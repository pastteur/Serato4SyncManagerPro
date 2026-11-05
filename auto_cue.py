#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - AUTO-CUE GENERATOR & REPAIR (auto_cue.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Gera, grava e repara marcadores oficiais de Hot Cues para o Serato DJ Pro 4
(Intro, Drop 1, Breakdown, Drop 2, Outro) nas tags GEOB:Serato Markers2.
Suporta varredura, aplicação por Crate/Subcrate e reparação de tags em lote
com streaming de progresso e backup de segurança blindado contra sobrescritas.
================================================================================
"""

import sys
import os
import json
import base64
import struct
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

try:
    import mutagen
    from mutagen.id3 import ID3, GEOB
except ImportError:
    mutagen = None

AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')

CUE_COLORS = {
    "red": b'\xcc\x00\x00',
    "blue": b'\x00\x66\xcc',
    "yellow": b'\xcc\xcc\x00',
    "green": b'\x00\xcc\x00',
    "orange": b'\xcc\x66\x00',
    "purple": b'\x99\x00\xcc'
}

BACKUP_DB_PATH = Path.home() / ".serato_sync_cues_backup.sqlite"


def get_backup_db():
    """Conecta e inicializa o banco SQLite de backups de segurança de Hot Cues."""
    conn = sqlite3.connect(str(BACKUP_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cues_backup (
            filepath TEXT PRIMARY KEY,
            filename TEXT,
            markers2_blob BLOB,
            markers1_blob BLOB,
            cues_json TEXT,
            created_at TEXT
        );
    """)
    conn.commit()
    return conn


def backup_track_cues(filepath: str, audio) -> bool:
    """Salva uma cópia exata das tags de cues antes de qualquer modificação."""
    if not audio or not hasattr(audio, 'tags') or audio.tags is None:
        return False
    try:
        m2 = audio.tags.get('GEOB:Serato Markers2')
        m1 = audio.tags.get('GEOB:Serato Markers_')
        m2_bytes = m2.data if m2 else None
        m1_bytes = m1.data if m1 else None

        if not m2_bytes and not m1_bytes:
            return False

        cues = extract_cues_from_raw_tag(m2_bytes) if m2_bytes else []
        cues_json = json.dumps(cues, ensure_ascii=False)

        conn = get_backup_db()
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO cues_backup 
                (filepath, filename, markers2_blob, markers1_blob, cues_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                str(filepath),
                Path(filepath).name,
                m2_bytes,
                m1_bytes,
                cues_json,
                datetime.now().isoformat()
            ))
        conn.close()
        return True
    except Exception:
        return False


def build_serato_markers2_tag(cues: list, color_rgb: bytes = b'\xff\xff\xff', bpmlock: bool = False) -> bytes:
    """
    Gera o payload binário GEOB:Serato Markers2 100% em conformidade com as especificações do Serato DJ Pro.
    Estrutura:
      1. Header mágico: \x01\x01
      2. Bloco COLOR: 'COLOR\x00' + >I len (4) + \x00 + 3-byte RGB
      3. Blocos CUE (0..7): 'CUE\x00' + >I len + (>cBIc3s2s + label\\x00)
      4. Bloco BPMLOCK: 'BPMLOCK\x00' + >I len (1) + 1 byte (\\x00 ou \\x01) — CRÍTICO: DEVE vir no final
      5. Empacotamento em Base64 com substituição obrigatória de '=' por 'A' (especificação Serato)
      6. Inserção de \\n (0x0A) a cada 72 caracteres
      7. \\x01\\x01 + base64_bytes, preenchido até 470 bytes mínimos com \\x00
    """
    entries = []

    # 1. COLOR entry
    color_data = b'\x00' + color_rgb[:3]
    entries.append(b'COLOR\x00' + struct.pack('>I', len(color_data)) + color_data)

    # 2. CUE entries
    for c in cues:
        label = c.get("label", "")
        label_bytes = label.encode('utf-8') + b'\x00'
        cue_color = c.get("color", b'\xcc\x00\x00')
        if isinstance(cue_color, str):
            cue_color = CUE_COLORS.get(cue_color, b'\xcc\x00\x00')

        # FMT = '>cBIc3s2s' (12 bytes de cabeçalho do cue + label null-terminated)
        cue_data = struct.pack(
            '>cBIc3s2s',
            b'\x00',
            int(c['index']) & 0x07,
            int(c['pos_ms']),
            b'\x00',
            cue_color[:3],
            b'\x00\x00'
        ) + label_bytes

        entries.append(b'CUE\x00' + struct.pack('>I', len(cue_data)) + cue_data)

    # 3. BPMLOCK entry (obrigatoriamente o último elemento)
    bpm_data = b'\x01' if bpmlock else b'\x00'
    entries.append(b'BPMLOCK\x00' + struct.pack('>I', len(bpm_data)) + bpm_data)

    # Monta payload binário completo
    payload = struct.pack('BB', 0x01, 0x01) + b''.join(entries)

    # Converte para base64 com substituição do padding '=' por 'A'
    b64_bytes = bytearray(base64.b64encode(payload).replace(b'=', b'A'))

    # Quebra de linha oficial a cada 72 caracteres
    i = 72
    while i < len(b64_bytes):
        b64_bytes.insert(i, 0x0A)
        i += 73

    # Empacota no frame final com cabeçalho \x01\x01 e preenchimento de 470 bytes
    tag_data = struct.pack('BB', 0x01, 0x01) + bytes(b64_bytes)
    if len(tag_data) < 470:
        tag_data = tag_data.ljust(470, b'\x00')

    return tag_data


def extract_cues_from_raw_tag(raw_data: bytes) -> list:
    """
    Extrai com segurança quaisquer Hot Cues já gravados no payload binário do Serato Markers2,
    mesmo que o payload tenha a anomalia do BPMLOCK ou ordenação truncada.
    """
    cues = []
    if not raw_data or len(raw_data) < 4:
        return cues

    try:
        null_pos = raw_data.find(b'\x00', 2)
        b64 = raw_data[2:null_pos] if null_pos != -1 else raw_data[2:]
        b64 = b64.replace(b'\n', b'').replace(b'\r', b'')
        padding = b'A==' if len(b64) % 4 == 1 else (b'=' * (-len(b64) % 4))
        payload = base64.b64decode(b64 + padding)

        pos = 2
        while pos < len(payload):
            null_idx = payload.find(b'\x00', pos)
            if null_idx == -1:
                break
            name = payload[pos:null_idx].decode('utf-8', errors='ignore')
            if not name:
                pos = null_idx + 1
                continue
            pos = null_idx + 1
            if pos + 4 > len(payload):
                break
            entry_len = struct.unpack('>I', payload[pos:pos+4])[0]
            pos += 4
            entry_data = payload[pos:pos+entry_len]
            pos += entry_len

            if name == 'CUE' and len(entry_data) >= 12:
                _, idx, ms, _, col, _ = struct.unpack('>cBIc3s2s', entry_data[:12])
                lbl = entry_data[12:].rstrip(b'\x00').decode('utf-8', errors='ignore')
                cues.append({
                    "index": idx,
                    "pos_ms": ms,
                    "label": lbl,
                    "color": col
                })
    except Exception:
        pass

    return cues


def calculate_smart_cues(duration_sec: float, bpm_float: float = 0.0):
    """
    Calcula os 5 pontos de Hot Cue ideais com base na métrica musical de DJs.
    """
    duration_ms = duration_sec * 1000

    # Tempo por compasso (4 tempos)
    if bpm_float > 0:
        bar_ms = (60.0 / bpm_float) * 4 * 1000
    else:
        bar_ms = 2000.0 # ~120 BPM padrão

    # 1. Intro: Primeiro beat (500 ms)
    pos_cue1 = 500

    # 2. Drop 1: 16 ou 32 compassos (cerca de 30s a 45s)
    drop1_target = bar_ms * 16
    if drop1_target < 20000:
        drop1_target = bar_ms * 32
    pos_cue2 = min(drop1_target, duration_ms * 0.25)

    # 3. Breakdown (Ponte): Meio da música - 8 compassos
    pos_cue3 = max(pos_cue2 + 15000, (duration_ms / 2.0) - (bar_ms * 4))

    # 4. Drop 2 (Clímax): Meio da música + 8 compassos
    pos_cue4 = min(duration_ms * 0.75, (duration_ms / 2.0) + (bar_ms * 8))

    # 5. Outro (Mix-out): 16 ou 32 compassos antes do fim
    pos_cue5 = max(pos_cue4 + 10000, duration_ms - (bar_ms * 16))

    cues = [
        {"index": 0, "label": "Intro", "pos_ms": int(pos_cue1), "color": "red", "color_hex": "#cc0000"},
        {"index": 1, "label": "Drop 1", "pos_ms": int(pos_cue2), "color": "blue", "color_hex": "#0066cc"},
        {"index": 2, "label": "Break", "pos_ms": int(pos_cue3), "color": "yellow", "color_hex": "#cccc00"},
        {"index": 3, "label": "Drop 2", "pos_ms": int(pos_cue4), "color": "green", "color_hex": "#00cc00"},
        {"index": 4, "label": "Outro", "pos_ms": int(pos_cue5), "color": "orange", "color_hex": "#cc6600"},
    ]
    return cues


def repair_track_cues(filepath_str: str) -> dict:
    """
    Repara o arquivo MP3 re-encodando a tag GEOB:Serato Markers2 com o layout binário perfeito.
    Restaura instantaneamente a visibilidade de todos os Hot Cues no Serato DJ Pro.
    """
    if not mutagen:
        return {"sucesso": False, "erro": "Mutagen não instalado"}

    file_p = Path(filepath_str)
    if not file_p.exists():
        return {"sucesso": False, "erro": "Arquivo não encontrado"}

    try:
        audio = mutagen.File(str(file_p))
        if audio is None:
            return {"sucesso": False, "erro": "Formato de áudio não suportado"}

        raw_tag = audio.tags.get('GEOB:Serato Markers2') if audio.tags else None
        if not raw_tag or not hasattr(raw_tag, 'data'):
            return {"sucesso": False, "erro": "Arquivo não possui tag Serato Markers2 para reparar"}

        existing_cues = extract_cues_from_raw_tag(raw_tag.data)
        if not existing_cues:
            # Se não conseguiu extrair cues antigos, recalcula usando duração e BPM
            duration = getattr(audio.info, 'length', 0.0)
            bpm_val = 0.0
            if 'TBPM' in audio:
                try: bpm_val = float(str(audio['TBPM']).split('.')[0])
                except Exception: pass
            existing_cues = calculate_smart_cues(duration, bpm_val)

        # Salva backup de segurança
        backup_track_cues(str(file_p), audio)

        # Constrói o novo payload perfeito
        new_tag_data = build_serato_markers2_tag(existing_cues)

        audio.tags['GEOB:Serato Markers2'] = GEOB(
            encoding=0,
            mime='application/octet-stream',
            desc='Serato Markers2',
            data=new_tag_data
        )

        # Limpa Markers_ legado conflitante se existir
        if 'GEOB:Serato Markers_' in audio.tags:
            del audio.tags['GEOB:Serato Markers_']

        # Salva em ID3v2.3 (mandatório Serato)
        audio.save(v2_version=3)

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "cues_reparados": len(existing_cues),
            "mensagem": f"{len(existing_cues)} Hot Cues reparados e ativados com sucesso para o Serato DJ Pro."
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def generate_and_save_serato_cues(filepath_str: str, overwrite_existing: bool = False):
    """
    Gera e aplica os Hot Cues na tag GEOB:Serato Markers2 do arquivo MP3.
    Por padrão protege contra sobrescrita de cues manuais pré-existentes.
    """
    if not mutagen:
        return {"sucesso": False, "erro": "Mutagen não instalado"}

    file_p = Path(filepath_str)
    if not file_p.exists():
        return {"sucesso": False, "erro": "Arquivo não encontrado"}

    try:
        audio = mutagen.File(str(file_p))
        if audio is None:
            return {"sucesso": False, "erro": "Formato de áudio não suportado"}

        # Proteção contra sobrescrita de cues existentes
        has_existing_cues = False
        if audio.tags:
            m2 = audio.tags.get('GEOB:Serato Markers2')
            if m2 and hasattr(m2, 'data'):
                cues_in_file = extract_cues_from_raw_tag(m2.data)
                if cues_in_file:
                    has_existing_cues = True

        if has_existing_cues and not overwrite_existing:
            return {
                "sucesso": True,
                "ignorado": True,
                "arquivo": file_p.name,
                "mensagem": "Faixa já possui Hot Cues gravados. Preservada com segurança."
            }

        duration = getattr(audio.info, 'length', 0.0)
        if duration < 10:
            return {"sucesso": False, "erro": "Áudio muito curto para Hot Cues"}

        bpm_val = 0.0
        if 'TBPM' in audio:
            try:
                bpm_val = float(str(audio['TBPM']).split('.')[0])
            except Exception:
                pass

        cues = calculate_smart_cues(duration, bpm_val)

        # Salva backup de segurança antes de alterar
        backup_track_cues(str(file_p), audio)

        # Monta payload binário Serato Markers2 oficial 100% compatível
        serato_data = build_serato_markers2_tag(cues)

        # Grava tag GEOB no arquivo MP3 com ID3v2.3 (obrigatório para Serato DJ Pro)
        if hasattr(audio, 'tags'):
            if audio.tags is None:
                audio.add_tags()

            audio.tags['GEOB:Serato Markers2'] = GEOB(
                encoding=0,
                mime='application/octet-stream',
                desc='Serato Markers2',
                data=serato_data
            )
            # Remove Markers_ legado se existir para evitar conflito de prioridade
            if 'GEOB:Serato Markers_' in audio.tags:
                del audio.tags['GEOB:Serato Markers_']

            # CRÍTICO: Serato DJ Pro requer ID3v2.3, NÃO v2.4
            audio.save(v2_version=3)

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "cues": cues,
            "mensagem": f"5 Hot Cues oficiais gerados e mapeados para o Serato DJ Pro."
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def scan_crate_cues(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True,
    limit: int = 150,
    offset: int = 0
):
    """Varre faixas da Crate ou Subcrate verificando existência de Hot Cues gravados."""
    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    if not base_path.exists():
        return {"sucesso": False, "erro": f"Pasta não encontrada: {base_path}"}

    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    if not target_dir.exists():
        return {"sucesso": True, "total": 0, "gravadas": 0, "pendentes": 0, "items": []}

    total_tracks = 0
    total_with_cues = 0
    items = []

    for root, dirs, files in os.walk(str(target_dir)):
        if '/.' in root or '\\.' in root:
            continue
        if crate_raiz and not include_subcrates and not subcrate:
            if root != str(target_dir):
                dirs.clear()
                continue
            dirs.clear()

        rel_folder = os.path.relpath(root, str(base_path))

        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            ext = Path(f).suffix.lower()
            if ext in ('.mp3', '.m4a', '.flac', '.wav', '.aiff'):
                total_tracks += 1
                full_p = Path(root) / f
                has_cues = False
                dur = 0.0
                bpm = 0.0

                if mutagen:
                    try:
                        audio = mutagen.File(str(full_p))
                        if audio is not None:
                            dur = getattr(audio.info, 'length', 0.0)
                            if 'TBPM' in audio:
                                try: bpm = float(str(audio['TBPM']).split('.')[0])
                                except Exception: pass
                            if 'GEOB:Serato Markers2' in audio:
                                raw_m2 = audio['GEOB:Serato Markers2'].data
                                cues_in = extract_cues_from_raw_tag(raw_m2)
                                if cues_in:
                                    has_cues = True
                    except Exception:
                        pass

                if has_cues:
                    total_with_cues += 1

                if total_tracks > offset and len(items) < limit:
                    crate_parts = [p for p in rel_folder.replace('\\', '/').split('/') if p]
                    c_raiz = crate_parts[0] if crate_parts else ""
                    items.append({
                        "id": f"cue-{total_tracks}",
                        "caminho": str(full_p),
                        "arquivo": f,
                        "pasta": rel_folder,
                        "crate": c_raiz,
                        "duracao_seg": round(dur, 1),
                        "bpm": round(bpm),
                        "tem_cues": has_cues,
                        "status": "Gravado" if has_cues else "Pendente"
                    })

    return {
        "sucesso": True,
        "total": total_tracks,
        "gravadas": total_with_cues,
        "pendentes": total_tracks - total_with_cues,
        "items": items
    }


def batch_repair_crate_cues(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True
):
    """Varre e repara o layout binário Serato Markers2 de todas as faixas que possuem cues."""
    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    files_to_process = []
    for root, dirs, files in os.walk(str(target_dir)):
        if '/.' in root or '\\.' in root:
            continue
        if crate_raiz and not include_subcrates and not subcrate:
            if root != str(target_dir):
                dirs.clear()
                continue
            dirs.clear()

        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            ext = Path(f).suffix.lower()
            if ext in ('.mp3', '.m4a', '.flac', '.wav', '.aiff'):
                files_to_process.append(Path(root) / f)

    total = len(files_to_process)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    repaired_count = 0
    errors = []

    for idx, full_p in enumerate(files_to_process, 1):
        try:
            audio = mutagen.File(str(full_p))
            if audio and 'GEOB:Serato Markers2' in audio:
                res = repair_track_cues(str(full_p))
                if res.get("sucesso"):
                    repaired_count += 1
                else:
                    errors.append(f"{full_p.name}: {res.get('erro')}")
        except Exception as e:
            errors.append(f"{full_p.name}: {str(e)}")

        if idx % 25 == 0 or idx == total:
            pct = round((idx / total) * 100, 1)
            print(json.dumps({
                "tipo": "progresso",
                "processados": idx,
                "total": total,
                "percentual": pct,
                "atualizados": repaired_count,
                "faixa_atual": full_p.name
            }, ensure_ascii=False), flush=True)

    print(json.dumps({
        "tipo": "fim",
        "sucesso": True,
        "total": total,
        "atualizados": repaired_count,
        "erros": errors[:10]
    }, ensure_ascii=False), flush=True)


def batch_apply_crate_cues(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True,
    only_pending: bool = False,
    overwrite_existing: bool = False
):
    """Gera e aplica Hot Cues para todas as faixas da Crate com streaming de progresso."""
    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    files_to_process = []
    for root, dirs, files in os.walk(str(target_dir)):
        if '/.' in root or '\\.' in root:
            continue
        if crate_raiz and not include_subcrates and not subcrate:
            if root != str(target_dir):
                dirs.clear()
                continue
            dirs.clear()

        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            ext = Path(f).suffix.lower()
            if ext in ('.mp3', '.m4a', '.flac', '.wav', '.aiff'):
                files_to_process.append(Path(root) / f)

    total = len(files_to_process)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    applied_count = 0
    errors = []

    for idx, full_p in enumerate(files_to_process, 1):
        if (only_pending or not overwrite_existing) and mutagen:
            try:
                audio = mutagen.File(str(full_p))
                if audio and 'GEOB:Serato Markers2' in audio:
                    cues_in = extract_cues_from_raw_tag(audio['GEOB:Serato Markers2'].data)
                    if cues_in:
                        continue
            except Exception:
                pass

        res = generate_and_save_serato_cues(str(full_p), overwrite_existing=overwrite_existing)
        if res.get("sucesso") and not res.get("ignorado"):
            applied_count += 1
        elif res.get("erro"):
            errors.append(f"{full_p.name}: {res.get('erro')}")

        if idx % 15 == 0 or idx == total:
            pct = round((idx / total) * 100, 1)
            print(json.dumps({
                "tipo": "progresso",
                "processados": idx,
                "total": total,
                "percentual": pct,
                "atualizados": applied_count,
                "faixa_atual": full_p.name
            }, ensure_ascii=False), flush=True)

    print(json.dumps({
        "tipo": "fim",
        "sucesso": True,
        "total": total,
        "atualizados": applied_count,
        "erros": errors[:10]
    }, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Auto-Cue Generator & Repair")
    parser.add_argument("--preview", type=str, default="", help="Calcula prévia dos cues de uma música")
    parser.add_argument("--apply", type=str, default="", help="Grava Hot Cues no arquivo")
    parser.add_argument("--repair-file", type=str, default="", help="Repara tags de Serato Markers2 em um arquivo")
    parser.add_argument("--repair-batch", action="store_true", help="Repara marcadores de toda a biblioteca/crate")
    parser.add_argument("--apply-batch", type=str, default="", help="JSON de lista de arquivos para aplicar em lote")
    parser.add_argument("--scan-crate", action="store_true", help="Varre Crate/Subcrate para listar faixas e cues")
    parser.add_argument("--batch-crate", action="store_true", help="Gera Hot Cues para toda a Crate")
    parser.add_argument("--mp3", type=str, default="", help="Pasta MP3 base")
    parser.add_argument("--crate-raiz", type=str, default="", help="Crate raiz")
    parser.add_argument("--subcrate", type=str, default="", help="Subcrate")
    parser.add_argument("--no-subcrates", action="store_true", help="Não incluir subcrates")
    parser.add_argument("--only-pending", action="store_true", help="Apenas faixas que ainda não possuem Hot Cues")
    parser.add_argument("--overwrite-existing", action="store_true", help="Sobrescrever cues pré-existentes")
    parser.add_argument("--limit", type=int, default=150, help="Limite de faixas na listagem")
    parser.add_argument("--offset", type=int, default=0, help="Offset de paginação")

    args = parser.parse_args()
    mp3_dir = args.mp3 or "/Volumes/Pastteyr/Music/MP3"

    if args.preview:
        file_p = Path(args.preview)
        if not file_p.exists():
            print(json.dumps({"sucesso": False, "erro": "Arquivo não encontrado"}))
            sys.exit(1)
        try:
            audio = mutagen.File(str(file_p))
            dur = getattr(audio.info, 'length', 0.0) if audio else 0.0
            bpm = 0.0
            if audio and 'TBPM' in audio:
                bpm = float(str(audio['TBPM']).split('.')[0])
            cues = calculate_smart_cues(dur, bpm)
            print(json.dumps({"sucesso": True, "duracao": dur, "bpm": bpm, "cues": cues}, ensure_ascii=False))
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}))
            sys.exit(1)

    if args.repair_file:
        res = repair_track_cues(args.repair_file)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.repair_batch:
        batch_repair_crate_cues(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates
        )
        sys.exit(0)

    if args.apply:
        res = generate_and_save_serato_cues(args.apply, overwrite_existing=args.overwrite_existing)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.apply_batch:
        try:
            files = json.loads(args.apply_batch)
            updated = 0
            for f in files:
                r = generate_and_save_serato_cues(f, overwrite_existing=args.overwrite_existing)
                if r.get("sucesso") and not r.get("ignorado"):
                    updated += 1
            print(json.dumps({"sucesso": True, "total": len(files), "atualizados": updated}))
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}))
            sys.exit(1)

    if args.scan_crate:
        res = scan_crate_cues(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates,
            limit=args.limit,
            offset=args.offset
        )
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

    if args.batch_crate:
        batch_apply_crate_cues(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates,
            only_pending=args.only_pending,
            overwrite_existing=args.overwrite_existing
        )
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
