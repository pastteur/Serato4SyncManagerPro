#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - BEATSHIFT SCANNER & KICK ALIGNMENT
================================================================================
Detecta e corrige faixas cujo primeiro beat (downbeat / kick) está deslocado
por meio tempo, 1/4 de tempo ou por milissegundos de silêncio inicial.
================================================================================
"""

import sys
import os
import json
import shutil
import subprocess
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import mutagen
    from mutagen.id3 import ID3, TBPM
except ImportError:
    mutagen = None


class BeatshiftScanner:
    """Escaneia o início do áudio procurando transientes de bumbo para checar fase do beatgrid."""

    @staticmethod
    def inspect_track(filepath: str) -> Dict[str, Any]:
        """
        Analisa a faixa procurando o primeiro pico de energia (downbeat)
        e cruza com o BPM registrado nas tags.
        """
        path = Path(filepath).resolve()
        if not path.is_file():
            return {"sucesso": False, "erro": "Arquivo não encontrado"}

        # 1. Lê BPM das tags ID3
        bpm = 120.0
        has_serato_grid = False
        if mutagen:
            try:
                audio = ID3(str(path))
                if "TBPM" in audio:
                    try:
                        bpm = float(str(audio["TBPM"]).strip())
                    except ValueError:
                        pass
                for frame in audio.values():
                    if frame.FrameID == "GEOB" and getattr(frame, "desc", "") == "Serato BeatGrid":
                        has_serato_grid = True
                        break
            except Exception:
                pass

        # 2. Usa ffmpeg para analisar silêncio inicial se disponível
        first_sound_ms = 0.0
        ffmpeg_bin = next(
            (
                p for p in [
                    str(Path(__file__).resolve().parent / "bin" / "ffmpeg"),
                    "/opt/homebrew/bin/ffmpeg",
                    "/usr/local/bin/ffmpeg",
                    shutil.which("ffmpeg") or "",
                ]
                if p and os.path.exists(p) and os.access(p, os.X_OK)
            ),
            None,
        )
        if ffmpeg_bin:
            try:
                cmd = [
                    ffmpeg_bin,
                    "-i", str(path),
                    "-t", "10",  # primeiros 10 segundos
                    "-af", "silencedetect=noise=-45dB:d=0.01",
                    "-f", "null",
                    "-"
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                # Analisa saída stderr para silence_end
                for line in res.stderr.splitlines():
                    if "silence_end:" in line:
                        parts = line.split("silence_end:")
                        if len(parts) > 1:
                            sec_str = parts[1].split()[0]
                            try:
                                first_sound_ms = float(sec_str) * 1000.0
                                break
                            except ValueError:
                                pass
            except Exception:
                first_sound_ms = 0.0

        # Duração de 1 beat em milissegundos
        beat_duration_ms = (60.0 / bpm) * 1000.0 if bpm > 0 else 500.0
        half_beat_ms = beat_duration_ms / 2.0
        quarter_beat_ms = beat_duration_ms / 4.0

        # Classificação de alinhamento
        offset_modulo = first_sound_ms % beat_duration_ms
        is_shifted = False
        shift_type = "Alinhado"

        if 40.0 < offset_modulo < beat_duration_ms - 40.0:
            is_shifted = True
            if abs(offset_modulo - half_beat_ms) < 45.0:
                shift_type = "Deslocamento de 1/2 Beat (Contratempo)"
            elif abs(offset_modulo - quarter_beat_ms) < 30.0 or abs(offset_modulo - (3 * quarter_beat_ms)) < 30.0:
                shift_type = "Deslocamento de 1/4 Beat (Fora de Fase)"
            else:
                shift_type = f"Silêncio Inicial Não Compensado ({round(first_sound_ms)}ms)"

        return {
            "sucesso": True,
            "filepath": str(path),
            "filename": path.name,
            "bpm": bpm,
            "has_serato_grid": has_serato_grid,
            "first_transient_ms": round(first_sound_ms, 1),
            "beat_duration_ms": round(beat_duration_ms, 1),
            "is_shifted": is_shifted,
            "shift_type": shift_type,
            "suggested_offset_ms": round(first_sound_ms, 1) if is_shifted else 0.0
        }


def main():
    parser = argparse.ArgumentParser(description="Beatshift & Kick Alignment Scanner")
    parser.add_argument("--file", type=str, required=True, help="Arquivo de áudio a inspecionar")
    parser.add_argument("--json", action="store_true", help="Saída formatada em JSON")

    args = parser.parse_args()
    report = BeatshiftScanner.inspect_track(args.file)

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"Faixa:       {report.get('filename')}")
        print(f"BPM:         {report.get('bpm')}")
        print(f"Primeiro Kick: {report.get('first_transient_ms')}ms")
        print(f"Status:      {report.get('shift_type')}")


if __name__ == "__main__":
    main()
