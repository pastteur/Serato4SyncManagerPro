#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - FERRAMENTAS DE BIBLIOTECA (library_tools.py)
================================================================================
- Verificação de referências quebradas nas crates (faixas que sumiram do disco)
- Exportação de crate para M3U e importação de M3U como nova crate
- Relatório de saúde da biblioteca (BPM, tom, bitrate, cues)
- Crates inteligentes: filtros salvos que regeneram a crate a partir da biblioteca
- Detecção de novas faixas desde a última verificação (sem daemon)

Todas as gravações de crate passam pelo mesmo escritor já usado pelo Track
Matcher. Nenhuma tag é alterada aqui.
================================================================================
"""

import os
import re
import sys

sys.dont_write_bytecode = True
import json
import argparse
from pathlib import Path

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

try:
    import mutagen
    from mutagen.id3 import ID3
except ImportError:
    mutagen = None
    ID3 = None

from music_analysis import CAMELOT_MAJOR, CAMELOT_MINOR, PITCH_NAMES
from serato_macos_app import ler_faixas_crate_binaria
from track_matcher import export_matched_to_serato_crate

AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')
LOW_BITRATE_KBPS = 192
SMART_RULES_PATH = Path.home() / ".serato_sync_smart_crates.json"
WATCH_STATE_PATH = Path.home() / ".serato_sync_watch_state.json"
EXPORTS_DIR = Path.home() / "SeratoSync" / "exports"




def library_root_for(serato_dir):
    """Raiz usada pelo Serato para caminhos relativos (mesma regra de sincronização)."""
    p = Path(os.path.expanduser(str(serato_dir))).resolve()
    if str(p).startswith("/Volumes/"):
        return p.parent
    return Path.home()


def _iter_audio(folder):
    root = Path(os.path.expanduser(str(folder)))
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        for f in filenames:
            if f.startswith('.') or Path(f).suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            yield Path(dirpath) / f


def _crate_files(serato_dir):
    subs = Path(os.path.expanduser(str(serato_dir))) / "Subcrates"
    if not subs.is_dir():
        return []
    return sorted(p for p in subs.iterdir() if p.suffix == ".crate")


def _crate_display_name(crate_path):
    return crate_path.stem.replace('%%', ' > ')


# ------------------------------------------------------------------------------
# Referências quebradas em crates
# ------------------------------------------------------------------------------
def check_crate_references(serato_dir, max_missing_listed=50):
    root = library_root_for(serato_dir)
    crates = []
    total_missing = 0
    for crate in _crate_files(serato_dir):
        _, faixas, _, _ = ler_faixas_crate_binaria(crate)
        faltando = []
        for rel in faixas:
            if not (root / rel).exists():
                faltando.append(rel)
        total_missing += len(faltando)
        crates.append({
            "crate": crate.name,
            "nome": _crate_display_name(crate),
            "total": len(faixas),
            "faltando": len(faltando),
            "exemplos": faltando[:max_missing_listed],
        })
    crates.sort(key=lambda c: (-c["faltando"], c["nome"]))
    return {
        "sucesso": True,
        "raiz": str(root),
        "crates_verificadas": len(crates),
        "referencias_quebradas": total_missing,
        "crates": crates,
    }


# ------------------------------------------------------------------------------
# Exportar / importar M3U
# ------------------------------------------------------------------------------
def export_crate_m3u(serato_dir, crate_name, out_path=None):
    crate = Path(os.path.expanduser(str(serato_dir))) / "Subcrates" / crate_name
    if not crate.exists():
        return {"sucesso": False, "erro": "Crate não encontrada: %s" % crate_name}
    root = library_root_for(serato_dir)
    _, faixas, _, _ = ler_faixas_crate_binaria(crate)
    if out_path is None:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = EXPORTS_DIR / (Path(crate_name).stem + ".m3u")
    out = Path(os.path.expanduser(str(out_path)))
    out.parent.mkdir(parents=True, exist_ok=True)
    linhas = ["#EXTM3U"]
    ausentes = 0
    for rel in faixas:
        abs_p = root / rel
        if not abs_p.exists():
            ausentes += 1
        linhas.append(str(abs_p))
    out.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return {"sucesso": True, "arquivo": str(out), "total": len(faixas), "ausentes": ausentes,
            "mensagem": "Crate exportada para M3U (%d faixas)." % len(faixas)}


def import_m3u_as_crate(serato_dir, m3u_path, crate_name):
    m3u = Path(os.path.expanduser(str(m3u_path)))
    if not m3u.exists():
        return {"sucesso": False, "erro": "Arquivo M3U não encontrado"}
    root = library_root_for(serato_dir)
    itens = []
    ignorados = []
    for linha in m3u.read_text(encoding="utf-8", errors="ignore").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith('#'):
            continue
        abs_p = Path(os.path.expanduser(linha))
        try:
            rel = str(abs_p.resolve().relative_to(root.resolve()))
        except ValueError:
            ignorados.append(linha)
            continue
        if not abs_p.exists():
            ignorados.append(linha)
            continue
        itens.append({"caminho_rel": rel})
    if not itens:
        return {"sucesso": False, "erro": "Nenhuma faixa válida dentro da raiz da biblioteca", "ignoradas": len(ignorados)}
    res = export_matched_to_serato_crate(crate_name, itens, str(serato_dir))
    res["ignoradas"] = len(ignorados)
    res["exemplos_ignoradas"] = ignorados[:20]
    return res


# ------------------------------------------------------------------------------
# Leitura de metadados (para saúde e crates inteligentes)
# ------------------------------------------------------------------------------
def read_track_meta(filepath):
    """Lê BPM, tom (em Camelot), bitrate, duração e presença de cues."""
    meta = {"bpm": None, "camelot": "", "bitrate_kbps": 0, "duracao": 0.0, "tem_cues": False}
    if mutagen is None:
        return meta
    try:
        audio = mutagen.File(str(filepath))
    except Exception:
        return meta
    if audio is None:
        return meta

    info = getattr(audio, "info", None)
    if info is not None:
        meta["bitrate_kbps"] = int(round((getattr(info, "bitrate", 0) or 0) / 1000.0))
        meta["duracao"] = float(getattr(info, "length", 0.0) or 0.0)

    tags = audio.tags
    if tags is not None:
        try:
            if "TBPM" in tags:
                bpm_txt = str(tags["TBPM"]).split(".")[0].strip()
                if bpm_txt.isdigit() and int(bpm_txt) > 0:
                    meta["bpm"] = int(bpm_txt)
        except Exception:
            pass
        try:
            if "TKEY" in tags:
                meta["camelot"] = _normalize_key_to_camelot(str(tags["TKEY"]))
        except Exception:
            pass
        try:
            m2 = tags.get("GEOB:Serato Markers2")
            if m2 is not None and hasattr(m2, "data"):
                from auto_cue import extract_cues_from_raw_tag
                meta["tem_cues"] = bool(extract_cues_from_raw_tag(m2.data))
        except Exception:
            pass
    return meta


def _normalize_key_to_camelot(text):
    t = (text or "").strip()
    if not t:
        return ""
    if re.fullmatch(r"\d{1,2}[AB]", t.upper()):
        return t.upper()
    return _NAME_TO_CAMELOT_CODE.get(t.lower(), "")


_NAME_TO_CAMELOT_CODE = {}
for _t, _c in CAMELOT_MAJOR.items():
    _NAME_TO_CAMELOT_CODE["%s major" % PITCH_NAMES[_t].lower()] = _c
for _t, _c in CAMELOT_MINOR.items():
    _NAME_TO_CAMELOT_CODE["%s minor" % PITCH_NAMES[_t].lower()] = _c


# ------------------------------------------------------------------------------
# Saúde da biblioteca
# ------------------------------------------------------------------------------
def library_health(mp3_folder, serato_dir=None):
    total = sem_bpm = sem_tom = baixa_qualidade = sem_cues = 0
    bytes_total = 0
    for p in _iter_audio(mp3_folder):
        total += 1
        try:
            bytes_total += p.stat().st_size
        except OSError:
            pass
        m = read_track_meta(p)
        if m["bpm"] is None:
            sem_bpm += 1
        if not m["camelot"]:
            sem_tom += 1
        if 0 < m["bitrate_kbps"] < LOW_BITRATE_KBPS:
            baixa_qualidade += 1
        if not m["tem_cues"]:
            sem_cues += 1

    resultado = {
        "sucesso": True,
        "total_faixas": total,
        "tamanho_gb": round(bytes_total / (1024 ** 3), 2),
        "sem_bpm": sem_bpm,
        "sem_tom": sem_tom,
        "baixa_qualidade": baixa_qualidade,
        "limiar_kbps": LOW_BITRATE_KBPS,
        "sem_cues": sem_cues,
    }
    if serato_dir:
        refs = check_crate_references(serato_dir, max_missing_listed=0)
        resultado["crates"] = refs["crates_verificadas"]
        resultado["referencias_quebradas"] = refs["referencias_quebradas"]
    return resultado


# ------------------------------------------------------------------------------
# Crates inteligentes
# ------------------------------------------------------------------------------
def _matches_rules(meta, rules):
    bpm_min = rules.get("bpm_min")
    bpm_max = rules.get("bpm_max")
    if bpm_min or bpm_max:
        if meta["bpm"] is None:
            return False
        if bpm_min and meta["bpm"] < int(bpm_min):
            return False
        if bpm_max and meta["bpm"] > int(bpm_max):
            return False

    camelot = rules.get("camelot") or []
    if camelot:
        if meta["camelot"] not in [c.upper() for c in camelot]:
            return False

    com_cues = rules.get("com_cues")
    if com_cues is True and not meta["tem_cues"]:
        return False
    if com_cues is False and meta["tem_cues"]:
        return False

    bitrate_min = rules.get("bitrate_min")
    if bitrate_min and (meta["bitrate_kbps"] or 0) < int(bitrate_min):
        return False
    return True


def build_smart_items(mp3_folder, rules, serato_dir):
    root = library_root_for(serato_dir)
    items = []
    for p in _iter_audio(mp3_folder):
        meta = read_track_meta(p)
        if _matches_rules(meta, rules):
            try:
                rel = str(p.resolve().relative_to(root.resolve()))
            except ValueError:
                continue
            items.append({"caminho_rel": rel})
    items.sort(key=lambda i: i["caminho_rel"])
    return items


def _load_smart_rules():
    if not SMART_RULES_PATH.exists():
        return []
    try:
        return json.loads(SMART_RULES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_smart_rules(rules):
    SMART_RULES_PATH.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


def create_smart_crate(mp3_folder, serato_dir, nome, rules, salvar_regra=True, dry_run=False):
    if not nome or not nome.strip():
        return {"sucesso": False, "erro": "Informe um nome para a crate inteligente"}
    items = build_smart_items(mp3_folder, rules, serato_dir)
    if dry_run:
        return {"sucesso": True, "dry_run": True, "total": len(items),
                "mensagem": "Prévia: %d faixas correspondem às regras." % len(items)}
    if not items:
        return {"sucesso": False, "erro": "Nenhuma faixa corresponde às regras; crate não criada"}
    res = export_matched_to_serato_crate(nome.strip(), items, str(serato_dir))
    if res.get("sucesso") and salvar_regra:
        existentes = [r for r in _load_smart_rules() if r.get("nome") != nome.strip()]
        existentes.append({"nome": nome.strip(), "regras": rules})
        _save_smart_rules(existentes)
    return res


def refresh_smart_crates(mp3_folder, serato_dir):
    resultados = []
    for regra in _load_smart_rules():
        res = create_smart_crate(mp3_folder, serato_dir, regra["nome"], regra["regras"],
                                 salvar_regra=False, dry_run=False)
        resultados.append({"nome": regra["nome"], "sucesso": bool(res.get("sucesso")),
                           "total": res.get("total_faixas", 0), "erro": res.get("erro")})
    return {"sucesso": True, "atualizadas": sum(1 for r in resultados if r["sucesso"]), "itens": resultados}


def list_smart_crates():
    return {"sucesso": True, "items": _load_smart_rules()}


def delete_smart_crate_rule(nome):
    restantes = [r for r in _load_smart_rules() if r.get("nome") != nome]
    _save_smart_rules(restantes)
    return {"sucesso": True, "mensagem": "Regra removida (a crate gerada no Serato não é apagada)."}


# ------------------------------------------------------------------------------
# Novas faixas desde a última verificação
# ------------------------------------------------------------------------------
def scan_new_files(mp3_folder):
    root = str(Path(os.path.expanduser(str(mp3_folder))).resolve())
    atual = {}
    for p in _iter_audio(root):
        try:
            st = p.stat()
            atual[str(p)] = [st.st_size, int(st.st_mtime)]
        except OSError:
            continue

    estado = {}
    if WATCH_STATE_PATH.exists():
        try:
            estado = json.loads(WATCH_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            estado = {}

    anterior = estado.get(root)
    WATCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    estado[root] = atual
    WATCH_STATE_PATH.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")

    if anterior is None:
        return {"sucesso": True, "linha_base": True, "novos": [], "removidos": 0,
                "mensagem": "Primeira verificação: linha de base registrada (%d arquivos)." % len(atual)}

    novos = sorted(p for p in atual if p not in anterior)
    removidos = sum(1 for p in anterior if p not in atual)
    return {"sucesso": True, "linha_base": False,
            "novos": [{"arquivo": p, "nome": Path(p).name} for p in novos[:500]],
            "total_novos": len(novos), "removidos": removidos}


# ------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Ferramentas de biblioteca")
    parser.add_argument("--serato", type=str, default="", help="Pasta _Serato_")
    parser.add_argument("--mp3", type=str, default="", help="Pasta MP3 da biblioteca")
    parser.add_argument("--check-refs", action="store_true")
    parser.add_argument("--export-m3u", type=str, default="", help="Nome do arquivo .crate a exportar")
    parser.add_argument("--out", type=str, default="", help="Destino do M3U")
    parser.add_argument("--import-m3u", type=str, default="", help="Caminho do M3U a importar")
    parser.add_argument("--crate-name", type=str, default="", help="Nome da crate a criar")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--smart-create", type=str, default="", help="JSON com nome e regras")
    parser.add_argument("--smart-dry-run", action="store_true")
    parser.add_argument("--smart-refresh", action="store_true")
    parser.add_argument("--smart-list", action="store_true")
    parser.add_argument("--smart-delete", type=str, default="")
    parser.add_argument("--scan-new", action="store_true")
    args = parser.parse_args()

    if args.check_refs:
        res = check_crate_references(args.serato)
    elif args.export_m3u:
        res = export_crate_m3u(args.serato, args.export_m3u, args.out or None)
    elif args.import_m3u:
        res = import_m3u_as_crate(args.serato, args.import_m3u, args.crate_name)
    elif args.health:
        res = library_health(args.mp3, args.serato or None)
    elif args.smart_create:
        cfg = json.loads(args.smart_create)
        res = create_smart_crate(args.mp3, args.serato, cfg.get("nome", ""), cfg.get("regras", {}),
                                 dry_run=args.smart_dry_run)
    elif args.smart_refresh:
        res = refresh_smart_crates(args.mp3, args.serato)
    elif args.smart_list:
        res = list_smart_crates()
    elif args.smart_delete:
        res = delete_smart_crate_rule(args.smart_delete)
    elif args.scan_new:
        res = scan_new_files(args.mp3)
    else:
        parser.print_help()
        sys.exit(0)

    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res.get("sucesso", True) else 1)


if __name__ == "__main__":
    main()
