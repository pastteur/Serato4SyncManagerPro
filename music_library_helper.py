#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - APPLE MUSIC / ITUNES LIBRARY HELPER
================================================================================
Integração nativa com a iTunesLibrary.framework no macOS para extração da
biblioteca do Apple Music (faixas, playlists e metadados) sem abrir a interface.
================================================================================
"""

import sys
import os
import json
import subprocess
import tempfile
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

sys.dont_write_bytecode = True

BIN_PATH = Path(__file__).resolve().parent / "bin" / "musiclibrary-helper"
SOURCE_M_PATH = Path(__file__).resolve().parent / "tools" / "musiclibrary_helper.m"


class MusicLibraryHelper:
    """Extrai e converte playlists e faixas da biblioteca Apple Music do macOS."""

    @classmethod
    def ensure_binary(cls) -> bool:
        """Garante que o binário compilado existe; se não, tenta compilar na hora."""
        if BIN_PATH.is_file() and os.access(BIN_PATH, os.X_OK):
            return True

        if sys.platform != "darwin":
            return False

        if not SOURCE_M_PATH.is_file():
            return False

        try:
            BIN_PATH.parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                "clang",
                "-framework", "Foundation",
                "-framework", "iTunesLibrary",
                "-O2",
                str(SOURCE_M_PATH),
                "-o", str(BIN_PATH)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return res.returncode == 0 and BIN_PATH.is_file()
        except Exception as e:
            sys.stderr.write(f"[MusicLibraryHelper] Erro ao compilar helper: {e}\n")
            return False

    @classmethod
    def extract_library(cls, output_json_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Invoca o binário nativo iTunesLibrary e retorna o JSON estruturado da coleção.
        """
        if sys.platform != "darwin":
            return {
                "sucesso": False,
                "erro": "Integração Apple Music (iTunesLibrary.framework) suportada exclusivamente no macOS."
            }

        if not cls.ensure_binary():
            return {
                "sucesso": False,
                "erro": "Binário musiclibrary-helper não disponível e não pôde ser compilado."
            }

        tmp_file = None
        target_path = output_json_path
        if not target_path:
            fd, tmp_file = tempfile.mkstemp(suffix=".json", prefix="musiclib_")
            os.close(fd)
            target_path = tmp_file

        try:
            cmd = [str(BIN_PATH), "--out", target_path]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode != 0:
                return {
                    "sucesso": False,
                    "erro": f"Helper retornou código de erro {res.returncode}: {res.stderr or res.stdout}"
                }

            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as e:
            return {
                "sucesso": False,
                "erro": f"Falha na execução do MusicLibraryHelper: {str(e)}"
            }
        finally:
            if tmp_file and os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    @classmethod
    def get_playlist_tracks(cls, playlist_name_or_id: str) -> List[Dict[str, Any]]:
        """
        Retorna a lista de faixas de uma playlist específica do Apple Music.
        """
        lib = cls.extract_library()
        if not lib.get("sucesso"):
            return []

        tracks_by_id = {t["id"]: t for t in lib.get("tracks", [])}
        target_pl = None

        for pl in lib.get("playlists", []):
            if pl["id"] == playlist_name_or_id or pl["name"].strip().lower() == playlist_name_or_id.strip().lower():
                target_pl = pl
                break

        if not target_pl:
            return []

        playlist_tracks = []
        for tid in target_pl.get("track_ids", []):
            if tid in tracks_by_id:
                playlist_tracks.append(tracks_by_id[tid])

        return playlist_tracks


def main():
    parser = argparse.ArgumentParser(description="Apple Music (macOS) Library Helper")
    parser.add_argument("--list-playlists", action="store_true", help="Lista todas as playlists do app Música")
    parser.add_argument("--playlist", type=str, help="Nome ou ID da playlist para extrair faixas")
    parser.add_argument("--out", type=str, help="Caminho do arquivo JSON de destino")
    parser.add_argument("--json", action="store_true", help="Saída formatada em JSON")

    args = parser.parse_args()

    if args.list_playlists:
        data = MusicLibraryHelper.extract_library()
        if not data.get("sucesso"):
            print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else f"Erro: {data.get('erro')}")
            sys.exit(1)

        playlists = data.get("playlists", [])
        if args.json:
            print(json.dumps({"sucesso": True, "playlists": playlists}, indent=2, ensure_ascii=False))
        else:
            print(f"Total de Playlists: {len(playlists)}")
            for pl in playlists:
                print(f" - [{pl['id']}] {pl['name']} ({pl['count']} faixas)")
        return

    if args.playlist:
        tracks = MusicLibraryHelper.get_playlist_tracks(args.playlist)
        if args.json:
            print(json.dumps({"sucesso": True, "playlist": args.playlist, "total": len(tracks), "tracks": tracks}, indent=2, ensure_ascii=False))
        else:
            print(f"Faixas na playlist '{args.playlist}': {len(tracks)}")
            for t in tracks:
                print(f" - {t.get('artist')} - {t.get('title')} ({t.get('filepath')})")
        return

    # Padrão: extrai toda a biblioteca
    result = MusicLibraryHelper.extract_library(args.out)
    if args.out:
        print(f"Biblioteca Apple Music salva com sucesso em: {args.out}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
