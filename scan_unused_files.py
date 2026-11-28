#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 5 SYNC MANAGER PRO - SCAN UNUSED FILES (scan_unused_files.py)
================================================================================
Localiza arquivos de áudio no disco que NÃO estão presentes em nenhuma Crate
ou playlist do Serato DJ Pro. Identifica gigabytes desperdiçados no SSD
com opções seguras de quarentena, lixeira ou criação de Crate de revisão.
================================================================================
"""

import sys
import os
import json
import shutil
import argparse
from pathlib import Path
from typing import Dict, Any, List, Set, Optional

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')

try:
    from crate_ops import read_and_validate_crate, library_root_for
except ImportError:
    read_and_validate_crate = None
    library_root_for = None

try:
    from serato_v4_engine import SeratoV4Engine
except ImportError:
    SeratoV4Engine = None


class UnusedFilesScanner:
    """Escaneia o HD procurando faixas órfãs que não pertencem a nenhuma Crate."""

    def __init__(self, mp3_dir: str, serato_dir: str):
        self.mp3_dir = Path(os.path.expanduser(mp3_dir)).resolve()
        self.serato_dir = Path(os.path.expanduser(serato_dir)).resolve()

    def _collect_serato_tracks(self) -> Set[str]:
        """Extrai todos os caminhos exatos (normalizados) conhecidos pelas crates v3 e v4."""
        used_paths: Set[str] = set()
        lib_root = library_root_for(self.serato_dir) if library_root_for else self.serato_dir.parent

        def _add_path_variants(raw_p: str) -> None:
            if not raw_p:
                return
            norm = os.path.normpath(raw_p.strip()).replace('\\', '/').lstrip('/')
            used_paths.add(norm.lower())
            p = Path(raw_p)
            if p.is_absolute():
                used_paths.add(str(p.resolve()).lower())
                try:
                    used_paths.add(p.resolve().relative_to(self.mp3_dir).as_posix().lower())
                except Exception:
                    pass
                try:
                    used_paths.add(p.resolve().relative_to(lib_root).as_posix().lower())
                except Exception:
                    pass
            else:
                cand_lib = (lib_root / norm).resolve()
                used_paths.add(str(cand_lib).lower())
                cand_mp3 = (self.mp3_dir / norm).resolve()
                used_paths.add(str(cand_mp3).lower())

        # 1. Crates v3 (.crate) usando parser centralizado de crate_ops
        subcrates_dir = self.serato_dir / "Subcrates"
        if subcrates_dir.is_dir():
            for crate_file in sorted(subcrates_dir.glob("*.crate")):
                if crate_file.name.startswith("._") or crate_file.name.startswith("."):
                    continue
                if read_and_validate_crate:
                    try:
                        _, tracks, _ = read_and_validate_crate(crate_file)
                        for path_str in tracks:
                            _add_path_variants(path_str)
                        continue
                    except Exception:
                        pass
                try:
                    data = crate_file.read_bytes()
                    idx = 0
                    while True:
                        idx = data.find(b'ptrk', idx)
                        if idx == -1:
                            break
                        idx += 4
                        if idx + 4 <= len(data):
                            length = int.from_bytes(data[idx:idx+4], byteorder='big')
                            idx += 4
                            if idx + length <= len(data):
                                try:
                                    _add_path_variants(data[idx:idx+length].decode('utf-16-be'))
                                except UnicodeDecodeError:
                                    pass
                                idx += length
                except Exception:
                    pass

        # 2. Serato v4 SQLite (location.sqlite) apenas da biblioteca selecionada
        if SeratoV4Engine:
            v4_candidates = [
                self.serato_dir / "Library",
                self.serato_dir,
            ]
            for v4_cand in v4_candidates:
                try:
                    engine = SeratoV4Engine(str(v4_cand))
                    if engine.is_v4_present():
                        locations = engine.resolve_track_locations()
                        for p_str in locations.values():
                            _add_path_variants(p_str)
                        break
                except Exception:
                    pass

        return used_paths

    def scan(self) -> Dict[str, Any]:
        """Executa a varredura cruzada e retorna relatório detalhado de órfãos."""
        if not self.mp3_dir.is_dir():
            return {"sucesso": False, "erro": f"Diretório de músicas inválido: {self.mp3_dir}"}

        used_tracks = self._collect_serato_tracks()
        lib_root = library_root_for(self.serato_dir) if library_root_for else self.serato_dir.parent
        unused_files = []
        total_unused_bytes = 0
        total_scanned_files = 0

        for root, _, files in os.walk(str(self.mp3_dir)):
            if '/.' in root or '\\.' in root:
                continue
            for f in files:
                if f.startswith('._') or f.startswith('.'):
                    continue
                ext = Path(f).suffix.lower()
                if ext not in AUDIO_EXTENSIONS:
                    continue

                total_scanned_files += 1
                full_path = (Path(root) / f).resolve()
                rel_mp3 = full_path.relative_to(self.mp3_dir).as_posix().lower()
                rel_lib = ""
                try:
                    rel_lib = full_path.relative_to(lib_root).as_posix().lower()
                except Exception:
                    pass

                # Casamento apenas por caminho exato/relativo (nunca por basename isolado)
                if (
                    str(full_path).lower() not in used_tracks
                    and rel_mp3 not in used_tracks
                    and (not rel_lib or rel_lib not in used_tracks)
                ):
                    try:
                        size = full_path.stat().st_size
                    except OSError:
                        size = 0

                    total_unused_bytes += size
                    unused_files.append({
                        "filepath": str(full_path),
                        "filename": f,
                        "rel_path": str(full_path.relative_to(self.mp3_dir)),
                        "size_bytes": size,
                        "size_mb": round(size / (1024 * 1024), 2)
                    })

        return {
            "sucesso": True,
            "mp3_dir": str(self.mp3_dir),
            "total_scanned": total_scanned_files,
            "total_unused": len(unused_files),
            "total_unused_bytes": total_unused_bytes,
            "total_unused_gb": round(total_unused_bytes / (1024 * 1024 * 1024), 2),
            "unused_files": unused_files
        }

    def quarantine_files(self, files_list: List[str], dest_dir_name: str = "_Quarentena_Orfaos") -> Dict[str, Any]:
        """Move os arquivos órfãos selecionados para uma pasta segura de quarentena."""
        target_dir = self.mp3_dir / dest_dir_name
        target_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        errors = []

        for f_path in files_list:
            src = Path(f_path)
            if src.is_file():
                try:
                    # Preserva caminho relativo quando dentro de mp3_dir e evita colisão de nomes
                    try:
                        rel_parent = src.resolve().parent.relative_to(self.mp3_dir)
                        dest_folder = target_dir / rel_parent
                    except Exception:
                        dest_folder = target_dir
                    dest_folder.mkdir(parents=True, exist_ok=True)
                    dest = dest_folder / src.name
                    if dest.exists():
                        counter = 1
                        while True:
                            cand = dest_folder / f"{src.stem}_{counter}{src.suffix}"
                            if not cand.exists():
                                dest = cand
                                break
                            counter += 1
                    shutil.move(str(src), str(dest))
                    moved += 1
                except Exception as e:
                    errors.append(f"Erro ao mover {src.name}: {e}")

        return {
            "sucesso": len(errors) == 0,
            "moved_count": moved,
            "destination": str(target_dir),
            "errors": errors
        }


def main():
    parser = argparse.ArgumentParser(description="Scan Unused Files Engine")
    parser.add_argument("--mp3", type=str, required=True, help="Diretório de músicas Master")
    parser.add_argument("--serato", type=str, required=True, help="Diretório _Serato_")
    parser.add_argument("--json", action="store_true", help="Saída em formato JSON")
    parser.add_argument("--quarantine", action="store_true", help="Move arquivos para quarentena")
    parser.add_argument("--files", nargs="*", default=[], help="Lista de caminhos de arquivos para quarentena")
    parser.add_argument("--dest", type=str, default="_Quarentena_Orfaos", help="Nome da subpasta de quarentena")

    args = parser.parse_args()
    scanner = UnusedFilesScanner(args.mp3, args.serato)

    if args.quarantine:
        report = scanner.quarantine_files(args.files, dest_dir_name=args.dest)
    else:
        report = scanner.scan()

    if args.json or args.quarantine:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"Total escaneado: {report.get('total_scanned')}")
        print(f"Total órfãos:    {report.get('total_unused')} faixas ({report.get('total_unused_gb')} GB)")


if __name__ == "__main__":
    main()
