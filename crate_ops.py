#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grava/atualiza uma crate do Serato a partir de uma lista de caminhos ABSOLUTOS,
preservando cabeçalho vrsn, blocos não-otrk e a ordem existente.

Adicionar uma faixa a uma crate que já existe é o caso principal aqui (o
integrate do Track Matcher só copia arquivos para pastas). Caminhos fora da
raiz da biblioteca são rejeitados: gerariam referência quebrada no Serato.
"""

import os
import sys
import json
import struct
import argparse
from pathlib import Path

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
    return Path.home()


def add_paths_to_crate(serato_dir, crate_name, abs_paths):
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    subcrates.mkdir(parents=True, exist_ok=True)

    safe = crate_name.replace('/', '%%').replace('\\', '%%')
    if not safe.endswith('.crate'):
        safe += '.crate'
    crate_path = subcrates / safe

    root = library_root_for(serato)

    relativos = []
    rejeitados = []
    for raw in abs_paths:
        p = Path(os.path.expanduser(str(raw)))
        try:
            rel = str(p.resolve().relative_to(root.resolve()))
        except ValueError:
            rejeitados.append({"arquivo": str(raw), "motivo": "fora da raiz da biblioteca (%s)" % root})
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
        data = crate_path.read_bytes()
        header_antigo, existentes, blocos_otrk, outros_blocos = parse_crate_binary(data)

    final = list(existentes)
    adicionados = 0
    for rel in relativos:
        if rel not in final:
            final.append(rel)
            adicionados += 1

    tmp = crate_path.with_suffix('.tmp')
    bak = crate_path.with_suffix('.bak')
    try:
        with open(tmp, 'wb') as f:
            f.write(header_antigo if header_antigo and len(header_antigo) >= 8
                    else b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000')
            for b in outros_blocos:
                f.write(b)
            for rel in final:
                ptrk = criar_tag_tlv('ptrk', rel)
                f.write(b'otrk' + struct.pack('>I', len(ptrk)) + ptrk)
            f.flush()
            os.fsync(f.fileno())
        if crate_path.exists():
            import shutil as _sh
            _sh.copy2(crate_path, bak)
        os.replace(tmp, crate_path)
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        return {"sucesso": False, "erro": str(e)}

    return {
        "sucesso": True,
        "crate": crate_path.name,
        "caminho": str(crate_path),
        "adicionados": adicionados,
        "total": len(final),
        "raiz": str(root),
        "rejeitados": rejeitados,
        "mensagem": "%d faixa(s) adicionada(s) à crate [%s] (%d no total)." % (adicionados, crate_path.stem, len(final)),
    }


def main():
    parser = argparse.ArgumentParser(description="Adiciona caminhos absolutos a uma crate do Serato")
    parser.add_argument("--serato", required=True)
    parser.add_argument("--crate", required=True)
    parser.add_argument("--paths", nargs="*", default=[])
    args = parser.parse_args()
    print(json.dumps(add_paths_to_crate(args.serato, args.crate, args.paths), ensure_ascii=False))


if __name__ == "__main__":
    main()
