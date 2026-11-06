#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - TRACK MATCHER ENGINE (track_matcher.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Cruzamento de playlists (Spotify, YouTube Music, M3U, CSV ou Texto) contra as
31.355 faixas do HD, gerando crates prontas para o Serato DJ Pro 4.
================================================================================
"""

import sys
import os
import re
import json
import shutil
import sqlite3
import argparse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import mutagen
except ImportError:
    mutagen = None

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

DB_PATH = Path.home() / ".serato_sound_seals.sqlite"
AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')


def normalize_str(s: str) -> str:
    """Normaliza texto para comparação fonética/fuzzy."""
    s = s.lower()
    s = re.sub(r'[\(\[\{].*?[\)\]\}]', '', s) # remove parenteses
    s = re.sub(r'[^\w\s]', '', s) # remove pontuações
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

                tracks.append({
                    "raw": f"{artist} - {title}" if artist else stem,
                    "artist": artist,
                    "title": title,
                    "filename": f,
                    "filepath": str(full_p),
                    "ext": ext,
                    "filesize": filesize,
                    "duration": round(duration, 1),
                    "bitrate": round(bitrate / 1000) if bitrate else 0,
                    "sample_rate": sample_rate,
                    "clean_title": normalize_str(title),
                    "clean_artist": normalize_str(artist),
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
    """
    base_path = Path(os.path.expanduser(mp3_dir_str)).resolve()
    if not base_path.exists():
        return {"sucesso": False, "erro": "Pasta MP3 não encontrada"}

    # Carrega índice da biblioteca local
    library = []
    for root, _, files in os.walk(str(base_path)):
        if '/.' in root or '\\.' in root:
            continue
        rel_dir = os.path.relpath(root, str(base_path))
        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            if Path(f).suffix.lower() in AUDIO_EXTENSIONS:
                stem = Path(f).stem
                library.append({
                    "full_path": str(Path(root) / f),
                    "rel_path": str(Path(rel_dir) / f) if rel_dir != '.' else f,
                    "filename": f,
                    "norm": normalize_str(stem),
                    "stem": stem
                })

    matched = []
    missing = []

    for req in tracks_to_match:
        target_norm = req["clean_title"]
        target_art = req["clean_artist"]
        best_match = None
        best_score = 0

        for lib in library:
            # 1. Match exato
            if target_norm in lib["norm"] and (not target_art or target_art in lib["norm"]):
                best_match = lib
                best_score = 100
                break
            # 2. Match de título
            elif target_norm and target_norm in lib["norm"]:
                if best_score < 80:
                    best_match = lib
                    best_score = 80

        if best_match:
            item_match = {
                "solicitado": req["raw"],
                "arquivo_local": best_match["filename"],
                "caminho_completo": best_match["full_path"],
                "caminho_rel": best_match["rel_path"],
                "score": best_score
            }

            if req.get("is_local_file"):
                item_match["caminho_novo"] = req.get("filepath")
                item_match["novo_bitrate"] = req.get("bitrate", 0)
                item_match["novo_formato"] = req.get("ext", "").replace(".", "").upper()
                item_match["novo_tamanho"] = req.get("filesize", 0)

                # Avalia qualidade da biblioteca existente
                lib_bitrate = 0
                lib_ext = Path(best_match["full_path"]).suffix.upper().replace(".", "")
                lib_size = 0
                try:
                    lib_size = Path(best_match["full_path"]).stat().st_size
                    if mutagen:
                        la = mutagen.File(best_match["full_path"])
                        if la and getattr(la, "info", None):
                            lib_bitrate = round(getattr(la.info, "bitrate", 0) / 1000)
                except Exception:
                    pass

                item_match["lib_bitrate"] = lib_bitrate
                item_match["lib_formato"] = lib_ext
                item_match["lib_tamanho"] = lib_size

                # Upgrade se novo bitrate for superior em pelo menos 32k ou formato superior
                is_upgrade = False
                if req.get("bitrate", 0) > (lib_bitrate + 32):
                    is_upgrade = True
                elif req.get("ext") in ('.flac', '.wav', '.aif') and lib_ext in ('MP3', 'AAC', 'M4A') and lib_bitrate < 320:
                    is_upgrade = True

                item_match["upgrade_disponivel"] = is_upgrade
                item_match["status_comparacao"] = "UPGRADE_DISPONIVEL" if is_upgrade else "JA_POSSUI_QUALIDADE"

            matched.append(item_match)
        else:
            missing_item = {
                "solicitado": req["raw"],
                "artista": req.get("artist", ""),
                "titulo": req.get("title", req["raw"])
            }
            if req.get("is_local_file"):
                missing_item["caminho_novo"] = req.get("filepath")
                missing_item["novo_bitrate"] = req.get("bitrate", 0)
                missing_item["novo_formato"] = req.get("ext", "").replace(".", "").upper()
                missing_item["novo_tamanho"] = req.get("filesize", 0)
                missing_item["status_comparacao"] = "FAIXA_NOVA"

            missing.append(missing_item)

    return {
        "sucesso": True,
        "tipo_origem": "folder" if any(t.get("is_local_file") for t in tracks_to_match) else "text",
        "total_solicitadas": len(tracks_to_match),
        "total_encontradas": len(matched),
        "total_faltantes": len(missing),
        "total_upgrades": sum(1 for m in matched if m.get("upgrade_disponivel")),
        "encontradas": matched,
        "faltantes": missing
    }


def export_matched_to_serato_crate(crate_name: str, matched_items: list, serato_dir_str: str):
    """
    Gera um arquivo .crate binário oficial compatível com Serato 4 contendo as faixas encontradas.
    """
    subcrates_dir = Path(os.path.expanduser(serato_dir_str)) / "Subcrates"
    subcrates_dir.mkdir(parents=True, exist_ok=True)

    safe_name = crate_name.replace('/', '%%').replace('\\', '%%')
    if not safe_name.endswith('.crate'):
        safe_name += '.crate'

    crate_path = subcrates_dir / safe_name

    # Header oficial do Serato
    header = b'vrsn\x00\x00\x00\x081.0/Serato ScratchLive Crate'
    track_entries = bytearray()

    for item in matched_items:
        rel_path = item["caminho_rel"]
        # Serato usa UTF-16-BE sem BOM para ptrk
        encoded_path = rel_path.encode('utf-16-be')
        size_bytes = len(encoded_path).to_bytes(4, byteorder='big')

        track_block = bytearray()
        track_block.extend(b'otrk')
        inner_content = bytearray(b'ptrk')
        inner_content.extend(size_bytes)
        inner_content.extend(encoded_path)
        track_block.extend(len(inner_content).to_bytes(4, byteorder='big'))
        track_block.extend(inner_content)

        track_entries.extend(track_block)

    with open(crate_path, 'wb') as f:
        f.write(header)
        f.write(track_entries)

    return {
        "sucesso": True,
        "crate_salva": str(crate_path),
        "total_faixas": len(matched_items),
        "mensagem": f"Crate [{crate_name}] gerada com sucesso com {len(matched_items)} faixas no Serato."
    }


def replace_track_with_upgrade(incoming_path_str: str, destination_path_str: str) -> dict:
    """
    Substitui a faixa antiga de menor qualidade pela nova faixa diretamente no mesmo local físico.
    Move a antiga para quarentena e clona tags Serato Markers (Hot Cues / Beatgrid).
    """
    inc_p = Path(os.path.expanduser(incoming_path_str)).resolve()
    dest_p = Path(os.path.expanduser(destination_path_str)).resolve()

    if not inc_p.exists():
        return {"sucesso": False, "erro": "Arquivo novo da pasta de novidades não encontrado."}
    if not dest_p.exists():
        return {"sucesso": False, "erro": "Arquivo original da biblioteca não encontrado no disco."}

    quarantine_dir = Path.home() / ".serato_quarentena_audio"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    quarantine_file = quarantine_dir / f"upgrade_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{dest_p.name}"

    try:
        # Clona tags Serato e ID3v2.3 da antiga para a nova antes de sobrescrever
        try:
            if mutagen:
                from mutagen.id3 import ID3
                old_id3 = ID3(str(dest_p))
                new_id3 = ID3(str(inc_p))
                for tag_key in ['GEOB:Serato Markers2', 'GEOB:Serato BeatGrid', 'TBPM', 'TKEY']:
                    if tag_key in old_id3 and tag_key not in new_id3:
                        new_id3[tag_key] = old_id3[tag_key]
                new_id3.save(v2_version=3)
        except Exception:
            pass

        # Backup da antiga na quarentena
        shutil.copy2(str(dest_p), str(quarantine_file))

        # Sobrescreve no local exato da biblioteca
        if inc_p.suffix.lower() == dest_p.suffix.lower():
            shutil.copy2(str(inc_p), str(dest_p))
            final_path = dest_p
        else:
            new_target = dest_p.with_suffix(inc_p.suffix)
            shutil.copy2(str(inc_p), str(new_target))
            dest_p.unlink(missing_ok=True)
            final_path = new_target

        return {
            "sucesso": True,
            "arquivo": final_path.name,
            "caminho_final": str(final_path),
            "quarentena": str(quarantine_file),
            "mensagem": f"Upgrade concluído com sucesso no local original ({final_path.name})."
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def batch_replace_upgrades(upgrades_list: list) -> dict:
    """Executa substituição de faixas em lote para upgrades de qualidade."""
    total = len(upgrades_list)
    updated = 0
    errors = []

    for item in upgrades_list:
        inc = item.get("caminho_novo")
        dest = item.get("caminho_completo")
        if inc and dest:
            res = replace_track_with_upgrade(inc, dest)
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
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Track Matcher")
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
    mp3_dir = args.mp3 or "/Volumes/Pastteyr/Music/MP3"

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
            serato_dir = args.serato or "/Volumes/Pastteyr/Serato"
            exp_res = export_matched_to_serato_crate(args.export_crate, match_res["encontradas"], serato_dir)
            match_res["export_serato"] = exp_res

        print(json.dumps(match_res, ensure_ascii=False))
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
