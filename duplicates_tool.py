#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 5 SYNC MANAGER PRO - ANALISADOR DE DUPLICADOS MULTI-PASTA
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
import re
import csv
import json
import uuid
import shutil
import argparse
import hashlib
import unicodedata
from datetime import datetime
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

try:
    import journal
except ImportError:
    journal = None

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


def calc_sha256(filepath) -> str:
    """Calcula o hash SHA-256 integral do arquivo em disco."""
    try:
        hasher = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


def clean_audio_name(filename):
    """
    Normaliza o nome do arquivo para matching semântico/musical:
    - Remove números de faixa no início (ex: '01 - ', '01. ', '1-01 ')
    - Remove sufixos de cópia (ex: '(1)', '[2]', ' - Cópia', ' - copy')
    - Remove pontuação, normaliza diacríticos (NFC) e caixa baixa.
    """
    stem = Path(filename).stem
    s = unicodedata.normalize('NFC', stem).lower().strip()
    s = re.sub(r'^\d+[\s\.\-_]+', '', s)
    s = re.sub(r'[\(\[\{]\s*\d+\s*[\)\]\}]', ' ', s)
    s = re.sub(r'[\-_]?\s*\b(cópia|copia|copy)\b\s*(\d+)?', ' ', s, flags=re.IGNORECASE)
    s = re.sub(r'[^\w\s]', ' ', s)
    return ' '.join(s.split())


def read_meta(filepath):
    """BPM, tom, duração, bitrate, artista, título, marcadores Serato e Sound Seal."""
    meta = {
        "bpm": "",
        "key": "",
        "duration": 0.0,
        "bitrate_kbps": 0,
        "artist": "",
        "title": "",
        "has_serato_markers": False,
        "sound_seal": ""
    }
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
        meta["duration"] = round(float(getattr(info, "length", 0) or 0), 2)
        meta["bitrate_kbps"] = int(round((getattr(info, "bitrate", 0) or 0) / 1000.0))
    tags = getattr(audio, "tags", None)
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
        try:
            if "TPE1" in tags:
                meta["artist"] = str(tags["TPE1"]).strip()
            elif "artist" in tags:
                meta["artist"] = str(tags["artist"][0]).strip()
        except Exception:
            pass
        try:
            if "TIT2" in tags:
                meta["title"] = str(tags["TIT2"]).strip()
            elif "title" in tags:
                meta["title"] = str(tags["title"][0]).strip()
        except Exception:
            pass
        try:
            for k in tags.keys():
                if "GEOB:Serato" in k or str(k).startswith("GEOB:Serato"):
                    meta["has_serato_markers"] = True
                    break
        except Exception:
            pass
        try:
            for k, val in tags.items():
                k_str = str(k)
                if "COMM" in k_str and "SOUND_SEAL" in str(val):
                    meta["sound_seal"] = str(val)
                elif "TXXX:SOUND_SEAL" in k_str:
                    meta["sound_seal"] = str(val)
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
                "clean_name": clean_audio_name(p.name),
                "tamanho": st.st_size,
                "mtime": st.st_mtime,
                "raiz": raiz["path"],
                "origem": raiz["origem"],
                "ext": p.suffix.lower(),
            })

    if progress:
        _emit({"tipo": "progresso", "fase": "comparacao", "total_arquivos": len(entradas)})

    # 1. Pré-seleção inteligente para cálculo de hash acústico (Sound Seal SHA-256)
    # Arquivos só necessitam de hash se tiverem mesmo tamanho (>50KB) ou mesmo nome limpo
    tam_grupos = {}
    clean_grupos = {}
    for e in entradas:
        if e["tamanho"] > 50 * 1024:
            tam_grupos.setdefault(e["tamanho"], []).append(e)
        if len(e["clean_name"]) >= 3:
            clean_grupos.setdefault(e["clean_name"], []).append(e)

    precisa_hash = set()
    for itens in tam_grupos.values():
        if len(itens) > 1:
            for it in itens:
                precisa_hash.add(it["caminho"])
    for itens in clean_grupos.values():
        if len(itens) > 1:
            for it in itens:
                precisa_hash.add(it["caminho"])

    total_hash = len(precisa_hash)
    hash_cache = {}
    for idx, fpath in enumerate(precisa_hash, 1):
        if progress and (idx % 25 == 0 or idx == total_hash):
            _emit({"tipo": "progresso", "fase": "hash", "grupo": idx,
                   "total_grupos": total_hash, "arquivo": Path(fpath).name})
        h = compute_content_hash(fpath)
        if h:
            hash_cache[fpath] = h

    for e in entradas:
        e["hash"] = hash_cache.get(e["caminho"], "")

    grupos = []
    processados = set()

    # FASE 1: IDENTICO_COMPROVADO (Mesmo Hash SHA-256 do fluxo de áudio)
    por_hash = {}
    for e in entradas:
        if e["hash"]:
            por_hash.setdefault(e["hash"], []).append(e)

    for h, itens in por_hash.items():
        if len(itens) > 1:
            for it in itens:
                processados.add(it["caminho"])

            arquivos_meta = []
            for it in itens:
                meta = read_meta(it["caminho"])
                arquivos_meta.append({
                    "caminho": it["caminho"],
                    "nome": it["nome"],
                    "raiz": it["raiz"],
                    "origem": it["origem"],
                    "tamanho": it["tamanho"],
                    "mtime": it["mtime"],
                    "hash": it["hash"],
                    **meta,
                })

            for a in arquivos_meta:
                a["sugerido_manter"] = False
            manter = _choose_keeper(arquivos_meta)
            if manter:
                manter["sugerido_manter"] = True

            grupos.append({
                "id": "grp-%d" % (len(grupos) + 1),
                "nome": manter["nome"] if manter else itens[0]["nome"],
                "tamanho": manter["tamanho"] if manter else itens[0]["tamanho"],
                "grau_certeza": "IDENTICO_COMPROVADO",
                "motivo": "Conteúdo de áudio 100% idêntico (mesmo hash SHA-256 do fluxo de som, independente de tags ID3).",
                "hash_audio": h,
                "arquivos": arquivos_meta,
            })

    # FASE 2: POSSIVEL_DUPLICADO (Mesmo Clean Name e duração compatível)
    # NOTA CRÍTICA: Arquivos com nomes divergentes NUNCA são agrupados aqui,
    # mesmo que coincidam no tamanho em bytes.
    por_clean = {}
    for e in entradas:
        if e["caminho"] not in processados and len(e["clean_name"]) >= 3:
            por_clean.setdefault(e["clean_name"], []).append(e)

    for cname, itens in por_clean.items():
        if len(itens) > 1:
            meta_itens = []
            for it in itens:
                meta = read_meta(it["caminho"])
                meta_itens.append({
                    "caminho": it["caminho"],
                    "nome": it["nome"],
                    "raiz": it["raiz"],
                    "origem": it["origem"],
                    "tamanho": it["tamanho"],
                    "mtime": it["mtime"],
                    "hash": it.get("hash", ""),
                    **meta,
                })

            # Sub-agrupamento por duração (delta <= 3.5 segundos)
            clusters = []
            for m in meta_itens:
                dur = m.get("duration", 0.0)
                matched_cl = None
                for cl in clusters:
                    ref_dur = cl[0].get("duration", 0.0)
                    if dur == 0.0 or ref_dur == 0.0 or abs(dur - ref_dur) <= 3.5:
                        matched_cl = cl
                        break
                if matched_cl is not None:
                    matched_cl.append(m)
                else:
                    clusters.append([m])

            for cl in clusters:
                if len(cl) > 1:
                    for it in cl:
                        processados.add(it["caminho"])

                    for a in cl:
                        a["sugerido_manter"] = False
                    manter = _choose_keeper(cl)
                    if manter:
                        manter["sugerido_manter"] = True

                    durs = [int(it.get("duration", 0)) for it in cl if it.get("duration", 0) > 0]
                    bitrates = [it.get("bitrate_kbps", 0) for it in cl if it.get("bitrate_kbps", 0) > 0]
                    dur_str = f"Duração: {' / '.join(f'{d}s' for d in durs)}" if durs else ""
                    bitrate_str = f"Bitrates: {' vs '.join(f'{b} kbps' for b in bitrates)}" if bitrates else ""
                    detalhes = [s for s in (dur_str, bitrate_str) if s]
                    motivo = f"Mesmo título normalizado ('{cname}') com master/bitrate divergente ({'; '.join(detalhes)})."

                    grupos.append({
                        "id": "grp-%d" % (len(grupos) + 1),
                        "nome": manter["nome"] if manter else cl[0]["nome"],
                        "tamanho": manter["tamanho"] if manter else cl[0]["tamanho"],
                        "grau_certeza": "POSSIVEL_DUPLICADO",
                        "motivo": motivo,
                        "hash_audio": cl[0].get("hash", ""),
                        "arquivos": cl,
                    })

    # FASE 3: POSSIVEL_DUPLICADO por Tags ID3 (Artista + Título idênticos)
    por_art_tit = {}
    for e in entradas:
        if e["caminho"] not in processados:
            meta = read_meta(e["caminho"])
            art = meta.get("artist", "").strip().lower()
            tit = meta.get("title", "").strip().lower()
            if len(art) >= 2 and len(tit) >= 2:
                art_n = ' '.join(re.sub(r'[^\w\s]', '', art).split())
                tit_n = ' '.join(re.sub(r'[^\w\s]', '', tit).split())
                if art_n and tit_n:
                    por_art_tit.setdefault((art_n, tit_n), []).append((e, meta))

    for (art_n, tit_n), pairs in por_art_tit.items():
        if len(pairs) > 1:
            cl_meta = []
            for e, meta in pairs:
                cl_meta.append({
                    "caminho": e["caminho"],
                    "nome": e["nome"],
                    "raiz": e["raiz"],
                    "origem": e["origem"],
                    "tamanho": e["tamanho"],
                    "mtime": e["mtime"],
                    "hash": e.get("hash", ""),
                    **meta,
                })
            durs = [m.get("duration", 0.0) for m in cl_meta if m.get("duration", 0.0) > 0]
            if len(durs) >= 2 and max(durs) - min(durs) > 4.0:
                continue

            for it in cl_meta:
                processados.add(it["caminho"])

            for a in cl_meta:
                a["sugerido_manter"] = False
            manter = _choose_keeper(cl_meta)
            if manter:
                manter["sugerido_manter"] = True

            art_tit_str = f"{cl_meta[0].get('artist')} - {cl_meta[0].get('title')}"
            grupos.append({
                "id": "grp-%d" % (len(grupos) + 1),
                "nome": manter["nome"] if manter else cl_meta[0]["nome"],
                "tamanho": manter["tamanho"] if manter else cl_meta[0]["tamanho"],
                "grau_certeza": "POSSIVEL_DUPLICADO",
                "motivo": f"Mesmo Artista e Título em tags ID3 ('{art_tit_str}').",
                "hash_audio": cl_meta[0].get("hash", ""),
                "arquivos": cl_meta,
            })

    grupos.sort(key=lambda g: (0 if g["grau_certeza"] == "IDENTICO_COMPROVADO" else 1, -g["tamanho"], g["nome"].lower()))

    brutos = sum(1 for e in entradas)
    bytes_recup = sum(
        sum(a["tamanho"] for a in g["arquivos"] if not a.get("sugerido_manter"))
        for g in grupos
    )
    return {
        "sucesso": True,
        "raizes": raizes,
        "total_arquivos": brutos,
        "grupos": len(grupos),
        "copias_redundantes": sum(len(g["arquivos"]) - 1 for g in grupos),
        "bytes_recuperaveis": bytes_recup,
        "itens": grupos,
    }


def _choose_keeper(arquivos):
    """
    Heurística inteligente de preservação (Keeper Selection):
    1. Presença de Hot Cues / Serato Markers (+500 pts)
    2. Presença de Sound Seal acústico confirmado (+300 pts)
    3. Maior bitrate de áudio (+bitrate pts, ex: 320 kbps > 128 kbps)
    4. Pertence à biblioteca Serato Master (+150 pts)
    5. Metadados ricos e confirmados (BPM, Tom, Artista) (+25 pts cada)
    6. Nome limpo sem marcadores de cópia '(1)', ' - Cópia' (+50 pts)
    7. Arquivo mais antigo / data de modificação (+10 pts)
    """
    if not arquivos:
        return None

    def score(a):
        s = 0
        if a.get("has_serato_markers"):
            s += 500
        if a.get("sound_seal"):
            s += 300
        s += int(a.get("bitrate_kbps") or 0)
        if a.get("origem") == "serato":
            s += 150
        if a.get("bpm"):
            s += 25
        if a.get("key"):
            s += 25
        if a.get("artist"):
            s += 25
        nome = a.get("nome", "").lower()
        if not re.search(r'[\(\[\{]\s*\d+\s*[\)\]\}]|\b(cópia|copia|copy)\b', nome):
            s += 50
        mtime = float(a.get("mtime") or 0)
        return (s, -mtime)

    return max(arquivos, key=score)


# ------------------------------------------------------------------------------
# Ações sobre arquivos
# ------------------------------------------------------------------------------
def move_to_trash(paths):
    operacao_id = str(uuid.uuid4())
    manifesto_itens = []
    resultados = []
    timestamp = datetime.now().isoformat()

    for raw in paths:
        p = Path(os.path.expanduser(str(raw))).resolve()
        if not p.exists():
            resultados.append({"arquivo": str(raw), "sucesso": False, "erro": "Arquivo não encontrado"})
            continue

        file_hash = calc_sha256(p)
        file_size = p.stat().st_size if p.exists() else 0
        dest_record = None

        try:
            # Sem pyobjc ou em fallback: move para a Lixeira do usuário diretamente
            lixeira = Path.home() / ".Trash"
            lixeira.mkdir(exist_ok=True)
            destino = lixeira / p.name
            if destino.exists():
                import time
                destino = lixeira / ("%d_%s" % (int(time.time()), p.name))
            shutil.move(str(p), str(destino))
            dest_record = str(destino)
            resultados.append({"arquivo": str(p), "sucesso": True, "destino": str(destino)})
        except Exception as e:
            resultados.append({"arquivo": str(p), "sucesso": False, "erro": str(e)})

        if dest_record:
            manifesto_entry = {
                "operacao_id": operacao_id,
                "timestamp": timestamp,
                "acao": "TRASH",
                "arquivo_origem": str(p),
                "arquivo_destino": dest_record,
                "sha256": file_hash,
                "tamanho_bytes": file_size
            }
            manifesto_itens.append(manifesto_entry)
            if journal:
                try:
                    with journal.get_journal_db() as conn:
                        conn.execute("""
                            INSERT INTO operacoes (criado_em, acao, arquivo, desfeita, hash_anterior, hash_posterior)
                            VALUES (?, 'DUPLICATE_TRASH', ?, 0, ?, ?);
                        """, (timestamp, str(p), file_hash, dest_record))
                        conn.commit()
                except Exception:
                    pass

    manifest_path = None
    if manifesto_itens:
        try:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            manifest_path = REPORT_DIR / f"trash_manifest_{operacao_id}.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump({"operacao_id": operacao_id, "timestamp": timestamp, "itens": manifesto_itens}, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    return {
        "sucesso": all(r["sucesso"] for r in resultados),
        "operacao_id": operacao_id,
        "manifesto": str(manifest_path) if manifest_path else "",
        "itens": resultados
    }


def move_files(paths, destination):
    dest_dir = Path(os.path.expanduser(str(destination))).resolve()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"sucesso": False, "erro": "Destino inválido: %s" % e}

    operacao_id = str(uuid.uuid4())
    manifesto_itens = []
    resultados = []
    timestamp = datetime.now().isoformat()

    for raw in paths:
        src = Path(os.path.expanduser(str(raw))).resolve()
        if not src.exists():
            resultados.append({"arquivo": str(raw), "sucesso": False, "erro": "Arquivo não encontrado"})
            continue

        file_hash = calc_sha256(src)
        file_size = src.stat().st_size if src.exists() else 0

        destino = dest_dir / src.name
        if destino.exists():
            destino = dest_dir / ("%s_movido%s" % (src.stem, src.suffix))
            n = 2
            while destino.exists():
                destino = dest_dir / ("%s_movido%d%s" % (src.stem, n, src.suffix))
                n += 1
        try:
            shutil.move(str(src), str(destino))
            dest_record = str(destino)
            resultados.append({"arquivo": str(src), "sucesso": True, "destino": str(destino)})

            manifesto_entry = {
                "operacao_id": operacao_id,
                "timestamp": timestamp,
                "acao": "MOVE",
                "arquivo_origem": str(src),
                "arquivo_destino": dest_record,
                "sha256": file_hash,
                "tamanho_bytes": file_size
            }
            manifesto_itens.append(manifesto_entry)
            if journal:
                try:
                    with journal.get_journal_db() as conn:
                        conn.execute("""
                            INSERT INTO operacoes (criado_em, acao, arquivo, desfeita, hash_anterior, hash_posterior)
                            VALUES (?, 'DUPLICATE_MOVE', ?, 0, ?, ?);
                        """, (timestamp, str(src), file_hash, dest_record))
                        conn.commit()
                except Exception:
                    pass
        except Exception as e:
            resultados.append({"arquivo": str(src), "sucesso": False, "erro": str(e)})

    manifest_path = dest_dir / "quarantine_manifest.json"
    try:
        existing_manifest = []
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    existing_manifest = json.load(f)
                    if not isinstance(existing_manifest, list):
                        existing_manifest = []
            except Exception:
                existing_manifest = []
        existing_manifest.extend(manifesto_itens)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(existing_manifest, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return {
        "sucesso": all(r["sucesso"] for r in resultados),
        "operacao_id": operacao_id,
        "destino": str(dest_dir),
        "manifesto": str(manifest_path),
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
    parser = argparse.ArgumentParser(description="Serato 5 Sync Manager Pro - Duplicados multi-pasta")
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
