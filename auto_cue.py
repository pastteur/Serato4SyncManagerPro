#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - AUTO-CUE GENERATOR (auto_cue.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Gera e grava marcadores oficiais de Hot Cues para o Serato DJ Pro 4
(Intro, Drop 1, Breakdown, Drop 2, Outro) nas tags GEOB:Serato Markers2.
Suporta varredura e aplicação por Crate e Subcrate com streaming de progresso.
================================================================================
"""

import sys
import os
import json
import base64
import argparse
from pathlib import Path

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


def build_serato_cue_entry(index: int, pos_ms: int, color_bytes: bytes, label: str) -> bytearray:
    """
    Monta um bloco binário CUE oficial do Serato Markers2.
    Layout binário oficial (Holzhaus/serato-tags spec):
      00: uint8_t index (0..7)
      01: uint8_t flag (0x00)
      02-05: uint32_t position in milliseconds (LITTLE-ENDIAN)
      06: uint8_t separator (0x00)
      07-09: 3 bytes RGB color (ex: b'\xcc\x00\x00')
      0a-0b: 2 bytes padding (b'\x00\x00')
      0c..: UTF-8 label (null-terminated)
    """
    data = bytearray()
    data.append(index)                                              # Offset 00: índice do cue (0..7)
    data.append(0)                                                  # Offset 01: flag / byte nulo
    data.extend(int(pos_ms).to_bytes(4, byteorder='little'))        # Offset 02-05: posição ms (LITTLE-ENDIAN)
    data.append(0)                                                  # Offset 06: separador
    data.extend(color_bytes[:3])                                    # Offset 07-09: cor RGB (3 bytes)
    data.extend(b'\x00\x00')                                        # Offset 0a-0b: padding
    data.extend(label.encode('utf-8') + b'\x00')                    # Offset 0c..: label null-terminated

    entry = bytearray(b'CUE\x00')
    entry.extend(len(data).to_bytes(4, byteorder='big'))
    entry.extend(data)
    return entry


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


def generate_and_save_serato_cues(filepath_str: str):
    """
    Gera e aplica os Hot Cues na tag GEOB:Serato Markers2 do arquivo MP3.
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

        # Monta payload binário Serato Markers2 oficial
        # Estrutura decodificada oficial Serato DJ Pro:
        # 1. Magic bytes \x01\x01
        # 2. COLOR chunk: 'COLOR\0' + 4-byte len (4) + 4-byte data (\x00\xff\xff\xff)
        # 3. BPMLOCK chunk: 'BPMLOCK\0' + 4-byte len (1) + 1-byte data (\x00) + 1-byte pad (\x00)
        # 4. Sequência de blocos CUE oficiais
        inner = bytearray(b'\x01\x01COLOR\x00\x00\x00\x00\x04\x00\xff\xff\xffBPMLOCK\x00\x00\x00\x00\x01\x00\x00')
        for c in cues:
            color_bytes = CUE_COLORS.get(c["color"], b'\xcc\x00\x00')
            cue_block = build_serato_cue_entry(c["index"], c["pos_ms"], color_bytes, c["label"])
            inner.extend(cue_block)

        # Codifica em base64 com quebra de linha a cada 72 chars (padrão Serato)
        b64_raw = base64.b64encode(bytes(inner)).decode('ascii')
        b64_lines = '\n'.join(b64_raw[i:i+72] for i in range(0, len(b64_raw), 72))
        b64_bytes = b64_lines.encode('ascii')

        # Formato final Serato: \x01\x01 + base64, preenchido com null bytes (\x00) até 470 bytes mínimos
        serato_data = b'\x01\x01' + b64_bytes
        if len(serato_data) < 470:
            serato_data = serato_data.ljust(470, b'\x00')

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
            "mensagem": f"5 Hot Cues oficiais gerados com sucesso para o Serato."
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


def batch_apply_crate_cues(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True,
    only_pending: bool = False
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
        if only_pending and mutagen:
            try:
                audio = mutagen.File(str(full_p))
                if audio and 'GEOB:Serato Markers2' in audio:
                    continue
            except Exception:
                pass

        res = generate_and_save_serato_cues(str(full_p))
        if res.get("sucesso"):
            applied_count += 1
        else:
            errors.append(f"{full_p.name}: {res.get('erro')}")

        if idx % 10 == 0 or idx == total:
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
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Auto-Cue Generator")
    parser.add_argument("--preview", type=str, default="", help="Calcula prévia dos cues de uma música")
    parser.add_argument("--apply", type=str, default="", help="Grava Hot Cues no arquivo")
    parser.add_argument("--apply-batch", type=str, default="", help="JSON de lista de arquivos para aplicar em lote")
    parser.add_argument("--scan-crate", action="store_true", help="Varre Crate/Subcrate para listar faixas e cues")
    parser.add_argument("--batch-crate", action="store_true", help="Gera Hot Cues para toda a Crate")
    parser.add_argument("--mp3", type=str, default="", help="Pasta MP3 base")
    parser.add_argument("--crate-raiz", type=str, default="", help="Crate raiz")
    parser.add_argument("--subcrate", type=str, default="", help="Subcrate")
    parser.add_argument("--no-subcrates", action="store_true", help="Não incluir subcrates")
    parser.add_argument("--only-pending", action="store_true", help="Apenas faixas que ainda não possuem Hot Cues")
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

    if args.apply:
        res = generate_and_save_serato_cues(args.apply)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.apply_batch:
        try:
            files = json.loads(args.apply_batch)
            updated = 0
            for f in files:
                r = generate_and_save_serato_cues(f)
                if r.get("sucesso"):
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
            only_pending=args.only_pending
        )
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
