#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - PIONEER REKORDBOX USB EXPORTER
================================================================================
Engine de exportação de Crates e faixas do Serato DJ Pro para mídias USB
compatíveis com tocadores físicos Pioneer CDJ (CDJ-2000NXS2, CDJ-3000, XDJ,
Opus Quad) via banco SQLite Rekordbox 6/7 (exportLibrary.db).
================================================================================
"""

import sys
import os
import json
import uuid
import shutil
import sqlite3
import argparse
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Tenta carregar o parser de Cues do Serato existente no projeto
try:
    from auto_cue import extract_cues_from_raw_tag
except ImportError:
    extract_cues_from_raw_tag = None

try:
    import mutagen
except ImportError:
    mutagen = None


def _extract_serato_cues_from_file(filepath: str) -> List[Dict[str, Any]]:
    """Extrai Hot Cues do frame GEOB:Serato Markers2 via auto_cue.extract_cues_from_raw_tag."""
    if not mutagen or not extract_cues_from_raw_tag:
        return []
    audio = mutagen.File(str(filepath))
    if not audio or not getattr(audio, "tags", None):
        return []
    m2 = audio.tags.get("GEOB:Serato Markers2")
    if not m2 or not hasattr(m2, "data"):
        return []
    parsed = extract_cues_from_raw_tag(m2.data)
    out = []
    for c in parsed:
        col_hex = str(c.get("color", "#00cc00")).lstrip("#")
        rgb = (0, 204, 0)
        if len(col_hex) == 6:
            try:
                rgb = (int(col_hex[0:2], 16), int(col_hex[2:4], 16), int(col_hex[4:6], 16))
            except ValueError:
                pass
        out.append({
            "index": int(c.get("id", c.get("index", 0))),
            "position_ms": int(c.get("pos_ms", c.get("position_ms", 0))),
            "color_rgb": rgb,
            "label": str(c.get("name", c.get("label", "")) or f"Cue {int(c.get('id', 0)) + 1}"),
        })
    return out


def calc_quick_hash(filepath: Path) -> str:
    """
    Calcula um hash rápido e determinístico de integridade do arquivo de áudio:
    - Para arquivos <= 1MB: SHA-256 integral do arquivo.
    - Para arquivos > 1MB: SHA-256 composto pelo tamanho do arquivo em bytes,
      os primeiros 64 KB, 64 KB da região central e os últimos 64 KB.
    """
    if not filepath.is_file():
        return ""
    try:
        size = filepath.stat().st_size
        hasher = hashlib.sha256()
        hasher.update(str(size).encode("ascii"))
        chunk_size = 64 * 1024

        with open(filepath, "rb") as f:
            if size <= 1024 * 1024:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
            else:
                # Primeiros 64 KB
                hasher.update(f.read(chunk_size))
                # Meio 64 KB
                mid = max(0, (size // 2) - (chunk_size // 2))
                f.seek(mid)
                hasher.update(f.read(chunk_size))
                # Últimos 64 KB
                f.seek(max(0, size - chunk_size))
                hasher.update(f.read(chunk_size))
        return hasher.hexdigest()
    except Exception:
        return ""


def is_copy_up_to_date(src: Path, dest: Path) -> bool:
    """
    Verifica se a cópia no destino já está 100% atualizada comparando
    existência, tamanho exato em bytes e quick hash de integridade.
    """
    if not dest.is_file() or not src.is_file():
        return False
    try:
        src_stat = src.stat()
        dest_stat = dest.stat()
        if src_stat.st_size != dest_stat.st_size:
            return False
        return calc_quick_hash(src) == calc_quick_hash(dest)
    except Exception:
        return False


class PioneerUsbExporter:
    """Gerador da estrutura de pendrive Pioneer CDJ (exportLibrary.db)."""

    def __init__(self, target_drive_root: Path):
        self.drive_root = Path(target_drive_root).resolve()
        self.pioneer_dir = self.drive_root / "PIONEER" / "rekordbox"
        self.contents_dir = self.drive_root / "Contents"
        self.db_path = self.pioneer_dir / "exportLibrary.db"

    def init_export_db(self) -> sqlite3.Connection:
        """Cria os diretórios e inicializa o esquema SQLite compatível com Rekordbox 6/7."""
        self.pioneer_dir.mkdir(parents=True, exist_ok=True)
        self.contents_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = DELETE;")
        conn.execute("PRAGMA synchronous = NORMAL;")

        cursor = conn.cursor()

        # 1. Propriedades do Banco
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS djmdProperty (
                Key TEXT PRIMARY KEY,
                Value TEXT
            );
        """)
        cursor.execute("INSERT OR REPLACE INTO djmdProperty VALUES ('UUID', ?);", (str(uuid.uuid4()),))
        cursor.execute("INSERT OR REPLACE INTO djmdProperty VALUES ('Version', '1.0.0');")
        cursor.execute("INSERT OR REPLACE INTO djmdProperty VALUES ('ApplicationName', 'Serato4SyncPro-PioneerEngine');")

        # 2. Tabelas Auxiliares de Metadados
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS djmdArtist (
                ID TEXT PRIMARY KEY,
                Name TEXT UNIQUE
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS djmdAlbum (
                ID TEXT PRIMARY KEY,
                Name TEXT UNIQUE
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS djmdGenre (
                ID TEXT PRIMARY KEY,
                Name TEXT UNIQUE
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS djmdKey (
                ID TEXT PRIMARY KEY,
                ScaleName TEXT UNIQUE
            );
        """)

        # 3. Tabela Central de Faixas (djmdContent)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS djmdContent (
                ID TEXT PRIMARY KEY,
                FolderPath TEXT,
                FileNameL TEXT,
                FileNameS TEXT,
                Title TEXT,
                ArtistID TEXT,
                AlbumID TEXT,
                GenreID TEXT,
                BPM INTEGER,
                KeyID TEXT,
                Duration INTEGER,
                Rating INTEGER DEFAULT 0,
                BitRate INTEGER DEFAULT 320,
                SampleRate INTEGER DEFAULT 44100,
                BitDepth INTEGER DEFAULT 16,
                DateCreated TEXT,
                DateAdded TEXT
            );
        """)

        # 4. Playlists e Relacionamento
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS djmdPlaylist (
                ID TEXT PRIMARY KEY,
                ParentID TEXT,
                Name TEXT,
                Seq INTEGER,
                IsFolder INTEGER DEFAULT 0
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS djmdSongPlaylist (
                PlaylistID TEXT,
                ContentID TEXT,
                TrackNo INTEGER,
                PRIMARY KEY (PlaylistID, ContentID, TrackNo)
            );
        """)

        # 5. Marcadores de Cues (Hot Cues / Memory Cues)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS djmdCue (
                ID TEXT PRIMARY KEY,
                ContentID TEXT,
                CueType INTEGER,
                HotCueNumber INTEGER,
                InMsec INTEGER,
                ColorR INTEGER DEFAULT 0,
                ColorG INTEGER DEFAULT 255,
                ColorB INTEGER DEFAULT 0,
                Comment TEXT DEFAULT ''
            );
        """)

        conn.commit()
        return conn

    def _get_or_create_aux_id(self, cursor: sqlite3.Cursor, table: str, name: str) -> str:
        """Busca ou cria o ID de Artist, Album, Genre ou Key."""
        name_clean = (name or "").strip()
        if not name_clean:
            name_clean = "Unknown"

        col_name = "ScaleName" if table == "djmdKey" else "Name"
        cursor.execute(f"SELECT ID FROM {table} WHERE {col_name} = ?;", (name_clean,))
        row = cursor.fetchone()
        if row:
            return row["ID"]

        new_id = str(uuid.uuid4())[:8]
        cursor.execute(f"INSERT INTO {table} (ID, {col_name}) VALUES (?, ?);", (new_id, name_clean))
        return new_id

    def export_crate(self, crate_name: str, tracks: List[Dict[str, Any]], copy_audio: bool = True, dry_run: bool = False) -> Dict[str, Any]:
        """
        Exporta uma lista de faixas sob uma Playlist Pioneer, copiando arquivos para
        o pendrive com verificação de integridade e convertendo marcadores Serato Markers2 para Cues Pioneer.
        """
        operacao_id = str(uuid.uuid4())
        stats = {
            "sucesso": True,
            "operacao_id": operacao_id,
            "crate_name": crate_name,
            "total_tracks": len(tracks),
            "copied_tracks": 0,
            "skipped_up_to_date": 0,
            "cues_converted": 0,
            "total_bytes": 0,
            "errors": []
        }

        if dry_run:
            for t in tracks:
                p = Path(t.get("filepath", ""))
                if p.is_file():
                    stats["total_bytes"] += p.stat().st_size
                    stats["copied_tracks"] += 1
            return stats

        conn = self.init_export_db()
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()

        # Cria ou recupera a Playlist
        cursor.execute("SELECT ID FROM djmdPlaylist WHERE Name = ?;", (crate_name,))
        pl_row = cursor.fetchone()
        if pl_row:
            playlist_id = pl_row["ID"]
        else:
            playlist_id = str(uuid.uuid4())[:8]
            cursor.execute("SELECT COALESCE(MAX(Seq), 0) + 1 FROM djmdPlaylist;")
            next_seq = cursor.fetchone()[0]
            cursor.execute("INSERT INTO djmdPlaylist (ID, ParentID, Name, Seq, IsFolder) VALUES (?, 'root', ?, ?, 0);", (playlist_id, crate_name, next_seq))

        for idx, track_data in enumerate(tracks, 1):
            src_path = Path(track_data.get("filepath", "")).resolve()
            if not src_path.is_file():
                stats["errors"].append(f"Arquivo não encontrado: {src_path}")
                continue

            content_id = hashlib.sha256(str(src_path).encode("utf-8")).hexdigest()[:12]
            artist_name = track_data.get("artist") or "Artista Desconhecido"
            album_name = track_data.get("album") or "Álbum Desconhecido"
            title = track_data.get("title") or src_path.stem
            genre = track_data.get("genre") or "Geral"
            bpm = int(round(float(track_data.get("bpm") or 0.0) * 100))
            duration = int(track_data.get("duration_ms") or 0)

            # Destino no pendrive: /Contents/<Artist>/<Album>/<filename>
            artist_folder = "".join(c for c in artist_name if c.isalnum() or c in " .-_").strip() or "Artist"
            album_folder = "".join(c for c in album_name if c.isalnum() or c in " .-_").strip() or "Album"
            dest_dir = self.contents_dir / artist_folder / album_folder
            dest_file = dest_dir / src_path.name
            rel_folder = f"/Contents/{artist_folder}/{album_folder}"

            if copy_audio:
                try:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    if is_copy_up_to_date(src_path, dest_file):
                        stats["skipped_up_to_date"] += 1
                        stats["total_bytes"] += dest_file.stat().st_size
                    else:
                        # Cópia atômica via arquivo temporário com validação de hash pós-cópia
                        tmp_file = dest_dir / f".part_{uuid.uuid4().hex[:8]}_{src_path.name}"
                        try:
                            shutil.copy2(src_path, tmp_file)
                            src_hash = calc_quick_hash(src_path)
                            tmp_hash = calc_quick_hash(tmp_file)
                            if src_hash != tmp_hash:
                                if tmp_file.exists():
                                    tmp_file.unlink()
                                raise IOError(f"Falha na validação de integridade pós-cópia para '{src_path.name}'")
                            os.replace(tmp_file, dest_file)
                        except Exception:
                            if tmp_file.exists():
                                try:
                                    tmp_file.unlink()
                                except Exception:
                                    pass
                            raise
                        stats["copied_tracks"] += 1
                        stats["total_bytes"] += dest_file.stat().st_size
                except Exception as e:
                    stats["errors"].append(f"Falha ao copiar áudio '{src_path.name}': {e}")
                    continue

            # Mapeia chaves auxiliares
            artist_id = self._get_or_create_aux_id(cursor, "djmdArtist", artist_name)
            album_id = self._get_or_create_aux_id(cursor, "djmdAlbum", album_name)
            genre_id = self._get_or_create_aux_id(cursor, "djmdGenre", genre)
            key_id = self._get_or_create_aux_id(cursor, "djmdKey", track_data.get("key") or "1A")

            # Insere em djmdContent
            cursor.execute("""
                INSERT OR REPLACE INTO djmdContent (
                    ID, FolderPath, FileNameL, FileNameS, Title, ArtistID, AlbumID, GenreID,
                    BPM, KeyID, Duration, DateCreated, DateAdded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                content_id, rel_folder, src_path.name, src_path.name,
                title, artist_id, album_id, genre_id, bpm, key_id, duration,
                now_str, now_str
            ))

            # Associa à Playlist
            cursor.execute("""
                INSERT OR REPLACE INTO djmdSongPlaylist (PlaylistID, ContentID, TrackNo)
                VALUES (?, ?, ?);
            """, (playlist_id, content_id, idx))

            # Converte Hot Cues do Serato para djmdCue (evita duplicatas por ContentID na reexportação)
            cursor.execute("DELETE FROM djmdCue WHERE ContentID = ?;", (content_id,))
            serato_cues = []
            try:
                serato_cues = _extract_serato_cues_from_file(str(src_path))
            except Exception:
                pass

            for cue in serato_cues:
                pad_index = cue.get("index", 0)  # 0..7
                cue_id = hashlib.sha256(f"{content_id}:{pad_index}".encode("ascii")).hexdigest()[:12]
                pos_ms = cue.get("position_ms", 0)
                rgb = cue.get("color_rgb", (0, 255, 0))
                label = cue.get("label", f"Cue {pad_index + 1}")

                cursor.execute("""
                    INSERT OR REPLACE INTO djmdCue (
                        ID, ContentID, CueType, HotCueNumber, InMsec, ColorR, ColorG, ColorB, Comment
                    ) VALUES (?, ?, 2, ?, ?, ?, ?, ?, ?);
                """, (cue_id, content_id, pad_index, pos_ms, rgb[0], rgb[1], rgb[2], label))
                stats["cues_converted"] += 1

        conn.commit()
        conn.close()
        stats["sucesso"] = len(stats["errors"]) == 0
        return stats


def main():
    parser = argparse.ArgumentParser(description="Pioneer Rekordbox USB Exporter Engine")
    parser.add_argument("--usb", type=str, required=True, help="Ponto de montagem da unidade USB (ex: /Volumes/MEU_PENDRIVE)")
    parser.add_argument("--crate", type=str, required=True, help="Nome da Crate para exportar")
    parser.add_argument("--tracks", type=str, required=True, help="Caminho do arquivo JSON contendo a lista de faixas")
    parser.add_argument("--no-copy", action="store_true", help="Não copia os arquivos físicos (apenas gera banco)")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula e calcula tamanho total")

    args = parser.parse_args()

    with open(args.tracks, "r", encoding="utf-8") as f:
        tracks_data = json.load(f)

    tracks = tracks_data.get("tracks", tracks_data) if isinstance(tracks_data, dict) else tracks_data
    exporter = PioneerUsbExporter(Path(args.usb))
    res = exporter.export_crate(args.crate, tracks, copy_audio=not args.no_copy, dry_run=args.dry_run)

    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
