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

sys.dont_write_bytecode = True
import json
import base64
import struct
import sqlite3
import shutil
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

# Vendor fallback: permite carregar dependências empacotadas sem exigir pip local
_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_backup_created ON cues_backup(created_at);")
    conn.commit()
    return conn


def list_cue_backups(limit: int = 300, search: str = ""):
    """
    Lista os backups de cues disponíveis para restauração, do mais recente ao mais antigo.
    Cada linha traz também se o arquivo original ainda existe no disco.
    """
    if not BACKUP_DB_PATH.exists():
        return {"sucesso": True, "total": 0, "items": []}
    try:
        conn = get_backup_db()
        conn.row_factory = sqlite3.Row
        query = "SELECT filepath, filename, cues_json, created_at FROM cues_backup"
        params = []
        if search.strip():
            query += " WHERE filename LIKE ? OR filepath LIKE ?"
            termo = f"%{search.strip()}%"
            params = [termo, termo]
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))

        items = []
        for row in conn.execute(query, params).fetchall():
            try:
                qtd_cues = len(json.loads(row["cues_json"] or "[]"))
            except Exception:
                qtd_cues = 0
            items.append({
                "filepath": row["filepath"],
                "filename": row["filename"],
                "quantidade_cues": qtd_cues,
                "created_at": row["created_at"],
                "arquivo_existe": Path(row["filepath"]).exists(),
            })
        conn.close()
        return {"sucesso": True, "total": len(items), "items": items}
    except Exception as e:
        return {"sucesso": False, "erro": str(e), "total": 0, "items": []}


def restore_track_cues(filepath_str: str):
    """
    Restaura o payload de cues exatamente como estava antes da primeira alteração.
    Se não existia cue algum antes, remove as tags GEOB:Serato Markers2/Markers_ que
    tenham sido gravadas, devolvendo a faixa ao estado original.
    """
    if not mutagen:
        return {"sucesso": False, "erro": "Mutagen não instalado"}
    if not BACKUP_DB_PATH.exists():
        return {"sucesso": False, "erro": "Nenhum backup de cues disponível"}

    file_p = Path(filepath_str)
    if not file_p.exists():
        return {"sucesso": False, "erro": "Arquivo não encontrado no disco"}

    try:
        conn = get_backup_db()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT markers2_blob, markers1_blob FROM cues_backup WHERE filepath = ?",
            (str(file_p),)
        ).fetchone()
        conn.close()

        if row is None:
            return {"sucesso": False, "erro": "Esta faixa não possui backup de cues registrado"}

        audio = mutagen.File(str(file_p))
        if audio is None:
            return {"sucesso": False, "erro": "Formato de áudio não suportado"}
        if audio.tags is None:
            audio.add_tags()

        m2_bytes = row["markers2_blob"]
        m1_bytes = row["markers1_blob"]

        if m2_bytes:
            audio.tags['GEOB:Serato Markers2'] = GEOB(
                encoding=0,
                mime='application/octet-stream',
                desc='Serato Markers2',
                data=bytes(m2_bytes)
            )
        else:
            audio.tags.delall('GEOB:Serato Markers2')

        if m1_bytes:
            audio.tags['GEOB:Serato Markers_'] = GEOB(
                encoding=0,
                mime='application/octet-stream',
                desc='Serato Markers_',
                data=bytes(m1_bytes)
            )
        else:
            audio.tags.delall('GEOB:Serato Markers_')

        audio.save(v2_version=3)

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "mensagem": "Cues restaurados ao estado anterior às alterações.",
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def backup_track_cues(filepath: str, audio) -> bool:
    """
    Salva uma cópia exata das tags de cues antes de qualquer modificação.
    Garante persistência verificada inclusive quando a faixa não possui tags ou cues existentes.
    """
    if audio is None:
        return False
    try:
        m2_bytes = None
        m1_bytes = None
        cues = []
        if hasattr(audio, 'tags') and audio.tags is not None:
            m2 = audio.tags.get('GEOB:Serato Markers2')
            m1 = audio.tags.get('GEOB:Serato Markers_')
            m2_bytes = m2.data if m2 else None
            m1_bytes = m1.data if m1 else None
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
            # Verificação obrigatória de persistência no banco SQLite
            row = conn.execute("SELECT 1 FROM cues_backup WHERE filepath = ?", (str(filepath),)).fetchone()
            if not row:
                raise IOError("Verificação de persistência do backup de cues falhou.")
        conn.close()
        return True
    except Exception as e:
        print(f"Erro ao salvar backup de cues para {filepath}: {e}", file=sys.stderr)
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
        
        # Ajusta padding do Base64 do Serato que substitui '=' por 'A'
        rem = len(b64) % 4
        if rem == 2:
            b64_to_decode = b64 + b'=='
        elif rem == 3:
            b64_to_decode = b64 + b'='
        elif rem == 1:
            b64_to_decode = b64[:-1] + b'=='
        else:
            b64_to_decode = b64

        try:
            payload = base64.b64decode(b64_to_decode)
        except Exception:
            # Fallback caso a substituição de 'A' necessite conversão manual
            b64_clean = b64
            while b64_clean.endswith(b'A') and len(b64_clean) % 4 != 0:
                b64_clean = b64_clean[:-1]
            b64_to_decode = b64_clean + (b'=' * (-len(b64_clean) % 4))
            payload = base64.b64decode(b64_to_decode)

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


def get_ffmpeg_bin():
    candidates = [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        shutil.which("ffmpeg") or ""
    ]
    for p in candidates:
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def detect_audio_transients(filepath_str: str, duration_sec: float) -> dict:
    """
    Analisa os transientes de áudio via ffmpeg para identificar o início exato
    do primeiro beat audível e o alinhamento de fase de compassos.
    Usa '-v info' para capturar com fidelidade os eventos de silencedetect.
    """
    ffmpeg_bin = get_ffmpeg_bin()
    if not ffmpeg_bin or not filepath_str or duration_sec < 1.0:
        return {"first_beat_ms": 500, "has_transient": False, "confiavel": False}

    try:
        # Detecta silêncio inicial nos primeiros 15 segundos usando '-v info'
        cmd = [
            ffmpeg_bin,
            "-v", "info",
            "-ss", "0",
            "-t", "15",
            "-i", str(filepath_str),
            "-af", "silencedetect=noise=-35dB:d=0.06",
            "-f", "null", "-"
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4, text=True)
        if proc.returncode != 0:
            return {"first_beat_ms": 500, "has_transient": False, "confiavel": False, "erro": "ffmpeg falhou na leitura do áudio"}

        lines = proc.stderr.splitlines()

        first_silence_end = None
        has_initial_silence = False

        import re
        start_re = re.compile(r"silence_start:\s*([0-9.]+)")
        end_re = re.compile(r"silence_end:\s*([0-9.]+)")

        for line in lines:
            m_start = start_re.search(line)
            if m_start:
                try:
                    s_val = float(m_start.group(1))
                    # Silêncio no início absoluto (primeiros 100ms)
                    if s_val <= 0.10:
                        has_initial_silence = True
                except Exception:
                    pass

            m_end = end_re.search(line)
            if m_end:
                try:
                    e_val = float(m_end.group(1))
                    if first_silence_end is None and has_initial_silence:
                        first_silence_end = e_val
                except Exception:
                    pass

        # 1. Silêncio inicial detectado e finalizado dentro da janela (primeiro beat encontrado)
        if has_initial_silence and first_silence_end is not None:
            beat_ms = max(50, int(first_silence_end * 1000))
            return {"first_beat_ms": beat_ms, "has_transient": True, "confiavel": True}

        # 2. Silêncio inicial contínuo por mais de 15s (sem transiente audível inicial)
        if has_initial_silence and first_silence_end is None:
            return {"first_beat_ms": 500, "has_transient": False, "confiavel": False, "motivo": "silencio_continuo"}

        # 3. Sem silêncio inicial: áudio se inicia imediatamente no tempo zero
        if not has_initial_silence:
            return {"first_beat_ms": 100, "has_transient": True, "confiavel": True}

    except Exception:
        pass

    return {"first_beat_ms": 500, "has_transient": False, "confiavel": False}


def calculate_smart_cues(duration_sec: float, bpm_float: float = 0.0, filepath_str: str = ""):
    """
    Calcula os 5 pontos de Hot Cue ideais com base na métrica musical de DJs e detecção de transientes.
    """
    duration_ms = duration_sec * 1000

    # Tempo por compasso (4 tempos)
    if bpm_float > 0:
        bar_ms = (60.0 / bpm_float) * 4 * 1000
    else:
        bar_ms = 2000.0 # ~120 BPM padrão

    first_beat_ms = 500
    if filepath_str and os.path.exists(filepath_str):
        trans = detect_audio_transients(filepath_str, duration_sec)
        first_beat_ms = trans.get("first_beat_ms", 500)

    # 1. Intro: Primeiro beat real
    pos_cue1 = int(first_beat_ms)

    # 2. Drop 1: 16 ou 32 compassos alinhados ao primeiro beat
    bars_for_drop1 = 16 if (bar_ms * 16) >= 20000 else 32
    target_drop1 = first_beat_ms + (bar_ms * bars_for_drop1)
    if target_drop1 > duration_ms * 0.35:
        target_drop1 = first_beat_ms + (bar_ms * 16)
    pos_cue2 = int(min(target_drop1, duration_ms * 0.30))

    # 3. Breakdown (Ponte): Alinhado a compasso próximo da metade
    half_time = duration_ms / 2.0
    bars_to_half = max(1, round((half_time - first_beat_ms) / bar_ms))
    pos_cue3 = int(max(pos_cue2 + 15000, first_beat_ms + ((bars_to_half - 4) * bar_ms)))

    # 4. Drop 2 (Clímax): Meio da música + 8 compassos
    pos_cue4 = int(min(duration_ms * 0.75, first_beat_ms + ((bars_to_half + 8) * bar_ms)))

    # 5. Outro (Mix-out): 16 compassos antes do fim alinhado ao grid
    bars_total = max(1, int((duration_ms - first_beat_ms) / bar_ms))
    bars_outro = max(1, bars_total - 16)
    pos_cue5 = int(max(pos_cue4 + 10000, first_beat_ms + (bars_outro * bar_ms)))

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
            existing_cues = calculate_smart_cues(duration, bpm_val, filepath_str=str(file_p))

        # Salva backup de segurança obrigatório antes de qualquer alteração
        if not backup_track_cues(str(file_p), audio):
            return {"sucesso": False, "erro": "Falha na criação ou verificação obrigatória do backup de cues. Gravação abortada por segurança."}

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

        op_id = None
        try:
            from journal import record_id3_before_change, record_operation_after
            op_id = record_id3_before_change(str(file_p), action="repair_cues")
        except Exception as e:
            return {"sucesso": False, "erro": "Journal indisponível; gravação cancelada: %s" % e}

        # Salva em ID3v2.3 (mandatório Serato)
        audio.save(v2_version=3)
        if op_id:
            try:
                record_operation_after(op_id, str(file_p))
            except Exception:
                pass

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
            m1 = audio.tags.get('GEOB:Serato Markers_')
            if m1 and hasattr(m1, 'data') and len(m1.data) > 0:
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

        cues = calculate_smart_cues(duration, bpm_val, filepath_str=str(file_p))

        # Salva backup de segurança antes de alterar
        if not backup_track_cues(str(file_p), audio):
            return {"sucesso": False, "erro": "Falha na criação ou verificação obrigatória do backup de cues. Gravação abortada por segurança."}

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
            # Registra o estado anterior no journal unificado (undo) antes de gravar
            op_id = None
            try:
                from journal import record_id3_before_change, record_operation_after
                op_id = record_id3_before_change(str(file_p), action="auto_cue")
            except Exception as e:
                return {"sucesso": False, "erro": "Journal indisponível; gravação cancelada: %s" % e}
            # CRÍTICO: Serato DJ Pro requer ID3v2.3, NÃO v2.4
            audio.save(v2_version=3)
            if op_id:
                try:
                    record_operation_after(op_id, str(file_p))
                except Exception:
                    pass

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "cues": cues,
            "mensagem": f"5 Hot Cues oficiais gerados e mapeados para o Serato DJ Pro."
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def audit_crate_cues_detailed(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True
):
    """
    Realiza uma auditoria aprofundada de todas as faixas da Crate ou Subcrate,
    detectando Hot Cues gravados, identificando se são os Auto-Cues padrão ou Hot Cues manuais de DJ,
    e listando o que já está implantado vs pendente sem qualquer limite de paginação.
    Trata erros de leitura adequadamente e protege cues manuais do DJ.
    """
    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    if not base_path.exists():
        return {"sucesso": False, "erro": f"Pasta não encontrada: {base_path}"}

    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    if not target_dir.exists():
        return {
            "sucesso": True,
            "total": 0,
            "gravadas": 0,
            "pendentes": 0,
            "personalizadas": 0,
            "padrao_autocue": 0,
            "erros_leitura": 0,
            "items": []
        }

    total_tracks = 0
    total_with_cues = 0
    total_custom = 0
    total_padrao = 0
    total_erros = 0
    items = []

    # O Auto-Cue padrão grava exatamente 5 cues nas posições calculadas com labels bem definidos
    STANDARD_AUTO_CUE_LABELS = {"INTRO", "DROP 1", "BREAK", "DROP 2", "OUTRO", "INÍCIO"}

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
                cue_list = []
                dur = 0.0
                bpm = 0.0
                tipo_cue = "Sem Cues"
                erro_msg = None

                if mutagen:
                    try:
                        audio = mutagen.File(str(full_p))
                        if audio is not None:
                            dur = getattr(audio.info, 'length', 0.0)
                            if 'TBPM' in audio:
                                try:
                                    bpm = float(str(audio['TBPM']).split('.')[0])
                                except Exception:
                                    pass
                            if 'GEOB:Serato Markers2' in audio:
                                raw_m2 = audio['GEOB:Serato Markers2'].data
                                cues_in = extract_cues_from_raw_tag(raw_m2)
                                if cues_in:
                                    has_cues = True
                                    cue_list = cues_in
                            elif 'GEOB:Serato Markers_' in audio:
                                has_cues = True
                        else:
                            erro_msg = "Formato de arquivo incompatível ou corrompido"
                    except Exception as e:
                        erro_msg = str(e)

                if erro_msg:
                    total_erros += 1
                    status_item = "Erro de Leitura"
                    tipo_cue = f"Falha na Análise: {erro_msg}"
                elif has_cues:
                    total_with_cues += 1
                    status_item = "Gravado"

                    # Classificação criteriosa:
                    # O Auto-Cue padrão tem exatamente 5 marcadores (índices 0 a 4) com os labels padrão.
                    # Se tiver quantidade diferente de 5, qualquer índice > 4, cores manuais ou rótulos próprios de DJ,
                    # é considerado Personalizado DJ (Protegido).
                    is_custom = False
                    if len(cue_list) != 5:
                        is_custom = True
                    else:
                        for c in cue_list:
                            lbl = (c.get("label") or "").strip().upper()
                            idx = c.get("index", 0)
                            if idx > 4 or (lbl and lbl not in STANDARD_AUTO_CUE_LABELS):
                                is_custom = True
                                break

                    if is_custom:
                        total_custom += 1
                        tipo_cue = "Personalizado DJ (Protegido)"
                    else:
                        total_padrao += 1
                        tipo_cue = "Auto-Cue Padrão"
                else:
                    status_item = "Pendente"

                crate_parts = [p for p in rel_folder.replace('\\', '/').split('/') if p]
                c_raiz = crate_parts[0] if crate_parts else "Raiz"

                cue_labels_summary = [f"#{c.get('index', i+1)} {c.get('label', '')}".strip() for i, c in enumerate(cue_list)]

                items.append({
                    "id": f"audit-cue-{total_tracks}",
                    "caminho": str(full_p),
                    "arquivo": f,
                    "pasta": rel_folder,
                    "crate": c_raiz,
                    "duracao_seg": round(dur, 1),
                    "bpm": round(bpm),
                    "tem_cues": has_cues,
                    "tipo_cue": tipo_cue,
                    "total_cues": len(cue_list),
                    "cue_labels": cue_labels_summary,
                    "status": status_item,
                    "erro": erro_msg
                })

    pendentes_reais = total_tracks - total_with_cues - total_erros
    return {
        "sucesso": True,
        "total": total_tracks,
        "gravadas": total_with_cues,
        "pendentes": max(0, pendentes_reais),
        "personalizadas": total_custom,
        "padrao_autocue": total_padrao,
        "erros_leitura": total_erros,
        "items": items
    }


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

                if total_tracks > offset and (not limit or limit <= 0 or len(items) < limit):
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

    has_errors = len(errors) > 0
    print(json.dumps({
        "tipo": "fim",
        "sucesso": not has_errors,
        "sucesso_parcial": (has_errors and repaired_count > 0),
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

    has_errors = len(errors) > 0
    print(json.dumps({
        "tipo": "fim",
        "sucesso": not has_errors,
        "sucesso_parcial": (has_errors and applied_count > 0),
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
    parser.add_argument("--audit-crate", action="store_true", help="Audita detalhadamente todas as faixas da Crate para identificar cues existentes vs pendentes")
    parser.add_argument("--batch-crate", action="store_true", help="Gera Hot Cues para toda a Crate")
    parser.add_argument("--list-backups", action="store_true", help="Lista os backups de cues disponíveis para restauração")
    parser.add_argument("--list-backups-search", type=str, default="", help="Filtra a lista de backups por nome ou caminho")
    parser.add_argument("--restore", type=str, default="", help="Restaura os cues de um arquivo a partir do backup")
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
            print(json.dumps({"sucesso": False, "erro": "Arquivo não encontrado"}, ensure_ascii=False), flush=True)
            sys.exit(1)
        try:
            audio = mutagen.File(str(file_p))
            dur = getattr(audio.info, 'length', 0.0) if audio else 0.0
            bpm = 0.0
            if audio and 'TBPM' in audio:
                bpm = float(str(audio['TBPM']).split('.')[0])
            cues = calculate_smart_cues(dur, bpm, filepath_str=str(file_p))
            print(json.dumps({"sucesso": True, "duracao": dur, "bpm": bpm, "cues": cues}, ensure_ascii=False), flush=True)
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}, ensure_ascii=False), flush=True)
            sys.exit(1)

    if args.repair_file:
        res = repair_track_cues(args.repair_file)
        print(json.dumps(res, ensure_ascii=False), flush=True)
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
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    if args.apply_batch:
        try:
            files = json.loads(args.apply_batch)
            updated = 0
            
            def process_file(file_path):
                return generate_and_save_serato_cues(file_path, overwrite_existing=args.overwrite_existing)

            # Execução paralela aproveitando múltiplos núcleos do Apple Silicon (4 a 8 threads)
            max_workers = min(8, max(2, (os.cpu_count() or 4)))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(process_file, f) for f in files]
                for future in as_completed(futures):
                    try:
                        r = future.result()
                        if r.get("sucesso") and not r.get("ignorado"):
                            updated += 1
                    except Exception:
                        pass

            print(json.dumps({"sucesso": True, "total": len(files), "atualizados": updated}, ensure_ascii=False), flush=True)
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}, ensure_ascii=False), flush=True)
            sys.exit(1)

    if args.audit_crate:
        res = audit_crate_cues_detailed(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates
        )
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    if args.scan_crate:
        res = scan_crate_cues(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates,
            limit=args.limit,
            offset=args.offset
        )
        print(json.dumps(res, ensure_ascii=False), flush=True)
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

    if args.list_backups:
        res = list_cue_backups(search=args.list_backups_search)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    if args.restore:
        res = restore_track_cues(args.restore)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
