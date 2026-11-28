#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 5 SYNC MANAGER PRO - SERATO v4 SQLite ENGINE & DOCTOR
================================================================================
Driver de leitura, inspeção e auditoria de integridade para a biblioteca
estruturada do Serato DJ Pro v4 (SQLite Engine).
================================================================================
"""

import sys
import os
import json
import sqlite3
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Caminhos padrão do Serato no macOS e Windows
DEFAULT_MACOS_SERATO_V4 = Path.home() / "Library" / "Application Support" / "Serato" / "Library"
DEFAULT_WIN_SERATO_V4 = Path(os.environ.get("LOCALAPPDATA", "")) / "Serato" / "Library" if os.environ.get("LOCALAPPDATA") else None


class SeratoV4Engine:
    """Engine de inspeção, auditoria e leitura da biblioteca SQLite do Serato DJ Pro 4."""

    def __init__(self, library_dir: Optional[str] = None):
        if library_dir:
            cand = Path(os.path.expanduser(library_dir)).resolve()
            # 1. Se o caminho passado tiver a subpasta Library ou for a própria pasta Library
            candidates = [
                cand / "Library",
                cand,
                cand.parent / "Library"
            ]
            # 2. Se for um caminho de volume externo (ex: /Volumes/Pastteyr/_Serato_)
            parts = cand.parts
            if len(parts) >= 3 and parts[1] == 'Volumes':
                ext_app_sup = Path(parts[0]) / parts[1] / parts[2] / "Library" / "Application Support" / "Serato" / "Library"
                candidates.append(ext_app_sup)

            selected_dir = None
            # Prioridade 1: pasta com master.sqlite ou root.sqlite (banco principal v4)
            for c in candidates:
                if self._safe_exists(c / "master.sqlite") or self._safe_exists(c / "root.sqlite"):
                    selected_dir = c
                    break

            # Prioridade 2: se foi passada uma pasta _Serato_ (que só tem .crates ou location.sqlite),
            # o Serato DJ Pro 4 armazena master.sqlite/root.sqlite no Application Support do usuário
            if not selected_dir and (cand.name == "_Serato_" or self._safe_exists(cand / "Subcrates")):
                sys_candidates = []
                if sys.platform == "darwin":
                    sys_candidates.extend([
                        DEFAULT_MACOS_SERATO_V4,
                        Path.home() / "Library" / "Application Support" / "Serato" / "Library",
                        Path.home() / "Library" / "Application Support" / "Serato"
                    ])
                elif sys.platform == "win32" and DEFAULT_WIN_SERATO_V4:
                    sys_candidates.append(DEFAULT_WIN_SERATO_V4)
                for c in sys_candidates:
                    if self._safe_exists(c / "master.sqlite") or self._safe_exists(c / "root.sqlite"):
                        selected_dir = c
                        break

            # Prioridade 3: fallback para diretórios que contenham apenas location.sqlite (ex: testes isolados)
            if not selected_dir:
                for c in candidates:
                    if self._safe_exists(c / "location.sqlite"):
                        selected_dir = c
                        break

            self.library_dir = selected_dir if selected_dir else (cand / "Library" if self._safe_exists(cand / "Library") else cand)
        else:
            candidates = []
            # Caminho canônico onde o Serato 4 armazena o banco SQLite no sistema operacional
            if sys.platform == "darwin":
                candidates.extend([
                    DEFAULT_MACOS_SERATO_V4,
                    Path.home() / "Library" / "Application Support" / "Serato" / "Library",
                    Path.home() / "Library" / "Application Support" / "Serato"
                ])
            elif sys.platform == "win32" and DEFAULT_WIN_SERATO_V4:
                candidates.append(DEFAULT_WIN_SERATO_V4)

            selected_dir = None
            for c in candidates:
                if self._safe_exists(c / "master.sqlite") or self._safe_exists(c / "root.sqlite") or self._safe_exists(c / "location.sqlite"):
                    selected_dir = c
                    break

            self.library_dir = selected_dir if selected_dir else DEFAULT_MACOS_SERATO_V4

        self.master_db = self.library_dir / "master.sqlite"
        self.root_db = self.library_dir / "root.sqlite"
        self.location_db = self.library_dir / "location.sqlite"
        self.streaming_db_files = {
            "remote_libraries": self.library_dir / "remote_libraries.sqlite",
            "apple_music": self.library_dir / "apple_music.sqlite",
            "beatport": self.library_dir / "beatport.sqlite",
            "soundcloud": self.library_dir / "soundcloud.sqlite",
            "spotify": self.library_dir / "spotify.sqlite",
        }

    def is_v4_present(self) -> bool:
        """Verifica se os arquivos do Serato v4 existem no diretório da biblioteca."""
        return self._safe_exists(self.library_dir) and (self._safe_exists(self.master_db) or self._safe_exists(self.root_db))

    def _connect_ro(self, db_path: Path) -> sqlite3.Connection:
        """Abre conexão SQLite em modo estritamente leitura (Read-Only) com URI."""
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.create_collation("serato_asset_string_comparator", lambda a, b: (a > b) - (a < b))
            conn.create_function("serato_str_norm", 1, lambda s: (s or "").lower())
            conn.create_function("serato_raw_key_string_to_key_type", 1, lambda k: 0)
        except Exception:
            pass
        return conn

    def _safe_exists(self, p: Path) -> bool:
        """Checa se o arquivo existe tratando possíveis restrições de permissão."""
        try:
            return p.exists()
        except (PermissionError, OSError):
            return False

    def audit_library(self) -> Dict[str, Any]:
        """
        Executa auditoria completa de sanidade e integridade da biblioteca Serato 4.
        Verifica:
          - Presença dos arquivos físicos
          - PRAGMA user_version e integridade do banco
          - UUID da base em serato_db
          - Status de sincronização v3 -> v4 em dbv2_status (autosync_disabled)
          - Quantidade de containers (crates/playlists)
          - Triggers registrados
        """
        master_exists = self._safe_exists(self.master_db)
        root_exists = self._safe_exists(self.root_db)
        location_exists = self._safe_exists(self.location_db)
        dir_exists = self._safe_exists(self.library_dir)

        streaming_dbs = {
            name: self._safe_exists(path)
            for name, path in self.streaming_db_files.items()
        }

        report: Dict[str, Any] = {
            "library_dir": str(self.library_dir),
            "v4_detected": False,
            "v5_features_detected": any(streaming_dbs.values()),
            "serato_generation": "Serato DJ Pro 5.x (SQLite + Stems/Streaming)" if any(streaming_dbs.values()) else "Serato 4/5 SQLite",
            "healthy": False,
            "master_exists": master_exists,
            "root_exists": root_exists,
            "location_exists": location_exists,
            "streaming_dbs": streaming_dbs,
            "db_uuid": None,
            "user_version": None,
            "autosync_disabled": None,
            "v3_migration_status": "Desconhecido",
            "containers_count": 0,
            "assets_count": 0,
            "smart_crate_rules_count": 0,
            "triggers_count": 0,
            "warnings": [],
            "errors": []
        }

        if not dir_exists:
            report["errors"].append(f"Diretório da biblioteca Serato inacessível ou não encontrado: {self.library_dir}")
            return report

        target_db = self.master_db if master_exists else self.root_db
        if not self._safe_exists(target_db):
            report["warnings"].append("Nenhum banco SQLite (master.sqlite / root.sqlite) acessível na pasta do Serato.")
            return report

        report["v4_detected"] = True

        try:
            conn = self._connect_ro(target_db)
            cursor = conn.cursor()

            # 1. PRAGMA user_version
            cursor.execute("PRAGMA user_version;")
            row = cursor.fetchone()
            report["user_version"] = row[0] if row else 0
            if report["user_version"] == 0:
                report["warnings"].append("PRAGMA user_version = 0 (banco não inicializado ou incompleto)")

            # 2. PRAGMA quick_check
            try:
                cursor.execute("PRAGMA quick_check;")
                check_res = cursor.fetchone()
                if check_res and check_res[0] != "ok":
                    report["errors"].append(f"Falha de integridade SQLite: {check_res[0]}")
            except Exception as e:
                report["warnings"].append(f"Não foi possível rodar PRAGMA quick_check: {e}")

            # 3. UUID em serato_db (se a tabela existir)
            try:
                cursor.execute("SELECT uuid FROM serato_db LIMIT 1;")
                uuid_row = cursor.fetchone()
                if uuid_row and uuid_row[0] is not None:
                    raw_uuid = uuid_row[0]
                    if isinstance(raw_uuid, (bytes, bytearray)):
                        if len(raw_uuid) == 16:
                            import uuid as _uuid
                            report["db_uuid"] = str(_uuid.UUID(bytes=bytes(raw_uuid)))
                        else:
                            report["db_uuid"] = bytes(raw_uuid).hex()
                    else:
                        report["db_uuid"] = str(raw_uuid)
            except sqlite3.OperationalError:
                # Tabela pode ter outro nome ou estar em root.sqlite
                pass

            # 4. dbv2_status (autosync_disabled)
            try:
                cursor.execute("SELECT autosync_disabled FROM dbv2_status LIMIT 1;")
                status_row = cursor.fetchone()
                if status_row:
                    report["autosync_disabled"] = int(status_row[0])
                    if report["autosync_disabled"] == 1:
                        report["v3_migration_status"] = "Migração Concluída (Serato v4 Independente)"
                    else:
                        report["v3_migration_status"] = "Sincronização Ativa (Serato v4 ainda importa v3 .crates)"
            except sqlite3.OperationalError:
                report["v3_migration_status"] = "Tabela dbv2_status ausente (estrutura legada ou personalizada)"

            # 5. Contagem de containers (crates)
            try:
                cursor.execute("SELECT COUNT(*) FROM container;")
                c_row = cursor.fetchone()
                report["containers_count"] = c_row[0] if c_row else 0
                if report["containers_count"] == 0:
                    report["warnings"].append("Nenhum container encontrado na tabela container.")
            except sqlite3.OperationalError:
                pass

            # 6. Triggers de integridade
            try:
                cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger';")
                trig_row = cursor.fetchone()
                report["triggers_count"] = trig_row[0] if trig_row else 0
            except sqlite3.OperationalError:
                pass

            # 7. Contagem de localizações (tabela location no SQLite ou arquivo location.sqlite)
            try:
                cursor.execute("SELECT COUNT(*) FROM location;")
                loc_row = cursor.fetchone()
                report["locations_count"] = loc_row[0] if loc_row else 0
                report["location_exists"] = True
            except sqlite3.OperationalError:
                report["locations_count"] = 0
                report["location_exists"] = location_exists

            # 8. Contagem de assets e smart_crate_rules (Serato 4/5)
            try:
                cursor.execute("SELECT COUNT(*) FROM asset;")
                asset_row = cursor.fetchone()
                report["assets_count"] = asset_row[0] if asset_row else 0
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("SELECT COUNT(*) FROM smart_crate_rules;")
                sc_row = cursor.fetchone()
                report["smart_crate_rules_count"] = sc_row[0] if sc_row else 0
            except sqlite3.OperationalError:
                pass

            conn.close()

            # Sanity check geral
            if not report["errors"]:
                report["healthy"] = True

        except Exception as e:
            report["errors"].append(f"Erro ao auditar banco Serato v4: {str(e)}")

        return report

    def list_containers(self) -> List[Dict[str, Any]]:
        """Lê a lista hierárquica de crates/containers do Serato 4."""
        target_db = self.master_db if self.master_db.exists() else self.root_db
        if not target_db.exists():
            return []

        containers = []
        try:
            conn = self._connect_ro(target_db)
            cursor = conn.cursor()

            # Consulta comum no schema Serato v4
            cursor.execute("""
                SELECT name, type FROM sqlite_master 
                WHERE type='table' AND name='container';
            """)
            if not cursor.fetchone():
                conn.close()
                return []

            # Inspeciona colunas disponíveis
            cursor.execute("PRAGMA table_info(container);")
            columns = [r["name"] for r in cursor.fetchall()]

            select_cols = ["id", "name"]
            for col in ["parent_id", "list_order", "color", "type"]:
                if col in columns:
                    select_cols.append(col)

            query = f"SELECT {', '.join(select_cols)} FROM container ORDER BY "
            if "list_order" in columns:
                query += "list_order ASC"
            else:
                query += "id ASC"

            cursor.execute(query)
            for row in cursor.fetchall():
                containers.append(dict(row))

            conn.close()
        except Exception as e:
            sys.stderr.write(f"[SeratoV4Engine] Erro ao listar containers: {e}\n")

        return containers

    def update_track_location(self, old_path: str, new_path: str) -> Dict[str, Any]:
        """
        Atualiza o caminho físico de um asset_id em location.sqlite ou master.sqlite (Injeção de Relocate v4).
        """
        target_db = self.location_db if self._safe_exists(self.location_db) else self.master_db
        if not self._safe_exists(target_db):
            return {"sucesso": False, "erro": "location.sqlite ou master.sqlite não encontrado"}

        try:
            conn = sqlite3.connect(str(target_db), timeout=5.0)
            cursor = conn.cursor()

            # Encontra a tabela que contém as colunas path e asset_id ou id
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [r[0] for r in cursor.fetchall()]

            target_table = None
            for t in tables:
                cursor.execute(f"PRAGMA table_info({t});")
                cols = [r[1] for r in cursor.fetchall()]
                if ("asset_id" in cols or "id" in cols) and "path" in cols:
                    target_table = t
                    break

            if not target_table:
                conn.close()
                return {"sucesso": False, "erro": f"Tabela de localizações não encontrada em {target_db.name}"}

            cursor.execute(f"UPDATE {target_table} SET path = ? WHERE path = ?;", (new_path, old_path))
            updated_rows = cursor.rowcount
            conn.commit()
            conn.close()

            return {
                "sucesso": updated_rows > 0,
                "rows_updated": updated_rows,
                "old_path": old_path,
                "new_path": new_path
            }
        except Exception as e:
            return {"sucesso": False, "erro": f"Falha ao injetar relocate em {target_db.name}: {e}"}

    def resolve_track_locations(self) -> Dict[int, str]:
        """
        Lê mapeamento de asset_id para caminhos de arquivo físicos contidos em location ou location.sqlite.
        Retorna dicionário {asset_id: filepath}.
        """
        locations: Dict[int, str] = {}
        target_dbs = [self.location_db, self.master_db]
        for db in target_dbs:
            if not self._safe_exists(db):
                continue
            try:
                conn = self._connect_ro(db)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [r["name"] for r in cursor.fetchall()]
                for t in tables:
                    cursor.execute(f"PRAGMA table_info({t});")
                    cols = [r["name"] for r in cursor.fetchall()]
                    id_col = "asset_id" if "asset_id" in cols else "id" if "id" in cols else None
                    if id_col and "path" in cols:
                        cursor.execute(f"SELECT {id_col}, path FROM {t} WHERE path IS NOT NULL;")
                        for r in cursor.fetchall():
                            locations[r[id_col]] = r["path"]
                        if locations:
                            break
                conn.close()
                if locations:
                    return locations
            except Exception as e:
                sys.stderr.write(f"[SeratoV4Engine] Erro ao ler localizações de {db}: {e}\n")

        return locations

    def collect_playback_analytics(self) -> Dict[str, Any]:
        """
        Coleta métricas de reprodução (dj_play_count / play_count), preparação
        (is_beatgrid_locked / overview_complete) e sessões (history_session) do Serato 4/5.
        """
        analytics: Dict[str, Any] = {
            "available": False,
            "total_db_assets": 0,
            "total_plays": 0,
            "play_distribution": {
                "0 plays": 0,
                "1–3 plays": 0,
                "4–10 plays": 0,
                "11+ plays": 0,
            },
            "zero_play_gb": 0.0,
            "beatgrid_locked_count": 0,
            "overview_complete_count": 0,
            "top_played_tracks": [],
            "top_played_genres": [],
            "recent_sessions": [],
        }

        target_db = self.master_db if self._safe_exists(self.master_db) else self.root_db
        if not self._safe_exists(target_db):
            return analytics

        try:
            conn = self._connect_ro(target_db)
            cur = conn.cursor()

            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {r["name"] for r in cur.fetchall()}

            if "asset" in tables:
                cur.execute("PRAGMA table_info(asset);")
                asset_cols = {r["name"] for r in cur.fetchall()}

                play_expr = "COALESCE(a.dj_play_count, 0)" if "dj_play_count" in asset_cols else "0"
                join_meta = ""
                if "dj_asset_metadata" in tables:
                    cur.execute("PRAGMA table_info(dj_asset_metadata);")
                    meta_cols = {r["name"] for r in cur.fetchall()}
                    if "asset_id" in meta_cols:
                        join_meta = "LEFT JOIN dj_asset_metadata m ON m.asset_id = a.id"
                        if "play_count" in meta_cols and "dj_play_count" in asset_cols:
                            play_expr = "MAX(COALESCE(a.dj_play_count, 0), COALESCE(m.play_count, 0))"
                        elif "play_count" in meta_cols:
                            play_expr = "COALESCE(m.play_count, 0)"
                        if "is_beatgrid_locked" in meta_cols:
                            cur.execute("SELECT SUM(CASE WHEN is_beatgrid_locked != 0 THEN 1 ELSE 0 END) FROM dj_asset_metadata;")
                            row_bg = cur.fetchone()
                            analytics["beatgrid_locked_count"] = int(row_bg[0] or 0) if row_bg else 0
                        if "overview_complete" in meta_cols:
                            cur.execute("SELECT SUM(CASE WHEN overview_complete != 0 THEN 1 ELSE 0 END) FROM dj_asset_metadata;")
                            row_ov = cur.fetchone()
                            analytics["overview_complete_count"] = int(row_ov[0] or 0) if row_ov else 0

                size_expr = "COALESCE(a.file_size, 0)" if "file_size" in asset_cols else "0"
                cur.execute(f"""
                    SELECT
                        COUNT(*),
                        SUM({play_expr}),
                        SUM(CASE WHEN ({play_expr}) = 0 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN ({play_expr}) BETWEEN 1 AND 3 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN ({play_expr}) BETWEEN 4 AND 10 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN ({play_expr}) >= 11 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN ({play_expr}) = 0 THEN {size_expr} ELSE 0 END)
                    FROM asset a
                    {join_meta};
                """)
                agg = cur.fetchone()
                if agg and agg[0]:
                    analytics["available"] = True
                    analytics["total_db_assets"] = int(agg[0] or 0)
                    analytics["total_plays"] = int(agg[1] or 0)
                    analytics["play_distribution"] = {
                        "0 plays": int(agg[2] or 0),
                        "1–3 plays": int(agg[3] or 0),
                        "4–10 plays": int(agg[4] or 0),
                        "11+ plays": int(agg[5] or 0),
                    }
                    analytics["zero_play_gb"] = round(float(agg[6] or 0) / (1024 ** 3), 2)

                # Top 15 faixas mais tocadas
                title_col = "a.title" if "title" in asset_cols else ("a.name" if "name" in asset_cols else "CAST(a.id AS TEXT)")
                artist_col = "a.artist" if "artist" in asset_cols else "''"
                bpm_col = "a.bpm" if "bpm" in asset_cols else "NULL"
                key_col = "a.key" if "key" in asset_cols else "''"
                cur.execute(f"""
                    SELECT {title_col} AS titulo, {artist_col} AS artista, {bpm_col} AS bpm, {key_col} AS key_val, ({play_expr}) AS plays
                    FROM asset a
                    {join_meta}
                    WHERE ({play_expr}) > 0
                    ORDER BY plays DESC
                    LIMIT 15;
                """)
                analytics["top_played_tracks"] = [
                    {
                        "titulo": r["titulo"] or "Sem título",
                        "artista": r["artista"] or "",
                        "bpm": r["bpm"],
                        "key": r["key_val"] or "",
                        "plays": int(r["plays"] or 0),
                    }
                    for r in cur.fetchall()
                ]

                # Top gêneros mais tocados
                if "genre" in asset_cols:
                    cur.execute(f"""
                        SELECT COALESCE(NULLIF(TRIM(a.genre), ''), 'Sem Gênero') AS genero, SUM({play_expr}) AS total_plays, COUNT(*) AS tracks
                        FROM asset a
                        {join_meta}
                        GROUP BY genero
                        HAVING total_plays > 0
                        ORDER BY total_plays DESC
                        LIMIT 10;
                    """)
                    analytics["top_played_genres"] = [
                        {"genero": r["genero"], "plays": int(r["total_plays"] or 0), "tracks": int(r["tracks"] or 0)}
                        for r in cur.fetchall()
                    ]

            # Sessões de histórico (history_session + history_entry)
            if "history_session" in tables:
                cur.execute("PRAGMA table_info(history_session);")
                hs_cols = {r["name"] for r in cur.fetchall()}
                name_expr = "hs.name" if "name" in hs_cols else "''"
                date_col = next((c for c in ("start_time", "created_at", "date", "timestamp") if c in hs_cols), None)
                date_expr = f"hs.{date_col}" if date_col else "''"
                if "history_entry" in tables:
                    cur.execute(f"""
                        SELECT hs.id, {name_expr} AS nome, {date_expr} AS data_ref, COUNT(he.id) AS faixas
                        FROM history_session hs
                        LEFT JOIN history_entry he ON he.session_id = hs.id
                        GROUP BY hs.id
                        ORDER BY hs.id DESC
                        LIMIT 10;
                    """)
                else:
                    cur.execute(f"""
                        SELECT hs.id, {name_expr} AS nome, {date_expr} AS data_ref, 0 AS faixas
                        FROM history_session hs
                        ORDER BY hs.id DESC
                        LIMIT 10;
                    """)
                analytics["recent_sessions"] = [
                    {
                        "id": r["id"],
                        "nome": r["nome"] or f"Sessão #{r['id']}",
                        "data": str(r["data_ref"] or ""),
                        "faixas": int(r["faixas"] or 0),
                    }
                    for r in cur.fetchall()
                ]

            conn.close()
        except Exception as e:
            sys.stderr.write(f"[SeratoV4Engine] Erro ao coletar playback analytics: {e}\n")

        return analytics


def main():
    parser = argparse.ArgumentParser(description="Auditor e Inspetor do Serato DJ Pro v4 SQLite Engine")
    parser.add_argument("--dir", type=str, default=None, help="Caminho do diretório Library do Serato")
    parser.add_argument("--audit", action="store_true", help="Executa auditoria de sanidade e integridade")
    parser.add_argument("--containers", action="store_true", help="Lista containers e crates do Serato v4")
    parser.add_argument("--json", action="store_true", help="Saída em formato JSON estruturado")

    args = parser.parse_args()
    engine = SeratoV4Engine(args.dir)

    if args.containers:
        containers = engine.list_containers()
        if args.json:
            print(json.dumps({"sucesso": True, "containers": containers}, ensure_ascii=False))
        else:
            print(f"Containers encontrados: {len(containers)}")
            for c in containers:
                print(f" - [{c.get('id')}] {c.get('name')} (ordem: {c.get('list_order')})")
        return

    # Padrão: auditoria
    report = engine.audit_library()
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print("=" * 70)
        print("SERATO DJ PRO v4 - AUDITORIA DE BIBLIOTECA SQLITE")
        print("=" * 70)
        print(f"Diretório:          {report['library_dir']}")
        print(f"v4 Detectado:       {'SIM' if report['v4_detected'] else 'NÃO'}")
        print(f"Saudável:           {'SIM' if report['healthy'] else 'NÃO'}")
        print(f"UUID da Base:       {report['db_uuid'] or 'N/A'}")
        print(f"Status Migração v3: {report['v3_migration_status']}")
        print(f"Containers:         {report['containers_count']}")
        print(f"Triggers:           {report['triggers_count']}")
        if report["warnings"]:
            print("\nAvisos:")
            for w in report["warnings"]:
                print(f" [!] {w}")
        if report["errors"]:
            print("\nErros:")
            for e in report["errors"]:
                print(f" [X] {e}")
        print("=" * 70)


if __name__ == "__main__":
    main()
