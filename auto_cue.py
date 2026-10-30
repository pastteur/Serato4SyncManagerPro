#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - AUTO-CUE GENERATOR (auto_cue.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Gera e grava marcadores oficiais de Hot Cues para o Serato DJ Pro 4
(Intro, Drop 1, Breakdown, Drop 2, Outro) nas tags GEOB:Serato Markers2.
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


CUE_COLORS = {
    "red": b'\xcc\x00\x00',
    "blue": b'\x00\x66\xcc',
    "yellow": b'\xcc\xcc\x00',
    "green": b'\x00\xcc\x00',
    "orange": b'\xcc\x66\x00',
    "purple": b'\x99\x00\xcc'
}


def build_serato_cue_entry(index: int, pos_ms: int, color_bytes: bytes, label: str) -> bytearray:
    """Monta um bloco binário CUE oficial do Serato."""
    data = bytearray()
    data.append(0)           # byte nulo
    data.append(index)       # índice do cue (0..7)
    data.extend(int(pos_ms).to_bytes(4, byteorder='big'))
    data.append(0)
    data.extend(color_bytes) # cor RGB (3 bytes)
    data.extend(b'\x00\x00')
    data.extend(label.encode('utf-8') + b'\x00')

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

        # Monta payload binário Serato Markers2
        payload = bytearray(b'\x01\x01COLOR\x00\x00\x00\x00\x04\x00\xff\xff\xffBPMLOCK\x00\x00\x00\x00\x01\x00\x00')
        for c in cues:
            color_bytes = CUE_COLORS.get(c["color"], b'\xcc\x00\x00')
            cue_block = build_serato_cue_entry(c["index"], c["pos_ms"], color_bytes, c["label"])
            payload.extend(cue_block)

        base64_str = base64.b64encode(payload)
        serato_data = b'\x01\x01' + base64_str

        # Grava tag GEOB no arquivo MP3
        if hasattr(audio, 'tags'):
            if audio.tags is None:
                audio.add_tags()

            audio.tags['GEOB:Serato Markers2'] = GEOB(
                encoding=0,
                mime='application/octet-stream',
                desc='Serato Markers2',
                data=serato_data
            )
            audio.save()

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "cues": cues,
            "mensagem": f"5 Hot Cues oficiais gerados com sucesso para o Serato."
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Auto-Cue Generator")
    parser.add_argument("--preview", type=str, default="", help="Calcula prévia dos cues de uma música")
    parser.add_argument("--apply", type=str, default="", help="Grava Hot Cues no arquivo")
    parser.add_argument("--apply-batch", type=str, default="", help="JSON de lista de arquivos para aplicar em lote")

    args = parser.parse_args()

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

    parser.print_help()


if __name__ == "__main__":
    main()
