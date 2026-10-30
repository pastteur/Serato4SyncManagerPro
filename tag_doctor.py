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
import argparse
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

# Padrões comuns de sujeira em downloads e pacotes da web
NOISE_PATTERNS = [
    re.compile(r'\(www\.[a-z0-9\-_\.]+\.[a-z]{2,}\)', re.IGNORECASE),
    re.compile(r'\[www\.[a-z0-9\-_\.]+\.[a-z]{2,}\]', re.IGNORECASE),
    re.compile(r'www\.[a-z0-9\-_\.]+\.[a-z]{2,}', re.IGNORECASE),
    re.compile(r'\[dj\s*pool\]', re.IGNORECASE),
    re.compile(r'\(dj\s*pool\)', re.IGNORECASE),
    re.compile(r'\[exclusive\]', re.IGNORECASE),
    re.compile(r'\[megapack\]', re.IGNORECASE),
    re.compile(r'\[\d{3}\s*kbps\]', re.IGNORECASE),
    re.compile(r'\(\d{3}\s*kbps\)', re.IGNORECASE),
    re.compile(r'_\-_'),
    re.compile(r'-\s*-'),
]

# Padrão de BPM/Key no final do nome: ex: " . 80 . Fm", " . 128 . Am", " . 96 . C#"
TRAILING_BPM_KEY = re.compile(r'\s*\.\s*\d{2,3}(?:\.\d+)?\s*\.\s*[A-G][b#]?(?:m|maj|min)?\s*$', re.IGNORECASE)
TRAILING_DOTS = re.compile(r'[\s\._]+$')
LEADING_TRACK_NUM = re.compile(r'^\d{1,3}\s*[-–.]\s*')


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
    e detecta Crate Raiz (ex: Axé, Funk, Sertanejo, EMusic) e Álbum.
    """
    text = filename_no_ext

    # 1. Remove URLs e sujeiras de download (sem tocar em Remix, feat, etc.)
    for pattern in NOISE_PATTERNS:
        text = pattern.sub('', text)

    # 2. Extrai e remove cauda de BPM/Key (ex: " . 80 . Fm", " . 130 . Dm")
    detected_bpm = ""
    detected_key = ""
    bpm_key_match = TRAILING_BPM_KEY.search(text)
    if bpm_key_match:
        part = bpm_key_match.group(0).strip(" .")
        subparts = [p.strip() for p in part.split('.') if p.strip()]
        if len(subparts) >= 2:
            detected_bpm = subparts[0]
            detected_key = subparts[1]
        text = TRAILING_BPM_KEY.sub('', text)

    # 3. Remove numeração de faixa inicial se houver (ex: "01 - ")
    text = LEADING_TRACK_NUM.sub('', text)

    # 4. Remove pontos ou traços residuais no final (ex: " . .")
    text = TRAILING_DOTS.sub('', text)

    # 5. Normaliza underscores e múltiplos espaços
    text = text.replace('_', ' ')
    text = re.sub(r'\s+', ' ', text).strip()

    # Identificação da Crate Raiz e Hierarquia
    folder_parts = [p for p in rel_folder.replace('\\', '/').split('/') if p]
    crate_raiz = folder_parts[0] if folder_parts else ""
    crate_completa = " -> ".join(folder_parts) if folder_parts else ""

    # Separação Inteligente: Artista - Título (Versão/Remix) - Álbum
    artist = existing_artist.strip() if existing_artist else ""
    title = existing_title.strip() if existing_title else ""
    album = existing_album.strip() if existing_album else ""

    parts = text.split(" - ")
    if len(parts) >= 3:
        p_art = parts[0].strip()
        p_tit = parts[1].strip()
        p_alb = parts[2].strip()
        if not artist: artist = p_art
        if not title: title = p_tit
        if not album: album = p_alb
    elif len(parts) == 2:
        p_art = parts[0].strip()
        p_tit = parts[1].strip()
        if not artist: artist = p_art
        if not title: title = p_tit
    else:
        if not title:
            title = text

    # Se existing_title era básico mas o filename possui versão/remix detalhado, prefere a versão rica!
    # Ex: existing_title="É o amor" e filename="Araketo - É o amor (Bahia Mix)" -> title="É o amor (Bahia Mix)"
    if " - " in text:
        p_after_art = text.split(" - ", 1)[1].strip()
        # Se contiver remix/feat/mix entre parênteses ou colchetes, preserva
        if re.search(r'[\(\[].*(?:remix|mix|feat|ft\.|ao vivo|live|acustic|acústic|vers|edit|bootleg|dub)[\)\]]', p_after_art, re.IGNORECASE):
            title = p_after_art

    # Capitalização Elegante suave (apenas se tudo maiúsculo ou tudo minúsculo)
    if artist and (artist.isupper() or artist.islower()):
        artist = artist.title()

    # Formatos de Nomenclatura para o DJ escolher:
    # 1. Padrão DJ Clássico: Artista - Título
    fmt_dj = f"{artist} - {title}".strip(" -") if artist else title

    # 2. Com Crate Raiz: Artista - Título - Crate
    if crate_raiz:
        fmt_crate = f"{artist} - {title} - {crate_raiz}".strip(" -")
    else:
        fmt_crate = fmt_dj

    # 3. Completo: Artista - Título - Crate - Álbum
    extra_parts = []
    if crate_raiz:
        extra_parts.append(crate_raiz)
    if album and album.lower() != crate_raiz.lower():
        extra_parts.append(album)

    if extra_parts:
        fmt_completo = f"{artist} - {title} - {' - '.join(extra_parts)}".strip(" -")
    else:
        fmt_completo = fmt_crate

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
                    crate_raiz: str = "", subcrate: str = "", include_subcrates: bool = True):
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
                clean_target_name = f"{clean_quick['clean_filename']}{ext}"

                # Detecção rápida de sujeira pelo nome do arquivo
                needs_clean_name = (clean_target_name != f)
                if needs_clean_name:
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

                    needs_clean = (clean_target_name != f or
                                   artist_current != clean_res["artist"] or
                                   title_current != clean_res["title"])

                    items.append({
                        "id": f"tag-{total_found}",
                        "caminho": str(full_path),
                        "arquivo_atual": f,
                        "arquivo_sugerido": clean_target_name,
                        "nome_dj": f"{clean_res['fmt_dj']}{ext}",
                        "nome_crate": f"{clean_res['fmt_crate']}{ext}",
                        "nome_completo": f"{clean_res['fmt_completo']}{ext}",
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

            # Renomeação opcional segura no disco
            if rename_files_on_disk and item.get("arquivo_sugerido"):
                novo_nome = item["arquivo_sugerido"]
                novo_caminho = file_path.parent / novo_nome
                if novo_caminho != file_path and not novo_caminho.exists():
                    file_path.rename(novo_caminho)

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

    # 1. Enumera rapidamente todos os arquivos alvo
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

            # Renomeação opcional no disco
            if rename_files and suggested_filename != filename:
                dest_path = full_path.parent / suggested_filename
                if dest_path != full_path and not dest_path.exists():
                    full_path.rename(dest_path)

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
            include_subcrates=not args.no_subcrates
        )
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

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
