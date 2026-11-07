#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - ANALISADOR DE DUPLICADOS MULTI-PASTA
                  (duplicates_tool.py)
================================================================================
Compara N pastas quaisquer entre si, com opção de incluir a biblioteca Serato,
e devolve grupos de arquivos candidatos a duplicata.

Diferente da auditoria embutida na sincronização (que só olha dentro de uma
pasta), aqui cada arquivo é comparado contra TODOS os outros de TODAS as
pastas selecionadas, inclusive em HDs diferentes.

Estratégia (barata -> cara):
  1. Agrupa por (tamanho exato, nome normalizado)  -> possível duplicata
  2. Confirma por SHA-256 dos bytes, ignorando ID3v2/ID3v1  -> idêntico
  3. Sem hash, compara duração + título/artista (se disponível)  -> provável

Nada é alterado no disco por este módulo, exceto as ações explícitas
(--trash, --move) que só são executadas quando o usuário pede.
================================================================================
"""

import os
import sys

sys.dont_write_bytecode = True
import csv
import json
import shutil
import argparse
import hashlib
from pathlib import Path

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

try:
    import mutagen
except ImportError:
    mutagen = None

AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')
HASHABLE_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')
REPORT_DIR = Path.home() / "SeratoSync" / "logs"
IGNORED_DIR_NAMES = {'.Trashes', '.Spotlight-V100', '.fseventsd', '.DocumentRevisions-V100'}


# ------------------------------------------------------------------------------
# Hash / metadados
# ------------------------------------------------------------------------------
def compute_content_hash(filepath):
    """
    SHA-256 dos bytes do arquivo, ignorando o bloco ID3v2 inicial e o rodapé
    ID3v1 de 128 bytes. Para MP3 isso isola o áudio; para FLAC/M4A os
    metadados ficam fora dessas duas zonas, então cópias com tags diferentes
    nesses formatos NÃO batem (e são tratadas como 'provável', não 'idêntico').
    """
    try:
        with open(filepath, 'rb') as f:
            header = f.read(10)
            start = 0
            if len(header) == 10 and header[:3] == b'ID3':
                size = ((header[6] & 0x7F) << 21) | ((header[7] & 0x7F) << 14) | ((header[8] & 0x7F) << 7) | (header[9] & 0x7F)
                start = 10 + size
                if header[5] & 0x10:
                    start += 10
            f.seek(0, os.SEEK_END)
            end = f.tell()
            if end > 128:
                f.seek(end - 128)
                if f.read(3) == b'TAG':
                    end -= 128
            if end <= start:
                return ""
            f.seek(start)
            hasher = hashlib.sha256()
            remaining = end - start
            while remaining > 0:
                chunk = f.read(min(remaining, 1024 * 1024))
                if not chunk:
                    break
                hasher.update(chunk)
                remaining -= len(chunk)
            return hasher.hexdigest()
    except Exception:
        return ""


def read_meta(filepath):
    """BPM, tom, duração e bitrate, quando disponíveis."""
    meta = {"bpm": "", "key": "", "duration": 0.0, "bitrate_kbps": 0}
    if mutagen is None:
        return meta
    try:
        audio = mutagen.File(str(filepath), easy=False)
    except Exception:
        return meta
    if audio is None:
        return meta
    info = getattr(audio, "info", None)
    if info is not None:
        meta["duration"] = float(getattr(info, "length", 0) or 0)
        meta["bitrate_kbps"] = int(round((getattr(info, "bitrate", 0) or 0) / 1000.0))
    tags = audio.tags
    if tags is not None:
        try:
            if "TBPM" in tags:
                v = str(tags["TBPM"]).split(".")[0].strip()
                if v.isdigit():
                    meta["bpm"] = v
        except Exception:
            pass
        try:
            if "TKEY" in tags:
                meta["key"] = str(tags["TKEY"]).strip()
        except Exception:
            pass
    return meta


def normalize_name(name):
    import unicodedata
    return unicodedata.normalize('NFC', name).lower().strip()


# ------------------------------------------------------------------------------
# Varredura
# ------------------------------------------------------------------------------
def iter_audio(root):
    root_p = Path(os.path.expanduser(str(root)))
    if not root_p.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(str(root_p), followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in IGNORED_DIR_NAMES]
        for f in filenames:
            if f.startswith('.') or f.startswith('._'):
                continue
            p = Path(dirpath) / f
            if p.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            if p.is_symlink() and not p.exists():
                continue
            yield p


def _emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def scan_roots(roots, serato_root=None, include_serato=None, progress=True):
    """
    Varre todas as raízes informadas e devolve grupos de candidatos.
    `include_serato` é uma pasta adicional (a biblioteca do Serato) tratada
    como mais uma raiz, marcada com origem='serato'.
    """
    raizes = []
    for r in roots or []:
        p = Path(os.path.expanduser(str(r))).resolve()
        raizes.append({"path": str(p), "origem": "externa", "exists": p.is_dir()})
    if include_serato:
        p = Path(os.path.expanduser(str(include_serato))).resolve()
        if p.is_dir():
            raizes.append({"path": str(p), "origem": "serato", "exists": True})

    entradas = []
    total_raizes = len(raizes)
    for idx, raiz in enumerate(raizes, 1):
        if not raiz["exists"]:
            continue
        if progress:
            _emit({"tipo": "progresso", "fase": "varredura", "raiz": raiz["path"],
                   "raiz_indice": idx, "total_raizes": total_raizes, "arquivos": len(entradas)})
        for p in iter_audio(raiz["path"]):
            try:
                st = p.stat()
            except OSError:
                continue
            entradas.append({
                "caminho": str(p),
                "nome": p.name,
                "nome_norm": normalize_name(p.name),
                "tamanho": st.st_size,
                "mtime": st.st_mtime,
                "raiz": raiz["path"],
                "origem": raiz["origem"],
                "ext": p.suffix.lower(),
            })

    if progress:
        _emit({"tipo": "progresso", "fase": "comparacao", "total_arquivos": len(entradas)})

    # 1. Agrupa por (nome normalizado, tamanho) e por tamanho exato (captura nomes divergentes)
    por_chave = {}
    por_tam = {}
    for e in entradas:
        por_chave.setdefault((e["nome_norm"], e["tamanho"]), []).append(e)
        if e["tamanho"] > 50 * 1024:
            por_tam.setdefault(e["tamanho"], []).append(e)

    candidatos = {}
    for k, v in por_chave.items():
        if len(v) > 1:
            candidatos[k] = v

    for tam, v in por_tam.items():
        if len(v) > 1:
            caminhos_v = set(item["caminho"] for item in v)
            ja_coberto = any(caminhos_v.issubset(set(ci["caminho"] for ci in g)) for g in candidatos.values())
            if not ja_coberto:
                candidatos[(f"match_tamanho_{tam}", tam)] = v

    # 2. Hash por grupo
    grupos = []
    total_cand = len(candidatos)
    for gi, ((nome, tamanho), itens) in enumerate(candidatos.items(), 1):
        hashes = {}
        for it in itens:
            h = compute_content_hash(it["caminho"]) if it["ext"] in HASHABLE_EXTENSIONS else ""
            it["hash"] = h
            if h:
                hashes.setdefault(h, []).append(it)
        if progress and (gi % 5 == 0 or gi == total_cand):
            _emit({"tipo": "progresso", "fase": "hash", "grupo": gi,
                   "total_grupos": total_cand, "arquivo": nome})

        if len(hashes) == 1 and all(it["hash"] for it in itens):
            grau = "IDENTICO_COMPROVADO"
            motivo = "Bytes idênticos (mesmo SHA-256), ignorando tags ID3."
        elif len(hashes) > 1:
            grau = "POSSIVEL_DUPLICADO"
            motivo = "Mesmo nome e tamanho, mas o conteúdo diverge."
        else:
            grau = "POSSIVEL_DUPLICADO"
            motivo = "Mesmo nome e tamanho; conteúdo não pôde ser confirmado."

        grupos.append({
            "id": "grp-%d" % len(grupos),
            "nome": itens[0]["nome"],
            "tamanho": tamanho,
            "grau_certeza": grau,
            "motivo": motivo,
            "hash_audio": next((it["hash"] for it in itens if it["hash"]), ""),
            "arquivos": [{
                "caminho": it["caminho"],
                "raiz": it["raiz"],
                "origem": it["origem"],
                "tamanho": it["tamanho"],
                "mtime": it["mtime"],
                "hash": it.get("hash", ""),
                **read_meta(it["caminho"]),
            } for it in itens],
        })

    grupos.sort(key=lambda g: (-g["tamanho"], g["nome"].lower()))
    for g in grupos:
        for a in g["arquivos"]:
            a["sugerido_manter"] = False
        manter = _choose_keeper(g["arquivos"])
        if manter:
            manter["sugerido_manter"] = True

    brutos = sum(1 for e in entradas)
    return {
        "sucesso": True,
        "raizes": raizes,
        "total_arquivos": brutos,
        "grupos": len(grupos),
        "copias_redundantes": sum(len(g["arquivos"]) - 1 for g in grupos),
        "bytes_recuperaveis": sum(g["tamanho"] * (len(g["arquivos"]) - 1) for g in grupos),
        "itens": grupos,
    }


def _choose_keeper(arquivos):
    """
    Heurística de manutenção: maior bitrate; empate -> dentro da biblioteca
    Serato; empate -> mais antigo por mtime.
    """
    if not arquivos:
        return None

    def score(a):
        return (
            a.get("bitrate_kbps") or 0,
            1 if a.get("origem") == "serato" else 0,
            -float(a.get("mtime") or 0),
        )
    return max(arquivos, key=score)


# ------------------------------------------------------------------------------
# Ações sobre arquivos
# ------------------------------------------------------------------------------
def move_to_trash(paths):
    resultados = []
    for raw in paths:
        p = Path(os.path.expanduser(str(raw)))
        if not p.exists():
            resultados.append({"arquivo": str(raw), "sucesso": False, "erro": "Arquivo não encontrado"})
            continue
        try:
            texto = p.as_uri()
            from Foundation import NSURL  # type: ignore
            from AppKit import NSWorkspace  # type: ignore
            ok = NSWorkspace.sharedWorkspace().performFileOperation_source_destination_files_tag_(
                "NSWorkspaceRecycleOperation", str(p.parent), "", [p.name], None
            )
            resultados.append({"arquivo": str(p), "sucesso": bool(ok)})
        except Exception:
            # Sem pyobjc: move para a Lixeira do usuário diretamente
            lixeira = Path.home() / ".Trash"
            lixeira.mkdir(exist_ok=True)
            destino = lixeira / p.name
            if destino.exists():
                import time
                destino = lixeira / ("%d_%s" % (int(time.time()), p.name))
            try:
                shutil.move(str(p), str(destino))
                resultados.append({"arquivo": str(p), "sucesso": True, "destino": str(destino)})
            except Exception as e:
                resultados.append({"arquivo": str(p), "sucesso": False, "erro": str(e)})
    return {"sucesso": all(r["sucesso"] for r in resultados), "itens": resultados}


def move_files(paths, destination):
    dest_dir = Path(os.path.expanduser(str(destination)))
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"sucesso": False, "erro": "Destino inválido: %s" % e}

    resultados = []
    for raw in paths:
        src = Path(os.path.expanduser(str(raw)))
        if not src.exists():
            resultados.append({"arquivo": str(raw), "sucesso": False, "erro": "Arquivo não encontrado"})
            continue
        destino = dest_dir / src.name
        if destino.exists():
            destino = dest_dir / ("%s_movido%s" % (src.stem, src.suffix))
            n = 2
            while destino.exists():
                destino = dest_dir / ("%s_movido%d%s" % (src.stem, n, src.suffix))
                n += 1
        try:
            shutil.move(str(src), str(destino))
            resultados.append({"arquivo": str(src), "sucesso": True, "destino": str(destino)})
        except Exception as e:
            resultados.append({"arquivo": str(src), "sucesso": False, "erro": str(e)})
    return {
        "sucesso": all(r["sucesso"] for r in resultados),
        "destino": str(dest_dir),
        "movidos": sum(1 for r in resultados if r["sucesso"]),
        "itens": resultados,
    }


def export_csv(grupos, out_path=None):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if out_path is None:
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = REPORT_DIR / ("duplicados_multipasta_%s.csv" % stamp)
    out = Path(os.path.expanduser(str(out_path)))
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(["grupo", "faixa", "grau", "origem", "caminho", "tamanho_bytes", "bitrate_kbps", "bpm", "tom", "manter_sugerido"])
        for g in grupos:
            for a in g["arquivos"]:
                w.writerow([g["id"], g["nome"], g["grau_certeza"], a["origem"], a["caminho"],
                            a["tamanho"], a.get("bitrate_kbps", ""), a.get("bpm", ""), a.get("key", ""),
                            "sim" if a.get("sugerido_manter") else "nao"])
    return {"sucesso": True, "arquivo": str(out), "linhas": sum(len(g["arquivos"]) for g in grupos)}


# ------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Duplicados multi-pasta")
    parser.add_argument("--roots", nargs="*", default=[], help="Pastas a comparar entre si")
    parser.add_argument("--include-serato", type=str, default="", help="Inclui esta pasta na comparação")
    parser.add_argument("--serato-path", type=str, default="", help="Caminho _Serato_ para gravar crates")
    parser.add_argument("--trash", nargs="*", default=None, help="Move os caminhos para a Lixeira")
    parser.add_argument("--move", nargs="*", default=None, help="Move os caminhos para --destination")
    parser.add_argument("--destination", type=str, default="", help="Pasta de destino do movimento")
    parser.add_argument("--export-csv", action="store_true", help="Exporta o resultado da varredura em CSV")
    parser.add_argument("--no-progress", action="store_true", help="Não emite progresso (uso em testes)")
    args = parser.parse_args()

    if args.trash is not None:
        _emit(move_to_trash(args.trash))
        return
    if args.move is not None:
        if not args.destination:
            _emit({"sucesso": False, "erro": "Informe --destination para mover"})
            sys.exit(1)
        _emit(move_files(args.move, args.destination))
        return

    res = scan_roots(args.roots, include_serato=args.include_serato or None,
                     progress=not args.no_progress)
    if args.export_csv:
        res["export_csv"] = export_csv(res["itens"])
    _emit(res)


if __name__ == "__main__":
    main()
