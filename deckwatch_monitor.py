#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - DECKWATCH & NOW PLAYING MONITOR
================================================================================
Monitora em tempo real a faixa atualmente executada no Serato DJ Pro,
inspecionando sessões de histórico ativas e integrando com o macOS
para gerar arquivos compatíveis com OBS Studio e automações de streaming.
================================================================================
"""

import sys
import os
import json
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

sys.dont_write_bytecode = True


class DeckWatchMonitor:
    """Monitor de reprodução em tempo real para o Serato DJ Pro."""

    def __init__(self, serato_dir: Optional[str] = None):
        self.serato_dir = Path(os.path.expanduser(serato_dir or "~/Music/_Serato_")).resolve()
        self.history_dir = self.serato_dir / "History" / "Sessions"
        if not self.history_dir.exists():
            self.history_dir = self.serato_dir / "History"

    def is_serato_running(self) -> bool:
        """Verifica se o processo do Serato DJ Pro está em execução no sistema."""
        try:
            cmd = ["pgrep", "-f", "Serato DJ"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            return res.returncode == 0
        except Exception:
            return False

    def get_latest_played_track(self) -> Dict[str, Any]:
        """
        Lê a última sessão de histórico do Serato para capturar a faixa mais recente.
        """
        is_running = self.is_serato_running()
        result = {
            "serato_running": is_running,
            "artist": "",
            "title": "",
            "full_name": "",
            "played_at": "",
            "is_live": False
        }

        if not self.history_dir.is_dir():
            return result

        # Procura arquivos .session ou .csv mais recentes
        session_files = sorted(
            list(self.history_dir.glob("*.session")) + list(self.history_dir.glob("*.csv")),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if not session_files:
            return result

        latest_file = session_files[0]
        # Se o arquivo foi modificado nos últimos 15 minutos e o Serato está rodando, é ao vivo
        mtime_diff = (datetime.now().timestamp() - latest_file.stat().st_mtime)
        result["is_live"] = is_running and (mtime_diff < 900)

        # Parse rápido de faixa recente
        try:
            with open(latest_file, "rb") as f:
                content = f.read()

            # Em arquivos de sessão do Serato, os nomes das faixas vêm em blocos UTF-16-BE ou ASCII
            # Busca última ocorrência de ptrk ou strings de áudio
            for ext in [b'.mp3', b'.flac', b'.wav', b'.m4a', b'.aiff']:
                pos = content.rfind(ext)
                if pos != -1:
                    start = max(0, pos - 150)
                    chunk = content[start:pos+len(ext)]
                    # Tenta decodificar trecho
                    clean_chunk = "".join(chr(b) for b in chunk if 32 <= b <= 126 or b in (45, 95))
                    parts = clean_chunk.split("/")[-1].split("\\")[-1]
                    name_stem = parts.replace(ext.decode('ascii', errors='ignore'), '').strip()

                    if " - " in name_stem:
                        p = name_stem.split(" - ")
                        result["artist"] = p[0].strip()
                        result["title"] = " - ".join(p[1:]).strip()
                    else:
                        result["title"] = name_stem

                    result["full_name"] = f"{result['artist']} - {result['title']}".strip(" -")
                    result["played_at"] = datetime.fromtimestamp(latest_file.stat().st_mtime).strftime("%H:%M:%S")
                    break
        except Exception:
            pass

        return result

    def export_obs_files(self, output_dir: Path) -> Dict[str, str]:
        """Gera now_playing.txt e now_playing.json para o OBS Studio."""
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        track = self.get_latest_played_track()
        txt_path = output_dir / "now_playing.txt"
        json_path = output_dir / "now_playing.json"

        display_text = track.get("full_name") or "Nenhuma faixa em reprodução"
        txt_path.write_text(display_text, encoding="utf-8")
        json_path.write_text(json.dumps(track, indent=2, ensure_ascii=False), encoding="utf-8")

        return {
            "txt_path": str(txt_path),
            "json_path": str(json_path),
            "now_playing": display_text
        }


def main():
    parser = argparse.ArgumentParser(description="Serato DeckWatch Monitor")
    parser.add_argument("--serato", type=str, default="~/Music/_Serato_", help="Diretório _Serato_")
    parser.add_argument("--obs-dir", type=str, help="Gera arquivos now_playing no diretório especificado")
    parser.add_argument("--json", action="store_true", help="Saída em JSON")

    args = parser.parse_args()
    monitor = DeckWatchMonitor(args.serato)

    if args.obs_dir:
        res = monitor.export_obs_files(Path(args.obs_dir))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    track = monitor.get_latest_played_track()
    if args.json:
        print(json.dumps(track, indent=2, ensure_ascii=False))
    else:
        status = "🔴 AO VIVO" if track.get("is_live") else "⚪ Inativo"
        print(f"Status Serato: {status}")
        print(f"Tocando agora: {track.get('full_name') or 'Nenhuma'}")


if __name__ == "__main__":
    main()
