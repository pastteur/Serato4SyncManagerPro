#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - HIGH PERFORMANCE SQLite FTS5 CACHE
================================================================================
Banco local SQLite com Write-Ahead Logging (WAL) e Full-Text Search (FTS5)
com tokenizer 'unicode61 remove_diacritics 1' para busca e matching instantâneo
em acervos de 30.000+ faixas.
================================================================================
"""

import sys
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

DEFAULT_CACHE_PATH = Path.home() / ".serato_library_cache.sqlite"
AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')

VERSION_KEYWORDS = {
    'remix', 'mix', 'extended', 'radio', 'edit', 'club', 'dub',
    'instrumental', 'acapella', 'acapela', 'ao vivo', 'live',
    'acustico', 'acoustic', 'mashup', 'bootleg', 'vip', 'rework',
    'flip', 'cover', 'sped up', 'speed up', 'nightcore', 'slowed',
    'original mix', 'vocal mix', 'clean', 'dirty'
}


def extract_version_tags(text: str) -> str:
    """Extrai palavras de versão de um título ou nome de arquivo."""
    if not text:
        return ""
    found = set()
    lower = unicodedata.normalize('NFC', text.lower())
    matches = re.findall(r'[\(\[\{](.*?)[\)\]\}]', lower)
    for m in matches:
        tokens = re.sub(r'[^\w\s]', ' ', m).split()
        for tok in tokens:
            if tok in VERSION_KEYWORDS:
                found.add(tok)
    if ' - ' in lower:
        parts = lower.split(' - ')
        for tok in re.sub(r'[^\w\s]', ' ', parts[-1]).split():
            if tok in VERSION_KEYWORDS:
                found.add(tok)
    return " ".join(sorted(found))


class FTSLibraryCache:
    """Gerenciador do banco SQLite com índice de busca FTS5 para o acervo de áudio."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path:
            self.db_path = Path(db_path).resolve()
        else:
            try:
                candidate = DEFAULT_CACHE_PATH.resolve()
                candidate.parent.mkdir(parents=True, exist_ok=True)
                # Testa se pode escrever no diretório
                with open(candidate.parent / ".perm_check", "w") as f:
                    f.write("ok")
                (candidate.parent / ".perm_check").unlink()
                self.db_path = candidate
            except (PermissionError, OSError):
                # Fallback para pasta local do projeto
                self.db_path = (Path(__file__).resolve().parent / ".serato_library_cache.sqlite").resolve()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self):
        """Cria tabelas relacionais, tabela virtual FTS5 e triggers de sincronização."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    stem TEXT NOT NULL,
                    artist TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    remix_version TEXT DEFAULT '',
                    album TEXT DEFAULT '',
                    genre TEXT DEFAULT '',
                    bpm REAL DEFAULT 0.0,
                    key TEXT DEFAULT '',
                    duration_ms INTEGER DEFAULT 0,
                    crate_name TEXT DEFAULT '',
                    sound_seal TEXT DEFAULT '',
                    mtime REAL DEFAULT 0.0,
                    file_size INTEGER DEFAULT 0
                );
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_mtime ON tracks(mtime);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_sound_seal ON tracks(sound_seal);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_crate ON tracks(crate_name);")

            # Tabela virtual FTS5
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
                    title,
                    artist,
                    remix_version,
                    album,
                    crate_name,
                    stem,
                    filename,
                    content='tracks',
                    content_rowid='id',
                    tokenize = 'unicode61 remove_diacritics 1'
                );
            """)

            # Triggers de sincronização tracks -> tracks_fts
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS tracks_ai AFTER INSERT ON tracks BEGIN
                    INSERT INTO tracks_fts(rowid, title, artist, remix_version, album, crate_name, stem, filename)
                    VALUES (new.id, new.title, new.artist, new.remix_version, new.album, new.crate_name, new.stem, new.filename);
                END;
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS tracks_ad AFTER DELETE ON tracks BEGIN
                    INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, remix_version, album, crate_name, stem, filename)
                    VALUES('delete', old.id, old.title, old.artist, old.remix_version, old.album, old.crate_name, old.stem, old.filename);
                END;
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS tracks_au AFTER UPDATE ON tracks BEGIN
                    INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, remix_version, album, crate_name, stem, filename)
                    VALUES('delete', old.id, old.title, old.artist, old.remix_version, old.album, old.crate_name, old.stem, old.filename);
                    INSERT INTO tracks_fts(rowid, title, artist, remix_version, album, crate_name, stem, filename)
                    VALUES (new.id, new.title, new.artist, new.remix_version, new.album, new.crate_name, new.stem, new.filename);
                END;
            """)
            conn.commit()

    def sync_directory(self, base_dir: Path, tag_extractor=None) -> Dict[str, int]:
        """
        Indexa incrementalmente a pasta base de áudios.
        Atualiza apenas arquivos novos ou com mtime modificado.
        """
        stats = {"scanned": 0, "inserted": 0, "updated": 0, "unchanged": 0, "deleted": 0}
        base_dir = Path(base_dir).resolve()
        if not base_dir.is_dir():
            return stats

        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Carrega cache existente para comparação rápida em memória
            cursor.execute("SELECT filepath, mtime, file_size FROM tracks WHERE filepath LIKE ?", (f"{base_dir}%",))
            existing_files = {row["filepath"]: (row["mtime"], row["file_size"]) for row in cursor.fetchall()}

            seen_paths = set()
            to_insert = []
            to_update = []

            for root, _, files in os.walk(str(base_dir)):
                if '/.' in root or '\\.' in root:
                    continue
                rel_dir = os.path.relpath(root, str(base_dir))
                crate_label = rel_dir.replace('\\', ' -> ').replace('/', ' -> ') if rel_dir != '.' else "Raiz"

                for f in files:
                    if f.startswith('._') or f.startswith('.'):
                        continue
                    ext = Path(f).suffix.lower()
                    if ext not in AUDIO_EXTENSIONS:
                        continue

                    full_path = str(Path(root) / f)
                    seen_paths.add(full_path)
                    stats["scanned"] += 1

                    try:
                        stat = os.stat(full_path)
                        mtime = stat.st_mtime
                        file_size = stat.st_size
                    except OSError:
                        continue

                    stem = Path(f).stem
                    version_tags = extract_version_tags(stem)

                    if full_path in existing_files:
                        old_mtime, old_size = existing_files[full_path]
                        if abs(old_mtime - mtime) < 0.01 and old_size == file_size:
                            stats["unchanged"] += 1
                            continue

                        # Arquivo modificado: atualiza
                        meta = tag_extractor(full_path) if tag_extractor else {}
                        to_update.append((
                            f, stem,
                            meta.get("artist", ""), meta.get("title", ""),
                            meta.get("remix_version", version_tags),
                            meta.get("album", ""), meta.get("genre", ""),
                            meta.get("bpm", 0.0), meta.get("key", ""),
                            meta.get("duration_ms", 0), crate_label,
                            meta.get("sound_seal", ""),
                            mtime, file_size, full_path
                        ))
                    else:
                        # Arquivo novo: insere
                        meta = tag_extractor(full_path) if tag_extractor else {}
                        to_insert.append((
                            full_path, f, stem,
                            meta.get("artist", ""), meta.get("title", ""),
                            meta.get("remix_version", version_tags),
                            meta.get("album", ""), meta.get("genre", ""),
                            meta.get("bpm", 0.0), meta.get("key", ""),
                            meta.get("duration_ms", 0), crate_label,
                            meta.get("sound_seal", ""),
                            mtime, file_size
                        ))

            # Executa batches com transação
            if to_insert:
                cursor.executemany("""
                    INSERT INTO tracks (
                        filepath, filename, stem, artist, title, remix_version,
                        album, genre, bpm, key, duration_ms, crate_name, sound_seal,
                        mtime, file_size
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, to_insert)
                stats["inserted"] = len(to_insert)

            if to_update:
                cursor.executemany("""
                    UPDATE tracks SET
                        filename=?, stem=?, artist=?, title=?, remix_version=?,
                        album=?, genre=?, bpm=?, key=?, duration_ms=?, crate_name=?,
                        sound_seal=?, mtime=?, file_size=?
                    WHERE filepath=?;
                """, to_update)
                stats["updated"] = len(to_update)

            # Limpeza de arquivos removidos do disco
            deleted_paths = set(existing_files.keys()) - seen_paths
            if deleted_paths:
                cursor.executemany("DELETE FROM tracks WHERE filepath=?", [(p,) for p in deleted_paths])
                stats["deleted"] = len(deleted_paths)

            conn.commit()

        return stats

    def search_fts(self, query_string: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Executa busca por texto completo via FTS5 usando ranking BM25.
        Trata caracteres especiais para evitar erros de sintaxe FTS.
        """
        clean_query = re.sub(r'[^\w\s]', ' ', query_string).strip()
        if not clean_query:
            return []

        # Formata tokens para prefix search: "termo1* termo2*"
        tokens = [f'"{tok}"*' for tok in clean_query.split() if len(tok) > 1]
        if not tokens:
            return []
        match_expr = " AND ".join(tokens)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT t.*, bm25(tracks_fts) AS rank
                    FROM tracks_fts f
                    JOIN tracks t ON t.id = f.rowid
                    WHERE tracks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?;
                """, (match_expr, limit))
                return [dict(r) for r in cursor.fetchall()]
            except sqlite3.OperationalError:
                # Fallback para busca por tokens simples
                cursor.execute("""
                    SELECT t.*, 0 AS rank
                    FROM tracks_fts f
                    JOIN tracks t ON t.id = f.rowid
                    WHERE tracks_fts MATCH ?
                    LIMIT ?;
                """, (clean_query, limit))
                return [dict(r) for r in cursor.fetchall()]

    def find_match_candidates(self, title: str, artist: str = "", limit: int = 25) -> List[Dict[str, Any]]:
        """
        Retorna candidatos do catálogo com altíssima pontuação de relevância
        para cruzamento contra listas externas (Spotify, YouTube, etc.).
        """
        terms = []
        if title:
            # Extrai palavras chave principais do título
            for t in re.sub(r'[^\w\s]', ' ', title).split():
                if len(t) > 2 and t.lower() not in {"the", "and", "feat", "mix"}:
                    terms.append(f'"{t}"*')
        if artist:
            for a in re.sub(r'[^\w\s]', ' ', artist).split():
                if len(a) > 2 and a.lower() not in {"the", "and", "dj"}:
                    terms.append(f'"{a}"*')

        if not terms:
            return []

        match_expr = " OR ".join(terms[:8])
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT t.*, bm25(tracks_fts) AS rank
                    FROM tracks_fts f
                    JOIN tracks t ON t.id = f.rowid
                    WHERE tracks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?;
                """, (match_expr, limit))
                return [dict(r) for r in cursor.fetchall()]
            except Exception:
                return []


def main():
    import argparse
    parser = argparse.ArgumentParser(description="SQLite FTS5 Library Cache Engine")
    parser.add_argument("--sync", type=str, help="Sincroniza e indexa uma pasta de músicas")
    parser.add_argument("--search", type=str, help="Busca faixas por termo completo (FTS5)")
    parser.add_argument("--limit", type=int, default=20, help="Limite de resultados")

    args = parser.parse_args()
    cache = FTSLibraryCache()

    if args.sync:
        stats = cache.sync_directory(Path(args.sync))
        print(json.dumps({"sucesso": True, **stats}, ensure_ascii=False))

    elif args.search:
        results = cache.search_fts(args.search, limit=args.limit)
        print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
