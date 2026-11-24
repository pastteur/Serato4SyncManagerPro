#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - CRATE OPERATIONS & PLAYLIST TOOLS (crate_ops.py)
================================================================================
Manipulação binária de arquivos .crate do Serato DJ Pro em _Serato_/Subcrates/
com atomicidade, preservação de cabeçalho vrsn, validação estrutural e backup.

Suporta:
- add_paths_to_crate: Adição de faixas relativas/absolutas
- prefix_crates: Adiciona prefixo no nome da crate ou subcrate
- capitalize_crates: Normaliza nomes de crates em Title Case
- sort_crate_tracks: Ordenação das faixas na crate (A-Z, Z-A, Shuffle)
- merge_crates: Fusão de múltiplas crates sem duplicatas
- rewrite_crate_order: Reordenação manual persistida na crate
================================================================================
"""

import os
import sys
import json
import uuid
import random
import shutil
import struct
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

sys.dont_write_bytecode = True

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from serato_macos_app import (
    parse_crate_binary, criar_tag_tlv, ler_faixas_crate_binaria, normalizar_nfc,
)


def library_root_for(serato_dir):
    p = Path(os.path.expanduser(str(serato_dir))).resolve()
    if str(p).startswith("/Volumes/"):
        return p.parent
    if p.parent == Path.home() or p.parent.parent == Path.home():
        return Path.home()
    return p.parent


def get_crate_path(subcrates_dir: Path, crate_name: str) -> Path:
    """Retorna o caminho seguro para o arquivo .crate em Subcrates."""
    safe = crate_name.replace('/', '%%').replace('\\', '%%')
    if not safe.endswith('.crate'):
        safe += '.crate'
    return subcrates_dir / safe


def write_crate_atomic(crate_path: Path, track_rel_list: List[str],
                       header_antigo: Optional[bytes] = None,
                       outros_blocos: Optional[List[bytes]] = None) -> Dict[str, Any]:
    """
    Grava uma lista de caminhos relativos em arquivo binário .crate com substituição
    atômica (UUID temp), fsync e verificação estrutural estrita.
    """
    crate_path.parent.mkdir(parents=True, exist_ok=True)
    crate_ja_existia = crate_path.exists()
    bak = crate_path.with_suffix('.bak')

    if crate_ja_existia:
        try:
            orig_size = crate_path.stat().st_size
            shutil.copy2(crate_path, bak)
            if not bak.exists() or bak.stat().st_size != orig_size:
                if bak.exists():
                    bak.unlink()
                return {"sucesso": False, "erro": "Falha na criação ou verificação de tamanho do backup .bak da crate."}
        except Exception as e_bak:
            return {"sucesso": False, "erro": f"Impossível criar backup da crate antes da alteração: {e_bak}"}

        if header_antigo is None or outros_blocos is None:
            try:
                data = crate_path.read_bytes()
                h, _, _, ob = parse_crate_binary(data)
                if header_antigo is None:
                    header_antigo = h
                if outros_blocos is None:
                    outros_blocos = ob
            except Exception:
                header_antigo = b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000'
                outros_blocos = []

    outros_blocos = outros_blocos or []
    tmp = crate_path.with_name(f".tmp_{crate_path.name}_{uuid.uuid4().hex[:8]}")

    try:
        with open(tmp, 'wb') as f:
            f.write(header_antigo if header_antigo and len(header_antigo) >= 8
                    else b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000')
            for b in outros_blocos:
                f.write(b)
            for rel in track_rel_list:
                ptrk = criar_tag_tlv('ptrk', rel)
                f.write(b'otrk' + struct.pack('>I', len(ptrk)) + ptrk)
            f.flush()
            os.fsync(f.fileno())

        # Validação estrutural do arquivo gerado antes de substituir o original
        if not tmp.exists() or tmp.stat().st_size < 16:
            raise IOError("Arquivo temporário da crate gerado incompleto ou vazio.")

        tmp_bytes = tmp.read_bytes()
        if not tmp_bytes.startswith(b'vrsn'):
            raise IOError("Estrutura da crate no arquivo temporário é inválida (vrsn ausente).")

        _, val_tracks, _, _ = parse_crate_binary(tmp_bytes)
        if len(val_tracks) != len(track_rel_list):
            raise IOError(f"Divergência estrutural de faixas ({len(val_tracks)} vs {len(track_rel_list)} esperadas).")

        # Substituição atômica no mesmo sistema de arquivos
        os.replace(tmp, crate_path)
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        return {"sucesso": False, "erro": str(e)}

    return {
        "sucesso": True,
        "crate": crate_path.name,
        "caminho": str(crate_path),
        "backup": str(bak) if crate_ja_existia else None,
        "total": len(track_rel_list)
    }


def add_paths_to_crate(serato_dir: str, crate_name: str, abs_paths: List[str]) -> Dict[str, Any]:
    """Adiciona faixas (caminhos absolutos) a uma crate mantendo faixas existentes."""
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    crate_path = get_crate_path(subcrates, crate_name)
    root = library_root_for(serato)

    relativos = []
    rejeitados = []
    for raw in abs_paths:
        p = Path(os.path.expanduser(str(raw)))
        try:
            rel = str(p.resolve().relative_to(root.resolve()))
        except ValueError:
            rejeitados.append({"arquivo": str(raw), "motivo": f"fora da raiz da biblioteca ({root})"})
            continue
        if not p.exists():
            rejeitados.append({"arquivo": str(raw), "motivo": "arquivo não encontrado"})
            continue
        relativos.append(normalizar_nfc(rel))

    if not relativos:
        return {"sucesso": False, "erro": "Nenhum caminho válido dentro da raiz da biblioteca",
                "raiz": str(root), "rejeitados": rejeitados}

    header_antigo = None
    existentes = []
    outros_blocos = []

    if crate_path.exists():
        try:
            data = crate_path.read_bytes()
            header_antigo, existentes, _, outros_blocos = parse_crate_binary(data)
        except Exception:
            pass

    final = list(existentes)
    adicionados = 0
    for rel in relativos:
        if rel not in final:
            final.append(rel)
            adicionados += 1

    res = write_crate_atomic(crate_path, final, header_antigo, outros_blocos)
    if not res["sucesso"]:
        return res

    res.update({
        "adicionados": adicionados,
        "raiz": str(root),
        "rejeitados": rejeitados,
        "mensagem": f"{adicionados} faixa(s) adicionada(s) à crate [{crate_path.stem}] ({len(final)} no total)."
    })
    return res


def sort_crate_tracks(serato_dir: str, crate_name: str, sort_mode: str = "az") -> Dict[str, Any]:
    """
    Ordena as faixas dentro de uma crate e reescreve o binário.
    sort_mode: 'az' (A-Z pelo nome do arquivo), 'za' (Z-A), 'shuffle' (aleatório).
    """
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    crate_path = get_crate_path(subcrates, crate_name)

    if not crate_path.exists():
        return {"sucesso": False, "erro": f"Crate não encontrada: {crate_name}"}

    try:
        data = crate_path.read_bytes()
        header_antigo, existentes, _, outros_blocos = parse_crate_binary(data)
    except Exception as e:
        return {"sucesso": False, "erro": f"Erro ao ler crate: {e}"}

    if not existentes:
        return {"sucesso": True, "crate": crate_name, "total": 0, "mensagem": "Crate vazia."}

    sorted_tracks = list(existentes)
    if sort_mode == "az":
        sorted_tracks.sort(key=lambda p: Path(p).name.lower())
    elif sort_mode == "za":
        sorted_tracks.sort(key=lambda p: Path(p).name.lower(), reverse=True)
    elif sort_mode == "shuffle":
        random.shuffle(sorted_tracks)
    elif sort_mode == "path":
        sorted_tracks.sort(key=lambda p: p.lower())
    else:
        return {"sucesso": False, "erro": f"Modo de ordenação inválido: {sort_mode}"}

    res = write_crate_atomic(crate_path, sorted_tracks, header_antigo, outros_blocos)
    if res["sucesso"]:
        res["mensagem"] = f"Crate [{crate_name}] reordenada com sucesso ({sort_mode.upper()} - {len(sorted_tracks)} faixas)."
    return res


def prefix_crate(serato_dir: str, crate_name: str, prefix: str, target: str = "subcrate") -> Dict[str, Any]:
    """
    Adiciona um prefixo no nome da crate ou subcrate.
    Ex: 'Sertanejo%%41' com prefixo '01. ' e target='subcrate' -> 'Sertanejo%%01. 41.crate'.
    """
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    old_crate_path = get_crate_path(subcrates, crate_name)

    if not old_crate_path.exists():
        return {"sucesso": False, "erro": f"Crate original não encontrada: {crate_name}"}

    clean_name = old_crate_path.stem
    parts = clean_name.split('%%')

    if target == "master" or len(parts) == 1:
        parts[0] = f"{prefix.strip()} {parts[0]}".strip()
    else:
        parts[-1] = f"{prefix.strip()} {parts[-1]}".strip()

    new_clean_name = '%%'.join(parts)
    new_crate_path = subcrates / f"{new_clean_name}.crate"

    if new_crate_path.exists() and new_crate_path != old_crate_path:
        return {"sucesso": False, "erro": f"Já existe uma crate com o nome de destino: {new_clean_name}"}

    try:
        shutil.move(old_crate_path, new_crate_path)
    except Exception as e:
        return {"sucesso": False, "erro": f"Falha ao renomear crate: {e}"}

    return {
        "sucesso": True,
        "old_name": clean_name,
        "new_name": new_clean_name,
        "caminho": str(new_crate_path),
        "mensagem": f"Crate renomeada de [{clean_name}] para [{new_clean_name}]."
    }


def capitalize_crate(serato_dir: str, crate_name: str) -> Dict[str, Any]:
    """Capitaliza (Title Case) as partes do nome da crate e renomeia o arquivo."""
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    old_crate_path = get_crate_path(subcrates, crate_name)

    if not old_crate_path.exists():
        return {"sucesso": False, "erro": f"Crate não encontrada: {crate_name}"}

    clean_name = old_crate_path.stem
    parts = clean_name.split('%%')
    capitalized_parts = [p.strip().title() for p in parts]
    new_clean_name = '%%'.join(capitalized_parts)
    new_crate_path = subcrates / f"{new_clean_name}.crate"

    if new_clean_name == clean_name:
        return {"sucesso": True, "old_name": clean_name, "new_name": new_clean_name, "mensagem": "Nome já estava capitalizado."}

    if new_crate_path.exists() and new_crate_path != old_crate_path:
        return {"sucesso": False, "erro": f"Já existe uma crate com o nome: {new_clean_name}"}

    try:
        shutil.move(old_crate_path, new_crate_path)
    except Exception as e:
        return {"sucesso": False, "erro": f"Falha ao capitalizar crate: {e}"}

    return {
        "sucesso": True,
        "old_name": clean_name,
        "new_name": new_clean_name,
        "mensagem": f"Crate [{clean_name}] capitalizada para [{new_clean_name}]."
    }


def merge_crates(serato_dir: str, source_crates: List[str], target_crate: str) -> Dict[str, Any]:
    """Funde múltiplas crates de origem em uma crate de destino sem duplicatas."""
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    target_path = get_crate_path(subcrates, target_crate)

    all_tracks = []
    header_antigo = None
    outros_blocos = []

    # Lê faixas já existentes na target (se houver)
    if target_path.exists():
        try:
            data = target_path.read_bytes()
            header_antigo, existentes, _, outros_blocos = parse_crate_binary(data)
            all_tracks.extend(existentes)
        except Exception:
            pass

    # Lê faixas de cada source_crate
    for sc_name in source_crates:
        sc_path = get_crate_path(subcrates, sc_name)
        if not sc_path.exists():
            continue
        try:
            data = sc_path.read_bytes()
            _, tracks, _, _ = parse_crate_binary(data)
            for t in tracks:
                if t not in all_tracks:
                    all_tracks.append(t)
        except Exception:
            pass

    res = write_crate_atomic(target_path, all_tracks, header_antigo, outros_blocos)
    if res["sucesso"]:
        res["mensagem"] = f"{len(source_crates)} crate(s) fundida(s) em [{target_crate}] com sucesso ({len(all_tracks)} faixas)."
    return res


def rewrite_crate_order(serato_dir: str, crate_name: str, ordered_tracks: List[str]) -> Dict[str, Any]:
    """Reescreve a ordem das faixas na crate com a ordem explícita fornecida."""
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    crate_path = get_crate_path(subcrates, crate_name)

    header_antigo = None
    outros_blocos = []
    if crate_path.exists():
        try:
            data = crate_path.read_bytes()
            header_antigo, _, _, outros_blocos = parse_crate_binary(data)
        except Exception:
            pass

    clean_tracks = [normalizar_nfc(t) for t in ordered_tracks if t]
    res = write_crate_atomic(crate_path, clean_tracks, header_antigo, outros_blocos)
    if res["sucesso"]:
        res["mensagem"] = f"Ordem manual da crate [{crate_name}] persistida com sucesso ({len(clean_tracks)} faixas)."
    return res


def main():
    parser = argparse.ArgumentParser(description="Serato Crate Operations & Playlist Tools")
    parser.add_argument("--action", type=str, default="add_paths",
                        choices=["add_paths", "sort", "prefix", "capitalize", "merge", "rewrite_order"],
                        help="Ação a executar na crate")
    parser.add_argument("--serato", required=True, help="Diretório _Serato_")
    parser.add_argument("--crate", required=True, help="Nome da crate")
    parser.add_argument("--paths", nargs="*", default=[], help="Caminhos para add_paths ou rewrite_order")
    parser.add_argument("--sources", nargs="*", default=[], help="Crates de origem para merge")
    parser.add_argument("--prefix", type=str, default="", help="Prefixo a adicionar")
    parser.add_argument("--sort-mode", type=str, default="az", choices=["az", "za", "shuffle", "path"])
    parser.add_argument("--target", type=str, default="subcrate", choices=["subcrate", "master"])

    args = parser.parse_args()

    if args.action == "add_paths":
        res = add_paths_to_crate(args.serato, args.crate, args.paths)
    elif args.action == "sort":
        res = sort_crate_tracks(args.serato, args.crate, args.sort_mode)
    elif args.action == "prefix":
        res = prefix_crate(args.serato, args.crate, args.prefix, args.target)
    elif args.action == "capitalize":
        res = capitalize_crate(args.serato, args.crate)
    elif args.action == "merge":
        res = merge_crates(args.serato, args.sources, args.crate)
    elif args.action == "rewrite_order":
        res = rewrite_crate_order(args.serato, args.crate, args.paths)
    else:
        res = {"sucesso": False, "erro": f"Ação desconhecida: {args.action}"}

    print(json.dumps(res, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
