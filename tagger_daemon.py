#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 5 SYNC MANAGER PRO - HIGH SPEED TAGGER DAEMON (tagger_daemon.py)
================================================================================
Processo auxiliar especializado para leitura e gravação ultrarrápida de tags
ID3v2.3 (com preservação de Serato Markers2) comunicando via NDJSON sobre
pipes de stdin e stdout.
================================================================================
"""

import sys
import os
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

sys.dont_write_bytecode = True

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

try:
    import mutagen
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TBPM, TKEY, TDRC, COMM, GEOB
except ImportError:
    mutagen = None


class TaggerEngine:
    """Núcleo de manipulação de tags ID3v2.3 de alta performance."""

    @staticmethod
    def read_tags(filepath: str) -> Dict[str, Any]:
        """Lê metadados e marcadores Serato de um arquivo de áudio."""
        path = Path(filepath).resolve()
        if not path.is_file():
            return {"sucesso": False, "erro": f"Arquivo não encontrado: {filepath}"}

        res: Dict[str, Any] = {
            "sucesso": True,
            "filepath": str(path),
            "filename": path.name,
            "artist": "",
            "title": path.stem,
            "album": "",
            "genre": "",
            "bpm": 0.0,
            "key": "",
            "year": "",
            "comment": "",
            "has_serato_markers": False
        }

        if not mutagen:
            return {"sucesso": False, "erro": "Mutagen não está disponível no ambiente"}

        try:
            audio = ID3(str(path))
            if "TIT2" in audio:
                res["title"] = str(audio["TIT2"])
            if "TPE1" in audio:
                res["artist"] = str(audio["TPE1"])
            if "TALB" in audio:
                res["album"] = str(audio["TALB"])
            if "TCON" in audio:
                res["genre"] = str(audio["TCON"])
            if "TBPM" in audio:
                try:
                    res["bpm"] = float(str(audio["TBPM"]).strip())
                except ValueError:
                    pass
            if "TKEY" in audio:
                res["key"] = str(audio["TKEY"])
            if "TDRC" in audio:
                res["year"] = str(audio["TDRC"])

            for frame in audio.values():
                if frame.FrameID == "COMM":
                    res["comment"] = str(frame)
                elif frame.FrameID == "GEOB" and getattr(frame, "desc", "") in ("Serato Markers_", "Serato Markers2"):
                    res["has_serato_markers"] = True

        except Exception as e:
            res["sucesso"] = False
            res["erro"] = f"Falha ao ler tags ID3: {str(e)}"

        return res

    @staticmethod
    def write_tags(filepath: str, tags: Dict[str, Any]) -> Dict[str, Any]:
        """
        Grava metadados ID3v2.3 preservando estritamente frames GEOB do Serato.
        Força v2_version=3 para compatibilidade nativa com o Serato DJ Pro.
        """
        path = Path(filepath).resolve()
        if not path.is_file():
            return {"sucesso": False, "erro": f"Arquivo não encontrado: {filepath}"}

        if not mutagen:
            return {"sucesso": False, "erro": "Mutagen não está disponível no ambiente"}

        try:
            try:
                audio = ID3(str(path))
            except Exception:
                audio = ID3()

            if "title" in tags and tags["title"]:
                audio["TIT2"] = TIT2(encoding=3, text=str(tags["title"]))
            if "artist" in tags and tags["artist"]:
                audio["TPE1"] = TPE1(encoding=3, text=str(tags["artist"]))
            if "album" in tags and tags["album"]:
                audio["TALB"] = TALB(encoding=3, text=str(tags["album"]))
            if "genre" in tags and tags["genre"]:
                audio["TCON"] = TCON(encoding=3, text=str(tags["genre"]))
            if "bpm" in tags and tags["bpm"]:
                audio["TBPM"] = TBPM(encoding=3, text=str(tags["bpm"]))
            if "key" in tags and tags["key"]:
                audio["TKEY"] = TKEY(encoding=3, text=str(tags["key"]))
            if "year" in tags and tags["year"]:
                audio["TDRC"] = TDRC(encoding=3, text=str(tags["year"]))
            if "comment" in tags and tags["comment"]:
                audio["COMM"] = COMM(encoding=3, lang="eng", desc="", text=str(tags["comment"]))

            # Salva obrigatoriamente como ID3v2.3
            audio.save(str(path), v2_version=3)
            return {"sucesso": True, "filepath": str(path)}
        except Exception as e:
            return {"sucesso": False, "filepath": str(path), "erro": f"Falha ao gravar tags: {str(e)}"}


def run_daemon_loop():
    """Loop principal de escuta contínua de comandos NDJSON via stdin."""
    engine = TaggerEngine()
    print(json.dumps({"event": "ready", "version": "1.0.0", "pid": os.getpid()}), flush=True)

    for line in sys.stdin:
        line_clean = line.strip()
        if not line_clean:
            continue

        try:
            req = json.loads(line_clean)
        except json.JSONDecodeError as e:
            print(json.dumps({"sucesso": False, "erro": f"JSON inválido: {e}"}), flush=True)
            continue

        cmd = req.get("cmd")
        req_id = req.get("id")

        if cmd == "ping":
            resp = {"id": req_id, "sucesso": True, "status": "pong"}

        elif cmd == "read_tags":
            filepath = req.get("filepath", "")
            resp = engine.read_tags(filepath)
            resp["id"] = req_id

        elif cmd == "write_tags":
            filepath = req.get("filepath", "")
            tags = req.get("tags", {})
            resp = engine.write_tags(filepath, tags)
            resp["id"] = req_id

        elif cmd == "batch_read":
            files = req.get("files", [])
            results = [engine.read_tags(f) for f in files]
            resp = {"id": req_id, "sucesso": True, "total": len(files), "results": results}

        elif cmd == "batch_write":
            updates = req.get("updates", [])
            results = [engine.write_tags(u.get("filepath", ""), u.get("tags", {})) for u in updates]
            resp = {"id": req_id, "sucesso": True, "total": len(updates), "results": results}

        elif cmd == "quit":
            print(json.dumps({"id": req_id, "sucesso": True, "status": "terminating"}), flush=True)
            break

        else:
            resp = {"id": req_id, "sucesso": False, "erro": f"Comando desconhecido: '{cmd}'"}

        print(json.dumps(resp, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Tagger Daemon NDJSON Engine")
    parser.add_argument("--daemon", action="store_true", help="Inicia o loop contínuo de daemon sobre stdin/stdout")
    parser.add_argument("--read", type=str, help="Lê tags de um arquivo avulso")
    parser.add_argument("--write", type=str, help="Grava tags passadas em JSON via --tags")
    parser.add_argument("--tags", type=str, help="Objeto JSON contendo as tags a gravar")

    args = parser.parse_args()

    if args.read:
        res = TaggerEngine.read_tags(args.read)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if args.write:
        tags_dict = json.loads(args.tags) if args.tags else {}
        res = TaggerEngine.write_tags(args.write, tags_dict)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    # Padrão: loop NDJSON do Daemon
    run_daemon_loop()


if __name__ == "__main__":
    main()
