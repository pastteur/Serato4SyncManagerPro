#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - RECIPE ENGINE WITH UNDO (recipe_engine.py)
================================================================================
Executa receitas e transformadores de biblioteca com histórico transacional
e suporte completo a rollback (Undo).
================================================================================
"""

import sys
import os
import re
import json
import uuid
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import mutagen
    from mutagen.id3 import ID3, TIT2, TPE1
except ImportError:
    mutagen = None

DEFAULT_UNDO_DB = Path.home() / ".serato_recipe_history.sqlite"


class RecipeEngine:
    """Motor de execução de receitas em lote com snapshot e histórico de Undo."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path:
            self.db_path = Path(db_path).resolve()
        else:
            try:
                candidate = DEFAULT_UNDO_DB.resolve()
                candidate.parent.mkdir(parents=True, exist_ok=True)
                with open(candidate.parent / ".perm_check", "w") as f:
                    f.write("ok")
                (candidate.parent / ".perm_check").unlink()
                self.db_path = candidate
            except (PermissionError, OSError):
                self.db_path = (Path(__file__).resolve().parent / ".serato_recipe_history.sqlite").resolve()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recipe_sessions (
                    session_id TEXT PRIMARY KEY,
                    recipe_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    affected_count INTEGER NOT NULL,
                    is_undone INTEGER DEFAULT 0
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recipe_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    old_state_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES recipe_sessions(session_id)
                );
            """)
            conn.commit()

    def apply_recipe(self, recipe_name: str, filepaths: List[str], params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Aplica a receita em lote registrando snapshot de cada arquivo para desfazer."""
        session_id = str(uuid.uuid4())[:12]
        now_str = datetime.now().isoformat()
        params = params or {}

        snapshots = []
        processed_count = 0
        errors = []

        for f_path in filepaths:
            path = Path(f_path).resolve()
            if not path.is_file():
                continue

            try:
                audio = ID3(str(path))
            except Exception:
                continue

            old_state = {
                "title": str(audio["TIT2"]) if "TIT2" in audio else path.stem,
                "artist": str(audio["TPE1"]) if "TPE1" in audio else ""
            }

            # Aplica a transformação
            new_title = old_state["title"]
            new_artist = old_state["artist"]

            if recipe_name == "swap_artist_title":
                new_title, new_artist = old_state["artist"], old_state["title"]

            elif recipe_name == "title_case":
                new_title = old_state["title"].title()
                new_artist = old_state["artist"].title()

            elif recipe_name == "uppercase":
                new_title = old_state["title"].upper()
                new_artist = old_state["artist"].upper()

            elif recipe_name == "strip_brackets":
                new_title = re.sub(r'\[.*?\]', '', old_state["title"]).strip()
                new_title = re.sub(r'\s+', ' ', new_title)

            elif recipe_name == "strip_parentheses":
                new_title = re.sub(r'\(.*?\)', '', old_state["title"]).strip()
                new_title = re.sub(r'\s+', ' ', new_title)

            else:
                errors.append(f"Receita desconhecida: {recipe_name}")
                break

            # Grava alteração
            try:
                audio["TIT2"] = TIT2(encoding=3, text=new_title)
                if new_artist:
                    audio["TPE1"] = TPE1(encoding=3, text=new_artist)
                audio.save(str(path), v2_version=3)

                snapshots.append((session_id, str(path), json.dumps(old_state)))
                processed_count += 1
            except Exception as e:
                errors.append(f"Erro ao salvar {path.name}: {e}")

        # Salva a sessão de Undo se pelo menos um arquivo foi processado
        if snapshots:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO recipe_sessions (session_id, recipe_name, timestamp, affected_count, is_undone)
                    VALUES (?, ?, ?, ?, 0);
                """, (session_id, recipe_name, now_str, len(snapshots)))
                cursor.executemany("""
                    INSERT INTO recipe_snapshots (session_id, filepath, old_state_json)
                    VALUES (?, ?, ?);
                """, snapshots)
                conn.commit()

        return {
            "sucesso": processed_count > 0,
            "session_id": session_id,
            "recipe_name": recipe_name,
            "affected_count": processed_count,
            "errors": errors
        }

    def undo_last(self) -> Dict[str, Any]:
        """Desfaz a última sessão de receita ativa restaurando o estado original."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT session_id, recipe_name FROM recipe_sessions
                WHERE is_undone = 0
                ORDER BY timestamp DESC LIMIT 1;
            """)
            row = cursor.fetchone()
            if not row:
                return {"sucesso": False, "erro": "Nenhuma ação recente para desfazer"}

            session_id = row["session_id"]
            recipe_name = row["recipe_name"]

            cursor.execute("SELECT filepath, old_state_json FROM recipe_snapshots WHERE session_id = ?;", (session_id,))
            snaps = cursor.fetchall()

            restored_count = 0
            errors = []

            for s in snaps:
                path = Path(s["filepath"])
                if not path.is_file():
                    continue

                old_state = json.loads(s["old_state_json"])
                try:
                    audio = ID3(str(path))
                    audio["TIT2"] = TIT2(encoding=3, text=old_state.get("title", ""))
                    if old_state.get("artist"):
                        audio["TPE1"] = TPE1(encoding=3, text=old_state["artist"])
                    audio.save(str(path), v2_version=3)
                    restored_count += 1
                except Exception as e:
                    errors.append(f"Erro ao restaurar {path.name}: {e}")

            # Marca como revertida
            cursor.execute("UPDATE recipe_sessions SET is_undone = 1 WHERE session_id = ?;", (session_id,))
            conn.commit()

            return {
                "sucesso": restored_count > 0,
                "session_id": session_id,
                "recipe_name": recipe_name,
                "restored_count": restored_count,
                "errors": errors
            }


def main():
    parser = argparse.ArgumentParser(description="Recipe Engine with Undo")
    parser.add_argument("--recipe", type=str, choices=["swap_artist_title", "title_case", "uppercase", "strip_brackets", "strip_parentheses"])
    parser.add_argument("--files", nargs="+", help="Arquivos para aplicar a receita")
    parser.add_argument("--undo", action="store_true", help="Desfaz a última receita aplicada")

    args = parser.parse_args()
    engine = RecipeEngine()

    if args.undo:
        res = engine.undo_last()
        print(json.dumps(res, ensure_ascii=False))
        return

    if args.recipe and args.files:
        res = engine.apply_recipe(args.recipe, args.files)
        print(json.dumps(res, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
