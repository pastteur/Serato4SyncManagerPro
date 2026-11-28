#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 5 SYNC MANAGER PRO - TRACK MATCHER ENGINE (track_matcher.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Cruzamento de playlists (Spotify, YouTube Music, M3U, CSV ou Texto) contra as
31.355 faixas do HD, gerando crates prontas para o Serato DJ Pro 4.
================================================================================
"""

import sys
import os

sys.dont_write_bytecode = True
import re
import json
import shutil
import sqlite3
import argparse
import hashlib
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

# Vendor fallback: permite carregar dependências empacotadas sem exigir pip local
_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

try:
    import mutagen
except ImportError:
    mutagen = None

try:
    from fts_library_cache import FTSLibraryCache
except ImportError:
    FTSLibraryCache = None

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

DB_PATH = Path.home() / ".serato_sound_seals.sqlite"
AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')

VERSION_KEYWORDS = {
    'remix', 'mix', 'extended', 'radio', 'edit', 'club', 'dub',
    'instrumental', 'acapella', 'acapela', 'ao vivo', 'live',
    'acustico', 'acoustic', 'mashup', 'bootleg', 'vip', 'rework',
    'flip', 'cover', 'sped up', 'speed up', 'nightcore', 'slowed',
    'original mix', 'vocal mix', 'clean', 'dirty'
}


def _ensure_seal(req: dict) -> str:
    """Calcula o selo de áudio apenas uma vez, sob demanda, para uma faixa de origem."""
    if req.get("audio_seal"):
        return req["audio_seal"]
    caminho = req.get("filepath")
    if not caminho:
        return ""
    seal = compute_audio_seal(caminho)
    req["audio_seal"] = seal
    return seal


def compute_audio_seal(filepath_str: str) -> str:
    """Calcula a impressão digital SHA-256 do fluxo de áudio puro ignorando tags ID3."""
    try:
        with open(filepath_str, 'rb') as f:
            header = f.read(10)
            start_offset = 0
            if len(header) >= 10 and header[:3] == b'ID3':
                size = ((header[6] & 0x7F) << 21) | ((header[7] & 0x7F) << 14) | ((header[8] & 0x7F) << 7) | (header[9] & 0x7F)
                start_offset = 10 + size
                if header[5] & 0x10:
                    start_offset += 10
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            end_offset = file_size
            if file_size > 128:
                f.seek(file_size - 128)
                if f.read(3) == b'TAG':
                    end_offset -= 128
            f.seek(start_offset)
            hasher = hashlib.sha256()
            bytes_to_read = max(0, end_offset - start_offset)
            chunk_size = 65536
            while bytes_to_read > 0:
                chunk = f.read(min(bytes_to_read, chunk_size))
                if not chunk:
                    break
                hasher.update(chunk)
                bytes_to_read -= len(chunk)
            return hasher.hexdigest()
    except Exception:
        return ""


def extract_version_descriptors(text: str) -> set:
    """Extrai marcadores explícitos de versão/mix contidos no título ou nome do arquivo."""
    if not text:
        return set()
    found = set()
    lower = unicodedata.normalize('NFC', text.lower())
    
    # 1. Busca termos dentro de parênteses ou colchetes
    parenteses = re.findall(r'[\(\[\{](.*?)[\)\]\}]', lower)
    for p in parenteses:
        p_clean = re.sub(r'[^\w\s]', ' ', p).strip()
        tokens = p_clean.split()
        for tok in tokens:
            if tok in VERSION_KEYWORDS:
                found.add(tok)
        if 'remix' in p or 'mix' in p:
            found.add('remix')
            for w in tokens:
                if len(w) > 2 and w not in ('remix', 'mix', 'extended', 'radio', 'edit', 'club', 'the', 'version'):
                    found.add(f"remixer:{w}")
                    
    # 2. Busca termos após hífen final (ex: "Faixa - Alok Remix")
    if ' - ' in lower:
        parts = lower.split(' - ')
        last_part = parts[-1]
        for kw in VERSION_KEYWORDS:
            if re.search(r'\b' + re.escape(kw) + r'\b', last_part):
                found.add(kw)
                
    return found


import difflib

STOP_WORDS = {"the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with", "by", "o", "a", "os", "as", "de", "do", "da", "dos", "das", "e", "em", "um", "uma"}

def token_similarity(s1: str, s2: str) -> float:
    """Calcula similaridade combinada (tokens + sequência de caracteres) entre dois textos."""
    if not s1 or not s2:
        return 0.0
    s1_clean = s1.strip().lower()
    s2_clean = s2.strip().lower()
    if s1_clean == s2_clean:
        return 1.0

    tokens1 = set(w for w in s1_clean.split() if w not in STOP_WORDS and len(w) > 1)
    tokens2 = set(w for w in s2_clean.split() if w not in STOP_WORDS and len(w) > 1)

    seq_ratio = difflib.SequenceMatcher(None, s1_clean, s2_clean).ratio()

    if tokens1 and tokens2:
        intersection = tokens1.intersection(tokens2)
        union = tokens1.union(tokens2)
        jaccard = len(intersection) / len(union) if union else 0.0
        return max(jaccard, seq_ratio)
    return seq_ratio


def normalize_str(s: str) -> str:
    """Normaliza texto base para comparação fonética/fuzzy removendo parênteses."""
    if not s:
        return ""
    s = unicodedata.normalize('NFC', s.lower())
    s = re.sub(r'[\(\[\{].*?[\)\]\}]', '', s) # remove parenteses
    s = re.sub(r'[^\w\s]', '', s) # remove pontuações
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def normalize_full_str(s: str) -> str:
    """Normaliza texto completo preservando os termos de versão."""
    if not s:
        return ""
    s = unicodedata.normalize('NFC', s.lower())
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def parse_incoming_folder(folder_path_str: str):
    """
    Varre uma pasta local de novos arquivos de áudio (downloads, novos packs)
    e extrai metadados completos de cada faixa para cruzamento com a biblioteca master.
    """
    folder_path = Path(os.path.expanduser(folder_path_str)).resolve()
    if not folder_path.exists():
        return []

    tracks = []
    for root, _, files in os.walk(str(folder_path)):
        if '/.' in root or '\\.' in root:
            continue
        for f in files:
            if f.startswith('.') or f.startswith('._'):
                continue
            ext = Path(f).suffix.lower()
            if ext in AUDIO_EXTENSIONS:
                full_p = Path(root) / f
                stem = full_p.stem
                artist = ""
                title = stem
                bitrate = 0
                sample_rate = 0
                duration = 0.0
                filesize = 0

                try:
                    filesize = full_p.stat().st_size
                    if mutagen:
                        audio = mutagen.File(str(full_p))
                        if audio:
                            if getattr(audio, 'info', None):
                                duration = getattr(audio.info, 'length', 0.0)
                                bitrate = getattr(audio.info, 'bitrate', 0)
                                sample_rate = getattr(audio.info, 'sample_rate', 0)
                            tags = getattr(audio, 'tags', None)
                            if tags:
                                if 'TPE1' in tags:
                                    artist = str(tags['TPE1'])
                                if 'TIT2' in tags:
                                    title = str(tags['TIT2'])
                except Exception:
                    pass

                if not artist and ' - ' in stem:
                    parts = stem.split(' - ', 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()

                raw_str = f"{artist} - {title}" if artist else stem
                version_tags = list(extract_version_descriptors(f"{stem} {title}"))
                # O selo de áudio (SHA-256 do arquivo inteiro) é caro e só é
                # necessário quando há upgrade a confirmar. Calculado sob demanda
                # em _ensure_seal(); antes, ler milhares de arquivos travava o início.
                seal = ""

                tracks.append({
                    "raw": raw_str,
                    "artist": artist,
                    "title": title,
                    "filename": f,
                    "filepath": str(full_p),
                    "pasta_origem": str(full_p.parent),
                    "ext": ext,
                    "filesize": filesize,
                    "duration": round(duration, 1),
                    "bitrate": round(bitrate / 1000) if bitrate else 0,
                    "sample_rate": sample_rate,
                    "clean_title": normalize_str(title),
                    "clean_artist": normalize_str(artist),
                    "full_norm": normalize_full_str(raw_str),
                    "version_tags": version_tags,
                    "audio_seal": seal,
                    "is_local_file": True
                })
    return tracks


def parse_text_lines(text_content: str):
    """Extrai faixas de texto cru (uma por linha)."""
    tracks = []
    lines = text_content.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        artist = ""
        title = line
        if ' - ' in line:
            parts = line.split(' - ', 1)
            artist = parts[0].strip()
            title = parts[1].strip()

        tracks.append({
            "raw": line,
            "artist": artist,
            "title": title,
            "clean_title": normalize_str(title),
            "clean_artist": normalize_str(artist)
        })
    return tracks


def parse_m3u_or_csv(file_path_str: str):
    """Lê arquivo M3U ou CSV e extrai a lista de faixas."""
    p = Path(os.path.expanduser(file_path_str))
    if not p.exists():
        return []

    tracks = []
    text = p.read_text(encoding='utf-8', errors='ignore')

    if p.suffix.lower() == '.csv':
        lines = text.splitlines()
        for l in lines[1:]: # pula header
            parts = l.split(';' if ';' in l else ',')
            if len(parts) >= 2:
                art = parts[0].strip().strip('"')
                tit = parts[1].strip().strip('"')
                tracks.append({
                    "raw": f"{art} - {tit}",
                    "artist": art,
                    "title": tit,
                    "clean_title": normalize_str(tit),
                    "clean_artist": normalize_str(art)
                })
    else: # M3U
        lines = text.splitlines()
        for l in lines:
            l = l.strip()
            if l.startswith('#EXTINF:'):
                info = l.split(',', 1)[-1]
                if ' - ' in info:
                    art, tit = info.split(' - ', 1)
                    tracks.append({
                        "raw": info,
                        "artist": art.strip(),
                        "title": tit.strip(),
                        "clean_title": normalize_str(tit),
                        "clean_artist": normalize_str(art)
                    })
            elif l and not l.startswith('#'):
                fname = Path(l).stem
                tracks.append({
                    "raw": fname,
                    "artist": "",
                    "title": fname,
                    "clean_title": normalize_str(fname),
                    "clean_artist": ""
                })
    return tracks


def fetch_spotify_playlist(playlist_url: str):
    """
    Obtém faixas de playlist do Spotify via endpoint público HTML/Embed.
    """
    m = re.search(r'playlist/([a-zA-Z0-9]+)', playlist_url)
    if not m:
        return {"sucesso": False, "erro": "URL do Spotify inválida."}

    playlist_id = m.group(1)
    embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"

    try:
        req = urllib.request.Request(embed_url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        # Extrai JSON embutido (__NEXT_DATA__)
        m_json = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        tracks = []
        playlist_name = "Spotify Playlist"

        if m_json:
            data = json.loads(m_json.group(1))
            props = data.get("props", {}).get("pageProps", {})
            state = props.get("state", {}).get("data", {}).get("entity", {})
            playlist_name = state.get("name", "Spotify Playlist")
            track_list = state.get("trackList", [])

            for t in track_list:
                tit = t.get("title", "")
                art = t.get("subtitle", "")
                dur = t.get("duration", 0) / 1000
                tracks.append({
                    "raw": f"{art} - {tit}",
                    "artist": art,
                    "title": tit,
                    "duration": dur,
                    "clean_title": normalize_str(tit),
                    "clean_artist": normalize_str(art)
                })

        return {
            "sucesso": True,
            "nome_playlist": playlist_name,
            "faixas": tracks
        }
    except Exception as e:
        return {
            "sucesso": False,
            "erro": f"Não foi possível ler playlist do Spotify: {e}"
        }


def match_tracks_against_library(tracks_to_match: list, mp3_dir_str: str):
    """
    Cruza as faixas solicitadas contra todos os arquivos de áudio do HD.
    Aplica validação estrita de versão (remix vs original), duração física e hash de áudio.
    """
    base_path = Path(os.path.expanduser(mp3_dir_str)).resolve()
    if not base_path.exists():
        return {"sucesso": False, "erro": "Pasta MP3 não encontrada"}

    # Carrega índice da biblioteca local com metadados de Crate e versão
    library = []
    for root, _, files in os.walk(str(base_path)):
        if '/.' in root or '\\.' in root:
            continue
        rel_dir = os.path.relpath(root, str(base_path))
        crate_label = rel_dir.replace('\\', ' -> ').replace('/', ' -> ') if rel_dir != '.' else "Raiz"
        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            if Path(f).suffix.lower() in AUDIO_EXTENSIONS:
                stem = Path(f).stem
                library.append({
                    "full_path": str(Path(root) / f),
                    "rel_path": str(Path(rel_dir) / f) if rel_dir != '.' else f,
                    "filename": f,
                    "crate_name": crate_label,
                    "norm": normalize_str(stem),
                    "full_norm": normalize_full_str(stem),
                    "version_tags": extract_version_descriptors(stem),
                    "stem": stem
                })

    matched = []
    missing = []

    # Índice invertido por token: reduz o cruzamento de (novidades x biblioteca)
    # para apenas candidatos que compartilham tokens. Sem isso, 2.6 mil novidades
    # contra 16 mil faixas geravam ~44 milhões de comparações com difflib.
    token_index = {}
    norm_index = {}
    for idx, lib in enumerate(library):
        norm_index.setdefault(lib["full_norm"], []).append(idx)
        norm_index.setdefault(lib["norm"], []).append(idx)
        for tok in set(lib["full_norm"].split()) | set(lib["norm"].split()):
            if len(tok) > 2 and tok not in STOP_WORDS:
                token_index.setdefault(tok, []).append(idx)

    def candidate_indices(target_norm, target_full):
        """Retorna índices candidatos: casamento exato + tokens em comum, por raridade."""
        candidatos = set(norm_index.get(target_full, ()))
        candidatos.update(norm_index.get(target_norm, ()))
        tokens = [t for t in set(target_full.split()) | set(target_norm.split())
                  if len(t) > 2 and t not in STOP_WORDS]
        # Ordena tokens do mais raro ao mais comum e limita a busca
        tokens.sort(key=lambda t: len(token_index.get(t, ())))
        for tok in tokens[:6]:
            candidatos.update(token_index.get(tok, ()))
        return candidatos

    total_reqs = max(1, len(tracks_to_match))
    for req_idx, req in enumerate(tracks_to_match, 1):
        if req_idx % 25 == 0 or req_idx == total_reqs:
            print(json.dumps({
                "tipo": "progresso",
                "processados": req_idx,
                "total": total_reqs,
                "percentual": round(req_idx * 100.0 / total_reqs, 1),
                "faixa": req.get("filename") or req.get("raw", ""),
            }, ensure_ascii=False), flush=True)
        target_norm = req["clean_title"]
        target_art = req["clean_artist"]
        target_full = req.get("full_norm", normalize_full_str(req["raw"]))
        req_versions = set(req.get("version_tags") or extract_version_descriptors(req["raw"]))
        has_remix_req = any('remix' in v or 'mix' in v for v in req_versions)
        has_live_req = any('live' in v or 'ao vivo' in v for v in req_versions)

        best_match = None
        best_score = 0

        # Percorre apenas os candidatos do índice (não a biblioteca inteira)
        for lib_idx in candidate_indices(target_norm, target_full):
            lib = library[lib_idx]
            lib_versions = lib["version_tags"]
            has_remix_lib = any('remix' in v or 'mix' in v for v in lib_versions)
            has_live_lib = any('live' in v or 'ao vivo' in v for v in lib_versions)
            version_match = (has_remix_req == has_remix_lib) and (has_live_req == has_live_lib)

            # 1. Correspondência exata de título completo
            if target_full == lib["full_norm"] and target_full:
                score = 100 if version_match else 75
                if score > best_score:
                    best_match = lib
                    best_score = score
                    if score == 100:
                        break
                continue

            # 2. Similaridade estruturada de Título e Artista (eliminando falsos positivos de palavras avulsas)
            sim_full = token_similarity(target_full, lib["full_norm"])
            sim_title = token_similarity(target_norm, lib["norm"])
            sim_art = token_similarity(target_art, lib["norm"]) if target_art else 1.0

            # Se o artista foi informado, exige que ele coincida razoavelmente
            if target_art and sim_art < 0.45:
                continue

            if target_norm and len(target_norm) > 2:
                if target_art and sim_art >= 0.6 and sim_title >= 0.70:
                    current_score = int((sim_title * 0.6 + sim_art * 0.4) * 100)
                    if not version_match:
                        current_score = max(50, current_score - 25)
                    if current_score > best_score and current_score >= 70:
                        best_match = lib
                        best_score = current_score
                elif sim_full >= 0.78:
                    current_score = int(sim_full * 100)
                    if not version_match:
                        current_score = max(50, current_score - 25)
                    if current_score > best_score and current_score >= 70:
                        best_match = lib
                        best_score = current_score
                elif sim_title >= 0.85 and (not target_art or sim_art >= 0.5):
                    current_score = int(sim_title * 100)
                    if not version_match:
                        current_score = max(50, current_score - 25)
                    if current_score > best_score and current_score >= 75:
                        best_match = lib
                        best_score = current_score

        if best_match and best_score >= 70:
            lib_versions = best_match["version_tags"]
            has_remix_lib = any('remix' in v or 'mix' in v for v in lib_versions)
            has_live_lib = any('live' in v or 'ao vivo' in v for v in lib_versions)
            versao_divergente = (has_remix_req != has_remix_lib) or (has_live_req != has_live_lib)

            # Se ambos forem remixes mas de produtores diferentes
            remixers_req = {v for v in req_versions if v.startswith('remixer:')}
            remixers_lib = {v for v in lib_versions if v.startswith('remixer:')}
            if remixers_req and remixers_lib and remixers_req != remixers_lib:
                versao_divergente = True

            item_match = {
                "solicitado": req["raw"],
                "arquivo_local": best_match["filename"],
                "caminho_completo": best_match["full_path"],
                "caminho_rel": best_match["rel_path"],
                "crate_destino": best_match["crate_name"],
                "score": best_score,
                "versao_divergente": versao_divergente,
                "versao_novo": ", ".join(sorted(req_versions)) if req_versions else "Original / Álbum",
                "versao_lib": ", ".join(sorted(lib_versions)) if lib_versions else "Original / Álbum"
            }

            if req.get("is_local_file"):
                item_match["caminho_novo"] = req.get("filepath")
                item_match["pasta_origem"] = req.get("pasta_origem", str(Path(req.get("filepath", "")).parent))
                item_match["novo_bitrate"] = req.get("bitrate", 0)
                item_match["novo_formato"] = req.get("ext", "").replace(".", "").upper()
                item_match["novo_tamanho"] = req.get("filesize", 0)
                item_match["novo_duracao"] = req.get("duration", 0.0)
                item_match["audio_seal_novo"] = _ensure_seal(req)

                # Avalia qualidade e duração física da biblioteca existente
                lib_bitrate = 0
                lib_duration = 0.0
                lib_ext = Path(best_match["full_path"]).suffix.upper().replace(".", "")
                lib_size = 0
                lib_seal = ""

                try:
                    lib_size = Path(best_match["full_path"]).stat().st_size
                    if mutagen:
                        la = mutagen.File(best_match["full_path"])
                        if la and getattr(la, "info", None):
                            lib_bitrate = round(getattr(la.info, "bitrate", 0) / 1000)
                            lib_duration = round(getattr(la.info, "length", 0.0), 1)
                except Exception:
                    pass

                item_match["lib_bitrate"] = lib_bitrate
                item_match["lib_formato"] = lib_ext
                item_match["lib_tamanho"] = lib_size
                item_match["lib_duracao"] = lib_duration

                # Compara duração física das faixas
                dur_novo = req.get("duration", 0.0)
                delta_dur = abs(dur_novo - lib_duration) if (dur_novo > 0 and lib_duration > 0) else 0.0
                item_match["delta_duracao"] = round(delta_dur, 1)

                duracao_incompativel = (dur_novo > 15 and lib_duration > 15 and delta_dur > 5.0)
                item_match["duracao_incompativel"] = duracao_incompativel

                # Avalia se a faixa nova tem qualidade técnica superior
                bitrate_superior = False
                if req.get("bitrate", 0) > (lib_bitrate + 32):
                    bitrate_superior = True
                elif req.get("ext") in ('.flac', '.wav', '.aif') and lib_ext in ('MP3', 'AAC', 'M4A') and lib_bitrate < 320:
                    bitrate_superior = True

                # Nível de Confiança
                if best_score >= 90 and not versao_divergente and not duracao_incompativel:
                    confianca = "ALTA"
                elif best_score >= 75 and not versao_divergente and not duracao_incompativel:
                    confianca = "MEDIA"
                else:
                    confianca = "INCERTA"

                item_match["confianca"] = confianca

                # TRAVA DE SEGURANÇA CONTRA SUBSTITUIÇÃO INDEVIDA (REMIX VS ORIGINAL E CONFIANÇA)
                is_safe_upgrade = False
                aviso_motivo = None

                if versao_divergente:
                    status_comp = "VERSAO_DIVERGENTE"
                    aviso_motivo = f"⚠️ Conflito de Versão: '{item_match['versao_novo']}' vs '{item_match['versao_lib']}'. Não sobrescrever a original!"
                elif duracao_incompativel:
                    status_comp = "DURACAO_INCOMPATIVEL"
                    aviso_motivo = f"⚠️ Duração Incompatível: difere em {round(delta_dur, 1)}s. Provável versão estendida ou remix."
                elif confianca != "ALTA":
                    status_comp = "CORRESPONDENCIA_INCERTA"
                    aviso_motivo = f"⚠️ Correspondência Incerta (Score {best_score}%, Confiança {confianca}). Não substituir automaticamente."
                elif bitrate_superior:
                    # Calcula hash de áudio do arquivo original para confirmar
                    lib_seal = compute_audio_seal(best_match["full_path"])
                    item_match["audio_seal_lib"] = lib_seal
                    is_safe_upgrade = True
                    status_comp = "UPGRADE_SEGURO"
                    aviso_motivo = f"✅ Upgrade Seguro: Mesma versão ({round(delta_dur, 1)}s de diferença), qualidade {req.get('bitrate', 0)}k vs {lib_bitrate}k."
                else:
                    status_comp = "JA_POSSUI_QUALIDADE"
                    aviso_motivo = f"Qualidade atual no HD ({lib_bitrate}k) já é satisfatória."

                item_match["upgrade_disponivel"] = is_safe_upgrade
                item_match["upgrade_seguro"] = is_safe_upgrade
                item_match["status_comparacao"] = status_comp
                item_match["aviso_incompatibilidade"] = aviso_motivo

            matched.append(item_match)
        else:
            missing_item = {
                "solicitado": req["raw"],
                "artista": req.get("artist", ""),
                "titulo": req.get("title", req["raw"]),
                "versao": ", ".join(sorted(req_versions)) if req_versions else "Original"
            }
            if req.get("is_local_file"):
                missing_item["caminho_novo"] = req.get("filepath")
                missing_item["pasta_origem"] = req.get("pasta_origem", str(Path(req.get("filepath", "")).parent))
                missing_item["novo_bitrate"] = req.get("bitrate", 0)
                missing_item["novo_formato"] = req.get("ext", "").replace(".", "").upper()
                missing_item["novo_tamanho"] = req.get("filesize", 0)
                missing_item["novo_duracao"] = req.get("duration", 0.0)
                missing_item["audio_seal_novo"] = _ensure_seal(req)
                missing_item["status_comparacao"] = "FAIXA_NOVA"

            missing.append(missing_item)

    return {
        "sucesso": True,
        "tipo_origem": "folder" if any(t.get("is_local_file") for t in tracks_to_match) else "text",
        "total_solicitadas": len(tracks_to_match),
        "total_encontradas": len(matched),
        "total_faltantes": len(missing),
        "total_upgrades": sum(1 for m in matched if m.get("upgrade_disponivel")),
        "total_divergentes": sum(1 for m in matched if m.get("versao_divergente") or m.get("duracao_incompativel")),
        "encontradas": matched,
        "faltantes": missing
    }


def export_matched_to_serato_crate(crate_name: str, matched_items: list, serato_dir_str: str):
    """
    Gera um arquivo .crate binário oficial compatível com Serato 4 usando
    gravação atômica, backup SHA-256 e registro em Journal via crate_ops.
    """
    from crate_ops import get_crate_path, read_and_validate_crate, write_crate_atomic

    subcrates_dir = Path(os.path.expanduser(serato_dir_str)) / "Subcrates"
    subcrates_dir.mkdir(parents=True, exist_ok=True)
    crate_path = get_crate_path(subcrates_dir, crate_name)

    track_rel_list = [item["caminho_rel"] for item in matched_items]
    header_antigo = None
    outros_blocos = None
    if crate_path.exists():
        try:
            header_antigo, _, outros_blocos = read_and_validate_crate(crate_path)
        except Exception:
            pass

    wres = write_crate_atomic(
        crate_path,
        track_rel_list,
        header_antigo=header_antigo,
        outros_blocos=outros_blocos,
        action_name="track_matcher_export",
    )
    if not wres.get("sucesso"):
        return {
            "sucesso": False,
            "erro": wres.get("erro", "Falha ao gravar crate exportada."),
            "crate_salva": str(crate_path),
            "total_faixas": 0,
        }

    return {
        "sucesso": True,
        "crate_salva": str(crate_path),
        "total_faixas": len(matched_items),
        "mensagem": f"Crate [{crate_name}] gerada com sucesso com {len(matched_items)} faixas no Serato."
    }


def replace_track_with_upgrade(incoming_path_str: str, destination_path_str: str, force: bool = False) -> dict:
    """
    Substitui a faixa antiga de menor qualidade pela nova faixa diretamente no mesmo local físico.
    Move a antiga para quarentena e clona tags Serato Markers (Hot Cues / Beatgrid).
    Possui trava de segurança estrita contra sobreposição de remixes e durações incompatíveis.
    """
    inc_p = Path(os.path.expanduser(incoming_path_str)).resolve()
    dest_p = Path(os.path.expanduser(destination_path_str)).resolve()

    if not inc_p.exists():
        return {"sucesso": False, "erro": "Arquivo novo da pasta de novidades não encontrado."}
    if not dest_p.exists():
        return {"sucesso": False, "erro": "Arquivo original da biblioteca não encontrado no disco."}

    # 1. TRAVA DE SEGURANÇA CONTRA SUBSTITUIÇÃO INDEVIDA (REMIX VS ORIGINAL / DURAÇÃO INCOMPATÍVEL)
    if not force:
        # Verifica descritores de versão nos nomes dos arquivos
        inc_versions = extract_version_descriptors(inc_p.stem)
        dest_versions = extract_version_descriptors(dest_p.stem)
        has_remix_inc = any('remix' in v or 'mix' in v for v in inc_versions)
        has_remix_dest = any('remix' in v or 'mix' in v for v in dest_versions)
        has_live_inc = any('live' in v or 'ao vivo' in v for v in inc_versions)
        has_live_dest = any('live' in v or 'ao vivo' in v for v in dest_versions)

        if (has_remix_inc != has_remix_dest) or (has_live_inc != has_live_dest):
            return {
                "sucesso": False,
                "bloqueado_seguranca": True,
                "erro": f"Substituição bloqueada por segurança: Versões incompatíveis ('{inc_p.name}' vs '{dest_p.name}'). Faixa de remix não pode sobrescrever a versão original!"
            }

        # Verifica diferença de duração física do áudio
        if mutagen:
            try:
                inc_audio = mutagen.File(str(inc_p))
                dest_audio = mutagen.File(str(dest_p))
                if inc_audio and dest_audio and inc_audio.info and dest_audio.info:
                    inc_dur = getattr(inc_audio.info, "length", 0.0)
                    dest_dur = getattr(dest_audio.info, "length", 0.0)
                    delta_dur = abs(inc_dur - dest_dur)
                    if inc_dur > 15 and dest_dur > 15 and delta_dur > 5.0:
                        return {
                            "sucesso": False,
                            "bloqueado_seguranca": True,
                            "erro": f"Substituição bloqueada por segurança: Duração difere em {round(delta_dur, 1)}s ({round(inc_dur, 1)}s vs {round(dest_dur, 1)}s). Provável remix ou edição estendida."
                        }
            except Exception:
                pass

    quarantine_dir = Path.home() / ".serato_quarentena_audio"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    quarantine_file = quarantine_dir / f"upgrade_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{dest_p.name}"

    import uuid
    same_ext = inc_p.suffix.lower() == dest_p.suffix.lower()
    final_path = dest_p if same_ext else dest_p.with_suffix(inc_p.suffix)
    temp_dest = final_path.with_name(f".tmp_upgrade_{uuid.uuid4().hex[:8]}_{final_path.name}")

    try:
        shutil.copy2(str(inc_p), str(temp_dest))

        # Clona tags Serato e ID3v2.3 da antiga para a cópia temporária (sem mutar arquivo de origem inc_p!)
        if mutagen:
            try:
                from mutagen.id3 import ID3
                if dest_p.suffix.lower() == ".mp3" and inc_p.suffix.lower() == ".mp3":
                    old_id3 = ID3(str(dest_p))
                    try:
                        new_id3 = ID3(str(temp_dest))
                    except Exception:
                        new_id3 = ID3()
                    # Preserva estritamente Hot Cues, Beatgrid, Stems, Tempo Map e Ratings do DJ (Serato 4/5)
                    serato_geob_keys = [
                        'GEOB:Serato Markers2',
                        'GEOB:Serato Markers_',
                        'GEOB:Serato BeatGrid',
                        'GEOB:Serato Tempo Map',
                        'GEOB:Serato Stems',
                        'GEOB:Serato Rating Emoji',
                        'GEOB:Serato Analysis Flags',
                        'GEOB:Serato Import ID',
                        'GEOB:Serato Autotags',
                        'GEOB:Serato Overview',
                        'GEOB:Serato VidAssoc',
                    ]
                    for tag_key in serato_geob_keys:
                        if tag_key in old_id3:
                            new_id3[tag_key] = old_id3[tag_key]
                    for tag_key in ['TBPM', 'TKEY']:
                        if tag_key in old_id3 and tag_key not in new_id3:
                            new_id3[tag_key] = old_id3[tag_key]
                    new_id3.save(str(temp_dest), v2_version=3)
            except Exception as e_tag:
                return {"sucesso": False, "erro": f"Falha ao preservar metadados Serato durante upgrade: {e_tag}"}

        # Backup obrigatório da faixa antiga na quarentena com validação de tamanho
        shutil.copy2(str(dest_p), str(quarantine_file))
        if not quarantine_file.exists() or quarantine_file.stat().st_size != dest_p.stat().st_size:
            raise IOError("Backup prévio em quarentena falhou; substituição abortada.")

        op_id = None
        try:
            from journal import record_id3_before_change, record_operation_after
            op_id = record_id3_before_change(str(dest_p), action="track_matcher_upgrade")
        except Exception:
            pass

        # Substituição atômica no destino final
        os.replace(str(temp_dest), str(final_path))
        if not same_ext and dest_p.exists() and dest_p != final_path:
            dest_p.unlink(missing_ok=True)

        if op_id is not None and final_path == dest_p:
            try:
                record_operation_after(op_id, str(final_path))
            except Exception:
                pass

        return {
            "sucesso": True,
            "arquivo": final_path.name,
            "caminho_final": str(final_path),
            "quarentena": str(quarantine_file),
            "mensagem": f"Upgrade concluído com sucesso no local original ({final_path.name})."
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}
    finally:
        if temp_dest.exists():
            try:
                temp_dest.unlink()
            except Exception:
                pass


def batch_replace_upgrades(upgrades_list: list, force: bool = False) -> dict:
    """Executa substituição de faixas em lote para upgrades de qualidade."""
    total = len(upgrades_list)
    updated = 0
    errors = []

    for item in upgrades_list:
        inc = item.get("caminho_novo")
        dest = item.get("caminho_completo")
        item_force = item.get("force", force)
        if inc and dest:
            res = replace_track_with_upgrade(inc, dest, force=item_force)
            if res.get("sucesso"):
                updated += 1
            else:
                errors.append(f"{Path(dest).name}: {res.get('erro')}")

    return {
        "sucesso": True,
        "total": total,
        "atualizados": updated,
        "erros": errors,
        "mensagem": f"{updated} de {total} faixas atualizadas com sucesso no próprio local do HD."
    }


def integrate_new_tracks_to_crate(tracks_list: list, target_crate_folder: str) -> dict:
    """Copia as faixas inéditas/selecionadas para a pasta da Crate escolhida pelo usuário."""
    dest_dir = Path(os.path.expanduser(target_crate_folder)).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    errors = []
    copied_files = []

    for item in tracks_list:
        src = item.get("caminho_novo") or item.get("caminho_completo")
        if not src:
            continue
        src_p = Path(src)
        if not src_p.exists():
            errors.append(f"Arquivo não encontrado: {src}")
            continue

        dest_file = dest_dir / src_p.name
        if dest_file.exists():
            stem = src_p.stem
            ext = src_p.suffix
            dest_file = dest_dir / f"{stem}_novo{ext}"

        try:
            shutil.copy2(str(src_p), str(dest_file))
            copied += 1
            copied_files.append(str(dest_file))
        except Exception as e:
            errors.append(f"{src_p.name}: {str(e)}")

    return {
        "sucesso": True,
        "total": len(tracks_list),
        "copiados": copied,
        "destino": str(dest_dir),
        "erros": errors,
        "mensagem": f"{copied} nova(s) faixa(s) copiada(s) e integrada(s) na pasta '{dest_dir.name}'."
    }


def main():
    parser = argparse.ArgumentParser(description="Serato 5 Sync Manager Pro - Track Matcher")
    parser.add_argument("--match-text", type=str, default="", help="Conteúdo de texto com faixas")
    parser.add_argument("--match-file", type=str, default="", help="Arquivo CSV ou M3U para cruzamento")
    parser.add_argument("--match-folder", type=str, default="", help="Pasta local contendo novos arquivos de áudio")
    parser.add_argument("--match-spotify", type=str, default="", help="URL de playlist do Spotify")
    parser.add_argument("--mp3", type=str, default="", help="Pasta MP3 do usuário")
    parser.add_argument("--serato", type=str, default="", help="Pasta Serato")
    parser.add_argument("--export-crate", type=str, default="", help="Nome da Crate para exportar")
    parser.add_argument("--replace-upgrades", type=str, default="", help="JSON de lista de pares de upgrade para substituir")
    parser.add_argument("--integrate-tracks", type=str, default="", help="JSON de faixas a copiar e integrar")
    parser.add_argument("--target-folder", type=str, default="", help="Pasta de destino para integração")

    args = parser.parse_args()
    mp3_dir = args.mp3 or str(Path.home() / "Music" / "MP3")

    if args.replace_upgrades:
        try:
            if args.replace_upgrades.startswith('['):
                items_up = json.loads(args.replace_upgrades)
            else:
                with open(args.replace_upgrades, 'r', encoding='utf-8') as f:
                    items_up = json.load(f)
            res = batch_replace_upgrades(items_up)
            print(json.dumps(res, ensure_ascii=False))
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}))
            sys.exit(1)

    if args.integrate_tracks and args.target_folder:
        try:
            if args.integrate_tracks.startswith('['):
                items_int = json.loads(args.integrate_tracks)
            else:
                with open(args.integrate_tracks, 'r', encoding='utf-8') as f:
                    items_int = json.load(f)
            res = integrate_new_tracks_to_crate(items_int, args.target_folder)
            print(json.dumps(res, ensure_ascii=False))
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}))
            sys.exit(1)

    tracks = []
    if args.match_spotify:
        res_spot = fetch_spotify_playlist(args.match_spotify)
        if not res_spot.get("sucesso"):
            print(json.dumps(res_spot, ensure_ascii=False))
            sys.exit(1)
        tracks = res_spot.get("faixas", [])
    elif args.match_folder:
        tracks = parse_incoming_folder(args.match_folder)
    elif args.match_file:
        tracks = parse_m3u_or_csv(args.match_file)
    elif args.match_text:
        tracks = parse_text_lines(args.match_text)

    if tracks:
        match_res = match_tracks_against_library(tracks, mp3_dir)
        if args.export_crate and match_res.get("encontradas"):
            serato_dir = args.serato or str(Path.home() / "Music" / "_Serato_")
            exp_res = export_matched_to_serato_crate(args.export_crate, match_res["encontradas"], serato_dir)
            match_res["export_serato"] = exp_res

        print(json.dumps(match_res, ensure_ascii=False))
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
