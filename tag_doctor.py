#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - TAG DOCTOR & BACKUP ENGINE (tag_doctor.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Motor de alta fidelidade para análise, higienização de nomes e regravação de tags ID3,
preservando 100% dos marcadores Serato (GEOB Markers, Beatgrids, BPM e Key).
================================================================================
"""

import sys
import os
import re
import shutil
import datetime
import json
import sqlite3
import argparse
import unicodedata
from pathlib import Path

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

try:
    import mutagen
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TBPM, TKEY
except ImportError:
    mutagen = None

DEFAULT_BACKUPS_DIR = Path.home() / "pasync" / "backups"
SERATO_INTERNAL_DB = Path.home() / "Library" / "Application Support" / "Serato" / "Library" / "master.sqlite"
AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')

# Padrões rápidos e seguros de remoção de domínios, sites e sujeiras de download da web (sem catastrophic backtracking)
NOISE_PATTERNS = [
    re.compile(r'\b(?:https?://)?(?:www\.)?[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)*\.(?:com|re|net|org|top|ru|io|co|me|vip|cc|club|site|online|link|info|mp3s?)\b(?:/[^\s\)]*)?', re.IGNORECASE),
    re.compile(r'\b(?:myfreemp3|123savemp3|spotidown|mp3clan|convert2mp3|y2mate|savefrom|360ytmp3)\.[a-z]{2,5}\b', re.IGNORECASE),
    re.compile(r'\bmy-free-mp3s?\.com\b', re.IGNORECASE),
    re.compile(r'\bwww\.[a-zA-Z0-9\-]+\.[a-z]{2,5}\b', re.IGNORECASE),
    re.compile(r'\b\d{2,3}\s*kbps\b', re.IGNORECASE),
    re.compile(r'\[dj\s*pool\]', re.IGNORECASE),
    re.compile(r'\(dj\s*pool\)', re.IGNORECASE),
    re.compile(r'\[exclusive\]', re.IGNORECASE),
    re.compile(r'\[megapack\]', re.IGNORECASE),
    re.compile(r'\[\d{3}\s*kbps\]', re.IGNORECASE),
    re.compile(r'\(\d{3}\s*kbps\)', re.IGNORECASE),
    re.compile(r'\(official\s*(?:audio|video|music\s*video|lyric\s*video)?\)', re.IGNORECASE),
    re.compile(r'\[official\s*(?:audio|video|music\s*video|lyric\s*video)?\]', re.IGNORECASE),
    re.compile(r'_\-_'),
    re.compile(r'-\s*-'),
]

# Padrão de BPM/Key no final do nome: ex: " . 80 . Fm", " . 128 . Am", " . 96 . C#"
TRAILING_BPM_KEY = re.compile(r'\s*\.\s*\d{2,3}(?:\.\d+)?\s*\.\s*[A-G][b#]?(?:m|maj|min)?\s*$', re.IGNORECASE)
TRAILING_DOTS = re.compile(r'[\s\._]+$')
TRAILING_PUNCT = re.compile(r'(?<=\s)[\._]+$|\.{2,}$|[\s_]+$')
LEADING_TRACK_NUM = re.compile(r'^\d{1,3}\s*[-–.]\s*')

TAG_CACHE_DB = Path.home() / ".serato_tag_cache.sqlite"
_SEEDED_TITLES = set()


def init_tag_cache():
    """Inicializa banco SQLite de cache de correspondência de metadados."""
    try:
        conn = sqlite3.connect(str(TAG_CACHE_DB))
        conn.execute('''
            CREATE TABLE IF NOT EXISTS metadata_cache (
                title_norm TEXT PRIMARY KEY,
                artist TEXT,
                title TEXT,
                score INT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        conn.commit()
        conn.close()
    except Exception:
        pass


def normalize_title_for_lookup(t: str) -> str:
    """Normaliza título removendo parênteses e pontuação para busca fonética."""
    t = unicodedata.normalize('NFC', t or '')
    t = re.sub(r'[\(\[\{].*?[\)\]\}]', '', t)
    t = re.sub(r'[^\w\s]', '', t)
    return re.sub(r'\s+', ' ', t).strip().lower()


def get_cached_artist(title: str) -> str:
    """Busca artista em cache local instantâneo (SQLite)."""
    norm = normalize_title_for_lookup(title)
    if not norm:
        return ""
    try:
        conn = sqlite3.connect(str(TAG_CACHE_DB))
        cur = conn.cursor()
        cur.execute("SELECT artist FROM metadata_cache WHERE title_norm = ?;", (norm,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return ""


def seed_tag_cache(title: str, artist: str):
    """Alimenta o cache com títulos e artistas conhecidos da biblioteca."""
    norm = normalize_title_for_lookup(title)
    if not norm or not artist or norm in _SEEDED_TITLES:
        return
    _SEEDED_TITLES.add(norm)
    try:
        conn = sqlite3.connect(str(TAG_CACHE_DB))
        conn.execute("INSERT OR IGNORE INTO metadata_cache (title_norm, artist, title, score) VALUES (?, ?, ?, 100);",
                     (norm, artist.strip(), title.strip()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def lookup_musicbrainz_artist(title: str, crate: str = "") -> str:
    """Consulta MusicBrainz na nuvem com fallback no cache local."""
    norm = normalize_title_for_lookup(title)
    if not norm:
        return ""

    cached = get_cached_artist(title)
    if cached:
        return cached

    # Consulta endpoint público do MusicBrainz
    try:
        import urllib.request
        import urllib.parse
        q = f'recording:"{title}"'
        url = f'https://musicbrainz.org/ws/2/recording/?query={urllib.parse.quote(q)}&fmt=json&limit=3'
        req = urllib.request.Request(url, headers={'User-Agent': 'Serato4SyncPro/1.0 (contact@serato4sync.pro)'})
        with urllib.request.urlopen(req, timeout=3.5) as res:
            data = json.loads(res.read().decode())
            recs = data.get('recordings', [])
            if recs:
                best = recs[0]
                art = best.get('artist-credit', [{}])[0].get('name', '')
                score = int(best.get('score', 0))
                if art and score >= 75:
                    conn = sqlite3.connect(str(TAG_CACHE_DB))
                    conn.execute("INSERT OR REPLACE INTO metadata_cache (title_norm, artist, title, score) VALUES (?, ?, ?, ?);",
                                 (norm, art.strip(), best.get('title', title), score))
                    conn.commit()
                    conn.close()
                    return art.strip()
    except Exception:
        pass
    return ""


def enrich_missing_artists(items: list):
    """Identifica artistas para itens sem artista usando MusicBrainz e Cache."""
    init_tag_cache()
    enriched_count = 0
    updated_items = []

    for item in items:
        art = (item.get("artista_sugerido") or "").strip()
        tit = (item.get("titulo_sugerido") or item.get("titulo_atual") or "").strip()
        crate = item.get("crate_raiz") or ""

        if not art and tit:
            found_art = lookup_musicbrainz_artist(tit, crate)
            if found_art:
                item["artista_sugerido"] = found_art
                ext = Path(item["caminho"]).suffix if item.get("caminho") else ".mp3"
                clean_res = clean_track_name(
                    Path(item.get("caminho", "")).stem or tit,
                    rel_folder=item.get("crate_completa") or item.get("crate_raiz", ""),
                    existing_artist=found_art,
                    existing_title=tit
                )
                item["arquivo_sugerido"] = f"{clean_res['fmt_completo']}{ext}"
                item["nome_dj"] = f"{clean_res['fmt_dj']}{ext}"
                item["nome_crate"] = f"{clean_res['fmt_crate']}{ext}"
                item["nome_completo"] = f"{clean_res['fmt_completo']}{ext}"
                item["precisa_limpeza"] = True
                enriched_count += 1

        updated_items.append(item)

    return {
        "sucesso": True,
        "total_enriquecidos": enriched_count,
        "items": updated_items
    }



def backup_master_database():
    """Realiza snapshot seguro de master.sqlite com carimbo de data/hora."""
    if not SERATO_INTERNAL_DB.exists():
        return {
            "sucesso": False,
            "erro": f"Banco central do Serato não encontrado em: {SERATO_INTERNAL_DB}"
        }

    DEFAULT_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = DEFAULT_BACKUPS_DIR / f"master_backup_{ts}.sqlite"

    try:
        shutil.copy2(SERATO_INTERNAL_DB, backup_file)
        size_mb = backup_file.stat().st_size / (1024 * 1024)
        return {
            "sucesso": True,
            "arquivo": str(backup_file),
            "tamanho_mb": round(size_mb, 2),
            "timestamp": ts,
            "mensagem": f"Backup do master.sqlite gerado com sucesso ({round(size_mb, 2)} MB)"
        }
    except Exception as e:
        return {
            "sucesso": False,
            "erro": f"Falha ao gerar backup: {e}"
        }


def list_master_backups():
    """Lista todos os backups existentes do master.sqlite."""
    if not DEFAULT_BACKUPS_DIR.exists():
        return []

    backups = []
    for f in sorted(DEFAULT_BACKUPS_DIR.glob("master_backup_*.sqlite"), reverse=True):
        size_mb = f.stat().st_size / (1024 * 1024)
        mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
        backups.append({
            "nome": f.name,
            "caminho": str(f),
            "tamanho_mb": round(size_mb, 2),
            "data": mtime
        })
    return backups


def restore_master_database(backup_path_str: str):
    """Restaura com segurança uma versão anterior de master.sqlite."""
    backup_file = Path(backup_path_str)
    if not backup_file.exists():
        return {"sucesso": False, "erro": "Arquivo de backup não encontrado."}

    try:
        # Gera salvaguarda do atual antes de substituir
        if SERATO_INTERNAL_DB.exists():
            salvaguarda = DEFAULT_BACKUPS_DIR / f"master_pre_restore_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite"
            shutil.copy2(SERATO_INTERNAL_DB, salvaguarda)

        shutil.copy2(backup_file, SERATO_INTERNAL_DB)
        return {"sucesso": True, "mensagem": f"Banco restaurado com sucesso a partir de {backup_file.name}"}
    except Exception as e:
        return {"sucesso": False, "erro": f"Erro ao restaurar: {e}"}


def clean_track_name(filename_no_ext: str, rel_folder: str = "", existing_artist: str = "", existing_title: str = "", existing_album: str = ""):
    """
    Higieniza nomes de faixas e títulos preservando 100% de versões/remixes/feats,
    e detecta Crate Raiz (ex: Axé, Funk, Sertanejo, Pop Rock) e Álbum.
    Remove propagandas de sites da web (myfreemp3, pool, etc.), aspas soltas,
    deduplica repetições infinitas de crates/álbuns no nome, deduplica artistas
    no título e garante consistência e idempotência total (f(f(x)) == f(x)).
    """
    # 0. Normalização Unicode NFC
    text = unicodedata.normalize('NFC', filename_no_ext)

    # 1. Identificação da Crate Raiz e Hierarquia (com normalização NFC e sem underscore)
    folder_parts = [p for p in rel_folder.replace(' -> ', '/').replace('\\', '/').split('/') if p]
    crate_raiz_raw = folder_parts[0] if folder_parts else ""
    crate_raiz = unicodedata.normalize('NFC', crate_raiz_raw.replace('_', ' ').strip())
    crate_completa = " -> ".join(folder_parts) if folder_parts else ""

    # Normaliza underscores e hífens duplos antes da remoção de URLs
    text = text.replace('_', ' ')
    text = re.sub(r'\s*-\s*-\s*', ' - ', text)

    # 2. Remove URLs e sujeiras de download da web
    for pattern in NOISE_PATTERNS:
        text = pattern.sub('', text)

    # 3. Extrai e remove cauda/marcadores de BPM e Key (ex: " . 80 . Fm", " . 130 . Dm", " . 128")
    detected_bpm = ""
    detected_key = ""
    bpm_key_match = TRAILING_BPM_KEY.search(text)
    if bpm_key_match:
        part = bpm_key_match.group(0).strip(" .")
        subparts = [p.strip() for p in part.split('.') if p.strip()]
        if len(subparts) >= 2:
            detected_bpm = subparts[0]
            detected_key = subparts[1]
        elif len(subparts) == 1:
            detected_bpm = subparts[0]
        text = TRAILING_BPM_KEY.sub('', text)

    # Remove BPMs isolados residuais tipo " . 130 " ou " - 128 bpm"
    bpm_isolated = re.search(r'\s*\.\s*(\d{2,3}(?:\.\d+)?)\s*(?:\.|$)', text)
    if bpm_isolated and not detected_bpm:
        detected_bpm = bpm_isolated.group(1)
        text = re.sub(r'\s*\.\s*\d{2,3}(?:\.\d+)?\s*(?:\.|$)', ' ', text)

    # 4. Remove numeração de faixa inicial se houver (ex: "01 - ", "11. ")
    text = re.sub(r'^\d{1,3}\s*[-–.]\s*', '', text)

    # 5. Remove duplicação de parênteses/colchetes: ex (Single Version) (Single Version)
    text = re.sub(r'(\([^\)]+\))\s*\1', r'\1', text, flags=re.IGNORECASE)
    text = re.sub(r'(\[[^\]]+\])\s*\1', r'\1', text, flags=re.IGNORECASE)

    # 6. Normaliza aspas soltas e espaços múltiplos
    text = re.sub(r'(?<=\s)\"\s*(.*?)\s*\"(?=\s|$)', r'\1', text)
    text = text.replace('\"', '')
    text = re.sub(r'\s*-\s*-\s*', ' - ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # 7. Separação Inteligente: split por " - "
    raw_parts = [unicodedata.normalize('NFC', p.strip()) for p in text.split(" - ") if p.strip()]

    # 8. Remove todas as ocorrências de Crate Raiz embutidas no nome do arquivo
    non_crate_parts = []
    for p in raw_parts:
        if crate_raiz and p.lower() == crate_raiz.lower():
            continue
        non_crate_parts.append(p)

    # 9. Deduplica partes repetidas consecutivas ou cíclicas mantendo a ordem original
    unique_parts = []
    for p in non_crate_parts:
        p_clean = TRAILING_PUNCT.sub('', p).strip(" -–:").strip()
        if not p_clean:
            continue
        if p_clean.lower() not in [u.lower() for u in unique_parts]:
            unique_parts.append(p_clean)

    # Detecção de Compilação Russa / Coletânea ('Sbornik', 'Various Artists', 'VA')
    if unique_parts and unique_parts[0].lower() in ['sbornik', 'various', 'various artists', 'v.a.', 'va']:
        unique_parts = unique_parts[1:]

    # 10. Sanitiza tags existentes passadas via Mutagen
    clean_ex_art = unicodedata.normalize('NFC', existing_artist).replace('_', ' ').strip() if existing_artist else ""
    clean_ex_tit = unicodedata.normalize('NFC', existing_title).replace('_', ' ').strip() if existing_title else ""
    clean_ex_alb = unicodedata.normalize('NFC', existing_album).replace('_', ' ').strip() if existing_album else ""

    for pattern in NOISE_PATTERNS:
        if clean_ex_art: clean_ex_art = pattern.sub('', clean_ex_art)
        if clean_ex_tit: clean_ex_tit = pattern.sub('', clean_ex_tit)
        if clean_ex_alb: clean_ex_alb = pattern.sub('', clean_ex_alb)

    if clean_ex_art:
        clean_ex_art = TRAILING_PUNCT.sub('', clean_ex_art).strip(' -–:').strip()

    if clean_ex_tit:
        clean_ex_tit = TRAILING_BPM_KEY.sub('', clean_ex_tit)
        clean_ex_tit = re.sub(r'^\d{1,3}\s*[-–.]\s*', '', clean_ex_tit)
        clean_ex_tit = TRAILING_PUNCT.sub('', clean_ex_tit).strip(' -–:').strip()
        if crate_raiz and clean_ex_tit.lower().endswith(f" - {crate_raiz.lower()}"):
            clean_ex_tit = clean_ex_tit[:-(len(crate_raiz) + 3)].strip()

    if clean_ex_alb:
        clean_ex_alb = TRAILING_PUNCT.sub('', clean_ex_alb).strip(' -–:').strip()
        if clean_ex_alb.lower() == crate_raiz.lower():
            clean_ex_alb = ""

    if clean_ex_tit and (clean_ex_tit.lower() == filename_no_ext.lower() or clean_ex_tit.lower() == text.lower()):
        clean_ex_tit = ""

    # Determina partes base a partir de unique_parts
    if len(unique_parts) >= 3:
        p_art = unique_parts[0]
        p_tit = unique_parts[1]
        p_alb = unique_parts[2]
    elif len(unique_parts) == 2:
        p_art = unique_parts[0]
        p_tit = unique_parts[1]
        p_alb = ""
    elif len(unique_parts) == 1:
        if clean_ex_art and clean_ex_art.lower() != unique_parts[0].lower():
            p_art = clean_ex_art
            p_tit = unique_parts[0]
        else:
            p_art = ""
            p_tit = unique_parts[0]
        p_alb = ""
    else:
        p_art, p_tit, p_alb = "", "", ""

    # Se a tag do título tinha o álbum duplicado no final, remove
    if p_alb and clean_ex_tit.lower().endswith(f" - {p_alb.lower()}"):
        clean_ex_tit = clean_ex_tit[:-(len(p_alb) + 3)].strip()
    if clean_ex_alb and clean_ex_tit.lower().endswith(f" - {clean_ex_alb.lower()}"):
        clean_ex_tit = clean_ex_tit[:-(len(clean_ex_alb) + 3)].strip()

    artist = p_art or clean_ex_art
    title = p_tit or clean_ex_tit
    album = p_alb or clean_ex_alb

    # Se a tag de título tem versão rica que o nome do arquivo perdeu, recupera
    if clean_ex_tit and re.search(r'[\(\[].*(?:remix|mix|feat|ft\.|ao vivo|live|acustic|acústic|vers|edit|bootleg|dub)[\)\]]', clean_ex_tit, re.IGNORECASE):
        if not re.search(r'[\(\[].*(?:remix|mix|feat|ft\.|ao vivo|live|acustic|acústic|vers|edit|bootleg|dub)[\)\]]', title, re.IGNORECASE):
            title = clean_ex_tit

    # Detecção e remoção de Artista Duplicado no Título!
    if artist and title:
        art_clean = re.escape(artist.strip())
        title_stripped = re.sub(r'^' + art_clean + r'\s*[-–:]\s*', '', title, flags=re.IGNORECASE).strip()
        if title_stripped:
            title = title_stripped
        if artist.strip().lower() == title.strip().lower():
            artist = ""

    # Caso CPM 22 ou similar sem traço
    if not artist and title:
        m_cpm = re.match(r'^(cpm\s*22)\s+([^-–].+)$', title, re.IGNORECASE)
        if m_cpm:
            artist = "CPM 22"
            title = m_cpm.group(2).strip()

    # Se ainda não tem artista, consulta o cache de títulos conhecidos / MusicBrainz
    if not artist and title:
        cached_art = get_cached_artist(title)
        if cached_art:
            artist = cached_art

    # Casos especiais de bandas compostas abreviadas:
    if artist:
        art_l = artist.lower()
        tit_l = title.lower()
        if 'blink' in art_l and '182' in tit_l:
            m_b = re.match(r'^blink[-_ ]?182\s*[-–]\s*(.+)$', title, re.IGNORECASE)
            if m_b:
                artist = "Blink-182"
                title = m_b.group(1).strip()
        elif 'guns' in art_l and 'rose' in tit_l:
            m_g = re.match(r'^guns[-_ ]?(?:n|and)[-_ ]?roses?\s*[-–]\s*(.+)$', title, re.IGNORECASE)
            if m_g:
                artist = "Guns N' Roses"
                title = m_g.group(1).strip()

    # Se ainda restou reticências truncadas no título:
    if title and '...' in title and artist:
        title = re.sub(r'^[^\.]*\.\.\.\s*', '', title).strip()

    # Se o álbum for igual à Crate ou Título, ou contido no título, anula para evitar duplicação
    if album and (album.lower() == crate_raiz.lower() or album.lower() in title.lower() or title.lower() in album.lower()):
        album = ""

    # Limpeza final de traços e espaços residuais
    title = title.strip(' -–:').strip()
    artist = artist.strip(' -–:').strip()

    if artist:
        art_l = artist.lower()
        if art_l in ['cpm 22', 'cpm22']:
            artist = "CPM 22"
        elif art_l == 'u2':
            artist = "U2"
        elif art_l == 'rbd':
            artist = "RBD"
        elif art_l == 'ac/dc':
            artist = "AC/DC"
        elif (artist.isupper() and len(artist) > 4) or artist.islower():
            artist = artist.title()

    # Formatos de Nomenclatura para o DJ escolher:
    fmt_dj = f"{artist} - {title}".strip(" -") if artist else title
    fmt_crate = f"{artist} - {title} - {crate_raiz}".strip(" -") if crate_raiz else fmt_dj

    extra_parts = []
    if crate_raiz:
        extra_parts.append(crate_raiz)
    if album and album.lower() != crate_raiz.lower() and album.lower() not in title.lower():
        extra_parts.append(album)

    if extra_parts:
        fmt_completo = f"{artist} - {title} - {' - '.join(extra_parts)}".strip(" -")
    else:
        fmt_completo = fmt_crate

    # Trava matemática anti-estouro de nome de arquivo no APFS (max 180 chars para stem)
    if len(fmt_completo) > 180:
        fmt_completo = fmt_completo[:180].rstrip(" -–:")
    if len(fmt_crate) > 180:
        fmt_crate = fmt_crate[:180].rstrip(" -–:")
    if len(fmt_dj) > 180:
        fmt_dj = fmt_dj[:180].rstrip(" -–:")

    return {
        "artist": artist,
        "title": title,
        "album": album,
        "crate_raiz": crate_raiz,
        "crate_completa": crate_completa,
        "clean_filename": fmt_dj,
        "fmt_dj": fmt_dj,
        "fmt_crate": fmt_crate,
        "fmt_completo": fmt_completo,
        "detected_bpm": detected_bpm,
        "detected_key": detected_key
    }


def list_crates_and_subcrates(mp3_dir_str: str):
    """Mapeia rapidamente todas as crates raiz e suas respectivas subcrates."""
    base_path = Path(os.path.expanduser(mp3_dir_str)).resolve()
    if not base_path.exists():
        return {"sucesso": False, "erro": f"Pasta não encontrada: {base_path}"}

    crates_dict = {}
    for entry in base_path.iterdir():
        if entry.is_dir() and not entry.name.startswith('.'):
            crates_dict[entry.name] = {
                "nome": entry.name,
                "total": 0,
                "subcrates": {}
            }

    for root, dirs, files in os.walk(str(base_path)):
        if '/.' in root or '\\.' in root:
            continue
        rel = os.path.relpath(root, str(base_path))
        if rel == '.':
            continue
        parts = rel.split(os.sep)
        crate_raiz = parts[0]
        if crate_raiz in crates_dict:
            audio_count = sum(1 for f in files if Path(f).suffix.lower() in AUDIO_EXTENSIONS and not f.startswith('.'))
            crates_dict[crate_raiz]["total"] += audio_count
            if len(parts) > 1:
                sub = "/".join(parts[1:])
                crates_dict[crate_raiz]["subcrates"][sub] = audio_count

    # Formata lista ordenada
    result_crates = []
    for crate_name in sorted(crates_dict.keys(), key=lambda x: x.lower()):
        c_data = crates_dict[crate_name]
        subs_list = []
        for sub_name in sorted(c_data["subcrates"].keys(), key=lambda x: x.lower()):
            subs_list.append({
                "nome": sub_name,
                "caminho_rel": sub_name,
                "total": c_data["subcrates"][sub_name]
            })
        result_crates.append({
            "nome": crate_name,
            "total": c_data["total"],
            "subcrates": subs_list
        })

    return {"sucesso": True, "crates": result_crates}


def scan_audio_tags(mp3_dir_str: str, limit: int = 50, offset: int = 0, search_filter: str = "",
                    crate_raiz: str = "", subcrate: str = "", include_subcrates: bool = True,
                    naming_mode: str = "full"):
    """Varre arquivos de áudio, inspeciona nomes em altíssima velocidade e lê tags ID3 da página atual."""
    base_path = Path(os.path.expanduser(mp3_dir_str)).resolve()
    if not base_path.exists():
        return {"sucesso": False, "erro": f"Pasta não encontrada: {base_path}"}

    items = []
    total_found = 0
    total_dirty = 0

    search_lower = search_filter.strip().lower() if search_filter else ""

    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    if not target_dir.exists():
        return {
            "sucesso": True,
            "total_encontrados": 0,
            "total_precisam_limpeza": 0,
            "limite": limit,
            "offset": offset,
            "items": []
        }

    for root, dirs, files in os.walk(str(target_dir)):
        # Ignora lixeiras e pastas ocultas
        if '/.' in root or '\\.' in root:
            continue

        if crate_raiz and not include_subcrates and not subcrate:
            if root != str(target_dir):
                dirs.clear()
                continue
            dirs.clear()

        rel_folder = os.path.relpath(root, str(base_path))

        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue

            ext = Path(f).suffix.lower()
            if ext in AUDIO_EXTENSIONS:
                total_found += 1

                # Filtro de busca se houver
                if search_lower and search_lower not in f.lower():
                    continue

                name_no_ext = Path(f).stem
                clean_quick = clean_track_name(name_no_ext, rel_folder=rel_folder)

                clean_dj = f"{clean_quick['fmt_dj']}{ext}"
                clean_crate = f"{clean_quick['fmt_crate']}{ext}"
                clean_full = f"{clean_quick['fmt_completo']}{ext}"

                if naming_mode == 'dj':
                    clean_target_name = clean_dj
                elif naming_mode == 'crate':
                    clean_target_name = clean_crate
                else:
                    clean_target_name = clean_full

                # Uma faixa já tem o nome limpo no disco se bate com qualquer um dos padrões oficiais válidos
                f_norm = unicodedata.normalize('NFC', f)
                is_name_clean = (f_norm == clean_dj or f_norm == clean_crate or f_norm == clean_full)
                if not is_name_clean:
                    total_dirty += 1

                # Apenas lê tags ID3 pesadas via mutagen para os itens da página atual
                if total_found > offset and len(items) < limit:
                    full_path = Path(root) / f
                    artist_current = ""
                    title_current = ""
                    album_current = ""
                    genre_current = ""
                    bpm_current = ""
                    key_current = ""

                    if mutagen:
                        try:
                            audio = mutagen.File(str(full_path))
                            if audio is not None:
                                if 'TIT2' in audio:
                                    title_current = str(audio['TIT2'])
                                elif 'title' in audio:
                                    title_current = str(audio['title'][0])

                                if 'TPE1' in audio:
                                    artist_current = str(audio['TPE1'])
                                elif 'artist' in audio:
                                    artist_current = str(audio['artist'][0])

                                if 'TALB' in audio:
                                    album_current = str(audio['TALB'])
                                elif 'album' in audio:
                                    album_current = str(audio['album'][0])

                                if 'TCON' in audio:
                                    genre_current = str(audio['TCON'])
                                elif 'genre' in audio:
                                    genre_current = str(audio['genre'][0])

                                if 'TBPM' in audio:
                                    bpm_current = str(audio['TBPM'])
                                elif 'bpm' in audio:
                                    bpm_current = str(audio['bpm'][0])

                                if 'TKEY' in audio:
                                    key_current = str(audio['TKEY'])
                                elif 'initialkey' in audio:
                                    key_current = str(audio['initialkey'][0])
                        except Exception:
                            pass

                    clean_res = clean_track_name(
                        name_no_ext,
                        rel_folder=rel_folder,
                        existing_artist=artist_current,
                        existing_title=title_current,
                        existing_album=album_current
                    )
                    final_bpm = bpm_current or clean_res["detected_bpm"]
                    final_key = key_current or clean_res["detected_key"]

                    item_clean_dj = f"{clean_res['fmt_dj']}{ext}"
                    item_clean_crate = f"{clean_res['fmt_crate']}{ext}"
                    item_clean_full = f"{clean_res['fmt_completo']}{ext}"

                    if naming_mode == 'dj':
                        item_target = item_clean_dj
                    elif naming_mode == 'crate':
                        item_target = item_clean_crate
                    else:
                        item_target = item_clean_full

                    f_norm = unicodedata.normalize('NFC', f)
                    is_item_name_clean = (f_norm == item_clean_dj or f_norm == item_clean_crate or f_norm == item_clean_full)

                    if artist_current and title_current:
                        seed_tag_cache(title_current, artist_current)

                    # Verifica se as tags ID3 oficiais já estão limpas e coincidem com Artista e Título limpos
                    if clean_res["artist"]:
                        tags_clean = bool(
                            artist_current and title_current and
                            artist_current.strip().lower() == clean_res["artist"].strip().lower() and
                            title_current.strip().lower() == clean_res["title"].strip().lower()
                        )
                    else:
                        tags_clean = bool(title_current and title_current.strip().lower() == clean_res["title"].strip().lower())

                    needs_clean = not (is_item_name_clean and tags_clean)

                    items.append({
                        "id": f"tag-{total_found}",
                        "caminho": str(full_path),
                        "arquivo_atual": f,
                        "arquivo_sugerido": item_target,
                        "nome_dj": item_clean_dj,
                        "nome_crate": item_clean_crate,
                        "nome_completo": item_clean_full,
                        "pasta": str(Path(root)),
                        "crate_raiz": clean_res["crate_raiz"],
                        "crate_completa": clean_res["crate_completa"],
                        "artista_atual": artist_current,
                        "artista_sugerido": clean_res["artist"],
                        "titulo_atual": title_current,
                        "titulo_sugerido": clean_res["title"],
                        "album_atual": album_current,
                        "album_sugerido": clean_res["album"],
                        "genero_atual": genre_current,
                        "genero_sugerido": clean_res["crate_raiz"],
                        "bpm": final_bpm,
                        "key": final_key,
                        "formato": ext.upper().replace('.', ''),
                        "precisa_limpeza": needs_clean
                    })

    return {
        "sucesso": True,
        "total_encontrados": total_found,
        "total_precisam_limpeza": total_dirty,
        "limite": limit,
        "offset": offset,
        "items": items
    }


def apply_cleaned_tags(items_to_apply: list, rename_files_on_disk: bool = False):
    """Aplica as tags limpas diretamente nos arquivos preservando tags Serato."""
    if not mutagen:
        return {"sucesso": False, "erro": "Mutagen não está instalado no sistema."}

    updated_count = 0
    errors = []

    for item in items_to_apply:
        file_path = Path(item["caminho"])
        if not file_path.exists():
            continue

        novo_artista = item.get("artista_sugerido", "").strip()
        novo_titulo = item.get("titulo_sugerido", "").strip()
        novo_album = item.get("album_sugerido", "").strip()
        crate_raiz = item.get("crate_raiz", "").strip()

        try:
            audio = mutagen.File(str(file_path))
            if audio is None:
                continue

            # Se for MP3 (ID3)
            if hasattr(audio, 'tags'):
                if audio.tags is None:
                    audio.add_tags()

                if novo_titulo:
                    audio.tags['TIT2'] = TIT2(encoding=3, text=novo_titulo)
                if novo_artista:
                    audio.tags['TPE1'] = TPE1(encoding=3, text=novo_artista)
                if novo_album:
                    audio.tags['TALB'] = TALB(encoding=3, text=novo_album)
                if crate_raiz:
                    audio.tags['TCON'] = TCON(encoding=3, text=crate_raiz)

                # Salva preservando tags Serato Markers
                audio.save()
            else:
                if novo_titulo:
                    audio['title'] = [novo_titulo]
                if novo_artista:
                    audio['artist'] = [novo_artista]
                if novo_album:
                    audio['album'] = [novo_album]
                if crate_raiz:
                    audio['genre'] = [crate_raiz]
                audio.save()

            # Renomeação opcional segura no disco contra colisões de caixa APFS
            if rename_files_on_disk and item.get("arquivo_sugerido"):
                novo_nome = item["arquivo_sugerido"]
                novo_caminho = file_path.parent / novo_nome
                if novo_caminho != file_path:
                    is_same_file = False
                    try:
                        if novo_caminho.exists():
                            is_same_file = os.path.samefile(file_path, novo_caminho)
                    except Exception:
                        pass

                    if not novo_caminho.exists() or is_same_file:
                        try:
                            if is_same_file:
                                temp_path = file_path.parent / f".tmp_{abs(hash(str(file_path)))}.tmp"
                                file_path.rename(temp_path)
                                temp_path.rename(novo_caminho)
                            else:
                                file_path.rename(novo_caminho)
                            file_path = novo_caminho
                        except Exception as e_ren:
                            errors.append(f"Renomear {file_path.name}: {e_ren}")
                    else:
                        # Colisão: arquivo de mesmo nome já existe no disco, adiciona sufixo numérico
                        try:
                            c = 1
                            alt_stem = Path(novo_nome).stem
                            alt_dest = file_path.parent / f"{alt_stem} ({c}){file_path.suffix}"
                            while alt_dest.exists():
                                try:
                                    if os.path.samefile(file_path, alt_dest):
                                        break
                                except Exception:
                                    pass
                                c += 1
                                alt_dest = file_path.parent / f"{alt_stem} ({c}){file_path.suffix}"
                            file_path.rename(alt_dest)
                            file_path = alt_dest
                        except Exception as e_ren:
                            errors.append(f"Renomear {file_path.name}: {e_ren}")

            updated_count += 1
        except Exception as e:
            errors.append(f"{file_path.name}: {e}")

    return {
        "sucesso": True,
        "atualizados": updated_count,
        "total_solicitados": len(items_to_apply),
        "erros": errors[:10]
    }


def batch_apply_tags(mp3_dir_str: str, crate_raiz: str = "", subcrate: str = "",
                     include_subcrates: bool = True, naming_mode: str = "full",
                     rename_files: bool = False, search_filter: str = ""):
    """Executa higienização em massa para uma Crate, Subcrate ou toda a biblioteca com streaming de progresso."""
    if not mutagen:
        print(json.dumps({"tipo": "fim", "sucesso": False, "erro": "Mutagen não está instalado no sistema."}, ensure_ascii=False), flush=True)
        return

    base_path = Path(os.path.expanduser(mp3_dir_str)).resolve()
    if not base_path.exists():
        print(json.dumps({"tipo": "fim", "sucesso": False, "erro": f"Pasta não encontrada: {base_path}"}, ensure_ascii=False), flush=True)
        return

    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    if not target_dir.exists():
        print(json.dumps({"tipo": "fim", "sucesso": False, "erro": f"Caminho não encontrado: {target_dir}"}, ensure_ascii=False), flush=True)
        return

    search_lower = search_filter.strip().lower() if search_filter else ""

    # 1. Enumera rapidamente e filtra estritamente os arquivos que precisam de correção
    files_to_process = []
    for root, dirs, files in os.walk(str(target_dir)):
        if '/.' in root or '\\.' in root:
            continue
        if crate_raiz and not include_subcrates and not subcrate:
            if root != str(target_dir):
                dirs.clear()
                continue
            dirs.clear()

        rel_folder = os.path.relpath(root, str(base_path))

        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            ext = Path(f).suffix.lower()
            if ext in AUDIO_EXTENSIONS:
                if search_lower and search_lower not in f.lower():
                    continue

                name_no_ext = Path(f).stem
                clean_quick = clean_track_name(name_no_ext, rel_folder=rel_folder)

                clean_dj = f"{clean_quick['fmt_dj']}{ext}"
                clean_crate = f"{clean_quick['fmt_crate']}{ext}"
                clean_full = f"{clean_quick['fmt_completo']}{ext}"

                f_norm = unicodedata.normalize('NFC', f)
                is_name_clean = (f_norm == clean_dj or f_norm == clean_crate or f_norm == clean_full)

                if naming_mode == 'dj':
                    target_name = clean_dj
                elif naming_mode == 'crate':
                    target_name = clean_crate
                else:
                    target_name = clean_full

                needs_rename = (rename_files and f_norm != target_name)
                needs_clean = not is_name_clean

                if needs_clean or needs_rename:
                    files_to_process.append((Path(root) / f, rel_folder, f, ext))

    total = len(files_to_process)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    if total == 0:
        print(json.dumps({"tipo": "fim", "sucesso": True, "atualizados": 0, "total": 0, "erros": []}, ensure_ascii=False), flush=True)
        return

    updated_count = 0
    errors = []

    for idx, (full_path, rel_folder, filename, ext) in enumerate(files_to_process, 1):
        try:
            name_no_ext = Path(filename).stem
            artist_current = ""
            title_current = ""
            album_current = ""
            try:
                audio = mutagen.File(str(full_path))
                if audio is not None:
                    if 'TIT2' in audio: title_current = str(audio['TIT2'])
                    elif 'title' in audio: title_current = str(audio['title'][0])
                    if 'TPE1' in audio: artist_current = str(audio['TPE1'])
                    elif 'artist' in audio: artist_current = str(audio['artist'][0])
                    if 'TALB' in audio: album_current = str(audio['TALB'])
                    elif 'album' in audio: album_current = str(audio['album'][0])
            except Exception:
                pass

            clean_res = clean_track_name(
                name_no_ext,
                rel_folder=rel_folder,
                existing_artist=artist_current,
                existing_title=title_current,
                existing_album=album_current
            )

            # Escolhe nomenclatura conforme o modo selecionado
            if naming_mode == 'full' and clean_res.get('fmt_completo'):
                suggested_stem = clean_res['fmt_completo']
            elif naming_mode == 'crate' and clean_res.get('fmt_crate'):
                suggested_stem = clean_res['fmt_crate']
            elif naming_mode == 'dj' and clean_res.get('fmt_dj'):
                suggested_stem = clean_res['fmt_dj']
            else:
                suggested_stem = clean_res['clean_filename']

            suggested_filename = f"{suggested_stem}{ext}"

            # Grava tags ID3 com mutagen (preservando GEOB Serato Markers2)
            audio = mutagen.File(str(full_path))
            if audio is not None:
                if hasattr(audio, 'tags'):
                    if audio.tags is None:
                        audio.add_tags()
                    if clean_res['title']:
                        audio.tags['TIT2'] = TIT2(encoding=3, text=clean_res['title'])
                    if clean_res['artist']:
                        audio.tags['TPE1'] = TPE1(encoding=3, text=clean_res['artist'])
                    if clean_res['album']:
                        audio.tags['TALB'] = TALB(encoding=3, text=clean_res['album'])
                    if clean_res['crate_raiz']:
                        audio.tags['TCON'] = TCON(encoding=3, text=clean_res['crate_raiz'])
                    audio.save()
                else:
                    if clean_res['title']: audio['title'] = [clean_res['title']]
                    if clean_res['artist']: audio['artist'] = [clean_res['artist']]
                    if clean_res['album']: audio['album'] = [clean_res['album']]
                    if clean_res['crate_raiz']: audio['genre'] = [clean_res['crate_raiz']]
                    audio.save()

            # Renomeação opcional no disco segura contra colisões de caixa APFS
            if rename_files and suggested_filename != filename:
                dest_path = full_path.parent / suggested_filename
                if dest_path != full_path:
                    is_same_file = False
                    try:
                        if dest_path.exists():
                            is_same_file = os.path.samefile(full_path, dest_path)
                    except Exception:
                        pass

                    if not dest_path.exists() or is_same_file:
                        try:
                            if is_same_file:
                                temp_path = full_path.parent / f".tmp_{abs(hash(str(full_path)))}.tmp"
                                full_path.rename(temp_path)
                                temp_path.rename(dest_path)
                            else:
                                full_path.rename(dest_path)
                            full_path = dest_path
                        except Exception as e_rename:
                            errors.append(f"Renomear {filename}: {e_rename}")
                    else:
                        # Colisão: arquivo de mesmo nome já existe no disco, adiciona sufixo numérico
                        try:
                            c = 1
                            alt_dest = full_path.parent / f"{suggested_stem} ({c}){ext}"
                            while alt_dest.exists():
                                try:
                                    if os.path.samefile(full_path, alt_dest):
                                        break
                                except Exception:
                                    pass
                                c += 1
                                alt_dest = full_path.parent / f"{suggested_stem} ({c}){ext}"
                            full_path.rename(alt_dest)
                            full_path = alt_dest
                        except Exception as e_rename:
                            errors.append(f"Renomear {filename}: {e_rename}")

            updated_count += 1
        except Exception as e:
            errors.append(f"{filename}: {e}")

        # Streaming de progresso a cada 10 arquivos ou no final
        if idx % 10 == 0 or idx == total:
            pct = round((idx / total) * 100, 1)
            print(json.dumps({
                "tipo": "progresso",
                "processados": idx,
                "total": total,
                "percentual": pct,
                "atualizados": updated_count,
                "faixa_atual": filename
            }, ensure_ascii=False), flush=True)

    print(json.dumps({
        "tipo": "fim",
        "sucesso": True,
        "atualizados": updated_count,
        "total": total,
        "erros": errors[:15]
    }, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Tag Doctor")
    parser.add_argument("--backup-db", action="store_true", help="Cria backup seguro do master.sqlite")
    parser.add_argument("--list-backups", action="store_true", help="Lista backups do banco")
    parser.add_argument("--restore-db", type=str, default="", help="Restaura banco especificado")
    parser.add_argument("--list-crates", action="store_true", help="Lista crates e subcrates disponíveis")
    parser.add_argument("--scan-tags", action="store_true", help="Analisa tags da pasta MP3")
    parser.add_argument("--batch-apply", action="store_true", help="Aplica correções em lote para Crate ou biblioteca")
    parser.add_argument("--mp3", type=str, default="", help="Caminho da pasta MP3")
    parser.add_argument("--crate-raiz", type=str, default="", help="Nome da Crate Raiz")
    parser.add_argument("--subcrate", type=str, default="", help="Subcrate específica")
    parser.add_argument("--no-subcrates", action="store_true", help="Não incluir subcrates automaticamente")
    parser.add_argument("--naming-mode", type=str, default="full", choices=["full", "crate", "dj"], help="Modo de nomenclatura")
    parser.add_argument("--limit", type=int, default=100, help="Limite de faixas na listagem")
    parser.add_argument("--offset", type=int, default=0, help="Offset de paginação")
    parser.add_argument("--search", type=str, default="", help="Filtro de busca")
    parser.add_argument("--apply-tags", type=str, default="", help="Caminho do arquivo JSON com itens a atualizar")
    parser.add_argument("--rename-files", action="store_true", help="Renomeia arquivos fisicamente no disco")
    parser.add_argument("--enrich-artists", type=str, default="", help="Identifica artistas faltantes via MusicBrainz/Cache para itens JSON")

    args = parser.parse_args()

    if args.backup_db:
        res = backup_master_database()
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.list_backups:
        backups = list_master_backups()
        print(json.dumps(backups, ensure_ascii=False))
        sys.exit(0)

    if args.restore_db:
        res = restore_master_database(args.restore_db)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    mp3_dir = args.mp3 or "/Volumes/Pastteyr/Music/MP3"

    if args.list_crates:
        res = list_crates_and_subcrates(mp3_dir)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.batch_apply:
        batch_apply_tags(
            mp3_dir_str=mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates,
            naming_mode=args.naming_mode,
            rename_files=args.rename_files,
            search_filter=args.search
        )
        sys.exit(0)

    if args.scan_tags:
        res = scan_audio_tags(
            mp3_dir_str=mp3_dir,
            limit=args.limit,
            offset=args.offset,
            search_filter=args.search,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates,
            naming_mode=args.naming_mode
        )
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.enrich_artists:
        try:
            if args.enrich_artists == "-":
                items = json.load(sys.stdin)
            elif os.path.exists(args.enrich_artists):
                with open(args.enrich_artists, "r", encoding="utf-8") as f:
                    items = json.load(f)
            else:
                items = json.loads(args.enrich_artists)
            res = enrich_missing_artists(items)
            print(json.dumps(res, ensure_ascii=False))
            sys.exit(0 if res.get("sucesso") else 1)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}))
            sys.exit(1)

    if args.apply_tags:
        try:
            if args.apply_tags == "-":
                items = json.load(sys.stdin)
            elif os.path.exists(args.apply_tags):
                with open(args.apply_tags, "r", encoding="utf-8") as f:
                    items = json.load(f)
            else:
                items = json.loads(args.apply_tags)
            res = apply_cleaned_tags(items, rename_files_on_disk=args.rename_files)
            print(json.dumps(res, ensure_ascii=False))
            sys.exit(0 if res.get("sucesso") else 1)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}))
            sys.exit(1)

    parser.print_help()


if __name__ == "__main__":
    main()
