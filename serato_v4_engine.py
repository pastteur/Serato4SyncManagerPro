#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - SERATO v4 SQLite ENGINE & DOCTOR
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
            for c in candidates:
                if self._safe_exists(c / "master.sqlite") or self._safe_exists(c / "root.sqlite") or self._safe_exists(c / "location.sqlite"):
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

        report: Dict[str, Any] = {
            "library_dir": str(self.library_dir),
            "v4_detected": False,
            "healthy": False,
            "master_exists": master_exists,
            "root_exists": root_exists,
            "location_exists": location_exists,
            "db_uuid": None,
            "user_version": None,
            "autosync_disabled": None,
            "v3_migration_status": "Desconhecido",
            "containers_count": 0,
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
                if uuid_row:
                    report["db_uuid"] = str(uuid_row[0])
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
