#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - SOUND SEAL & RELOCATE ENGINE (sound_seal.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Motor de impressão digital acústica (Sound Seal SHA-256) e Relocate inteligente
com scores de confiança (100%, 87%, 77%) e detecção de arquivos na Lixeira (.Trashes).
================================================================================
"""

import sys
import os
import re
import time
import json
import sqlite3
import hashlib
import datetime
import argparse
from pathlib import Path

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

try:
    import mutagen
except ImportError:
    mutagen = None

DB_PATH = Path.home() / ".serato_sound_seals.sqlite"
AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sound_seals (
            filepath TEXT PRIMARY KEY,
            filename TEXT,
            filesize INTEGER,
            mtime REAL,
            audio_seal TEXT,
            bpm TEXT,
            key TEXT,
            duration REAL,
            crate_raiz TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seal ON sound_seals(audio_seal);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_filename ON sound_seals(filename);")
    return conn


def compute_audio_seal(filepath_str: str) -> str:
    """
    Calcula a impressão digital SHA-256 do fluxo de áudio puro,
    ignorando cabeçalhos ID3v2 no início e tags ID3v1 no final.
    """
    try:
        with open(filepath_str, 'rb') as f:
            header = f.read(10)
            start_offset = 0
            if len(header) >= 10 and header[:3] == b'ID3':
                # Synchsafe integer para tamanho do ID3v2
                size = (header[6] << 21) | (header[7] << 14) | (header[8] << 7) | header[9]
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


def get_track_metadata(filepath_str: str):
    bpm = ""
    key = ""
    duration = 0.0
    if mutagen:
        try:
            audio = mutagen.File(filepath_str)
            if audio is not None:
                if hasattr(audio, 'info') and hasattr(audio.info, 'length'):
                    duration = round(audio.info.length, 2)
                if 'TBPM' in audio:
                    bpm = str(audio['TBPM'])
                elif 'bpm' in audio:
                    bpm = str(audio['bpm'][0])
                if 'TKEY' in audio:
                    key = str(audio['TKEY'])
                elif 'initialkey' in audio:
                    key = str(audio['initialkey'][0])
        except Exception:
            pass
    return bpm, key, duration


def scan_sound_seals(mp3_base_dir: str, batch_size: int = 500, stream_json: bool = True):
    """
    Varre a pasta de MP3 e gera os Sound Seals de forma incremental e resiliente.
    Continua exatamente de onde parou após reinicialização.
    """
    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    if not base_path.exists():
        return {"sucesso": False, "erro": f"Pasta não encontrada: {base_path}"}

    conn = get_db()
    cursor = conn.cursor()

    # 1. Carrega cache existente
    cursor.execute("SELECT filepath, filesize, mtime, audio_seal FROM sound_seals")
    cached = {row[0]: (row[1], row[2], row[3]) for row in cursor.fetchall()}

    all_files = []
    for root, _, files in os.walk(str(base_path)):
        if '/.' in root or '\\.' in root:
            continue
        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            if Path(f).suffix.lower() in AUDIO_EXTENSIONS:
                all_files.append((Path(root) / f, f, os.path.relpath(root, str(base_path))))

    total_files = len(all_files)
    processed_count = 0
    new_computed = 0
    start_time = time.time()

    for full_path, filename, rel_folder in all_files:
        path_str = str(full_path)
        processed_count += 1

        try:
            st = full_path.stat()
            size = st.st_size
            mtime = st.st_mtime
        except Exception:
            continue

        # Verifica cache
        if path_str in cached:
            c_size, c_mtime, c_seal = cached[path_str]
            if c_size == size and abs(c_mtime - mtime) < 0.1 and c_seal:
                continue

        # Calcula novo Sound Seal
        seal = compute_audio_seal(path_str)
        if not seal:
            continue

        bpm, key, duration = get_track_metadata(path_str)
        crate_parts = [p for p in rel_folder.replace('\\', '/').split('/') if p]
        crate_raiz = crate_parts[0] if crate_parts else ""

        cursor.execute("""
            INSERT OR REPLACE INTO sound_seals (filepath, filename, filesize, mtime, audio_seal, bpm, key, duration, crate_raiz, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (path_str, filename, size, mtime, seal, bpm, key, duration, crate_raiz))

        new_computed += 1

        if new_computed % 25 == 0:
            conn.commit()
            if stream_json:
                elapsed = time.time() - start_time
                speed = new_computed / elapsed if elapsed > 0 else 1
                remaining = max(0, (total_files - processed_count) / speed) if speed > 0 else 0
                pct = round((processed_count / total_files) * 100, 1) if total_files else 100
                print(f"__SOUND_SEAL_PROGRESS__{json.dumps({'processed': processed_count, 'total': total_files, 'pct': pct, 'remaining_sec': round(remaining)})}")

        if new_computed >= batch_size:
            break

    conn.commit()
    conn.close()

    return get_sound_seal_status()


def get_sound_seal_status():
    """Retorna estatísticas detalhadas da biblioteca de Sound Seals."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM sound_seals")
    total_indexed = cursor.fetchone()[0]

    # Cópias com mesmo selo sonoro
    cursor.execute("""
        SELECT audio_seal, COUNT(*) as cnt 
        FROM sound_seals 
        WHERE audio_seal != '' 
        GROUP BY audio_seal 
        HAVING cnt > 1
    """)
    duplicate_groups = cursor.fetchall()
    total_duplicate_tracks = sum(row[1] for row in duplicate_groups)

    conn.close()

    return {
        "sucesso": True,
        "total_selados": total_indexed,
        "grupos_duplicados_som": len(duplicate_groups),
        "total_faixas_com_copia_som": total_duplicate_tracks
    }


def get_sound_seal_duplicates(limit: int = 5000):
    """Lista cópias que possuem exatamente o mesmo selo sonoro (áudio idêntico)."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT audio_seal, COUNT(*) as cnt
        FROM sound_seals
        WHERE audio_seal != ''
        GROUP BY audio_seal
        HAVING cnt > 1
        ORDER BY cnt DESC
        LIMIT ?
    """, (limit,))

    groups = cursor.fetchall()
    results = []

    for seal, cnt in groups:
        cursor.execute("""
            SELECT filepath, filename, filesize, bpm, key, duration, crate_raiz
            FROM sound_seals
            WHERE audio_seal = ?
            ORDER BY filepath ASC
        """, (seal,))
        rows = cursor.fetchall()

        items = []
        for r in rows:
            items.append({
                "caminho": r[0],
                "nome": r[1],
                "tamanho": r[2],
                "bpm": r[3],
                "key": r[4],
                "duracao": r[5],
                "crate": r[6]
            })

        results.append({
            "seal": seal,
            "total_copias": cnt,
            "faixas": items
        })

    conn.close()
    return {"sucesso": True, "duplicados_som": results}


def scan_missing_and_relocate(serato_dir_str: str, mp3_dir_str: str):
    """
    Rastreia faixas do Serato cujo arquivo físico não existe no local registrado.
    Procura correspondências com Score de Confiança (100%, 87%, 77%) e na Lixeira (.Trashes).
    """
    conn = get_db()
    cursor = conn.cursor()

    # Mapeia todas as crates do Serato
    subcrates_dir = Path(os.path.expanduser(serato_dir_str)) / "Subcrates"
    if not subcrates_dir.exists():
        subcrates_dir = Path(os.path.expanduser(serato_dir_str)) / "_Serato_" / "Subcrates"

    missing_tracks = []
    checked_paths = set()

    # Busca volumes montados e lixeiras locais
    trashes_folders = []
    if Path("/Volumes").exists():
        for vol in Path("/Volumes").iterdir():
            if vol.is_dir() and not vol.name.startswith('.'):
                trash_candidate = vol / ".Trashes" / "501"
                if trash_candidate.exists():
                    trashes_folders.append(trash_candidate)
    user_trash = Path.home() / ".Trash"
    if user_trash.exists():
        trashes_folders.append(user_trash)

    if subcrates_dir.exists():
        for crate_file in subcrates_dir.glob("*.crate"):
            try:
                content = crate_file.read_bytes()
                # Extrai tags ptrk
                idx = 0
                while True:
                    p = content.find(b'ptrk', idx)
                    if p == -1:
                        break
                    size = int.from_bytes(content[p+4:p+8], byteorder='big')
                    raw_str = content[p+8:p+8+size]
                    rel_path = raw_str.decode('utf-16-be', errors='ignore').strip()
                    idx = p + 8 + size

                    if rel_path in checked_paths:
                        continue
                    checked_paths.add(rel_path)

                    # Verifica se o arquivo existe
                    full_candidate = Path(os.path.expanduser(mp3_dir_str)).parent / rel_path
                    if not full_candidate.exists():
                        # Procura em outros volumes
                        found = False
                        if Path("/Volumes").exists():
                            for vol in Path("/Volumes").iterdir():
                                if (vol / rel_path).exists():
                                    found = True
                                    break
                        if not found and not Path(rel_path).exists():
                            filename = Path(rel_path).name
                            missing_tracks.append({
                                "caminho_serato": rel_path,
                                "nome": filename,
                                "crate_origem": crate_file.stem.replace('%%', ' -> ')
                            })
            except Exception:
                continue

    # Agora para cada faixa faltante, busca candidatos com score
    results = []
    for missing in missing_tracks[:100]: # Top 100 para resposta rápida
        fname = missing["nome"]
        candidates = []

        # 1. Verifica se está no lixo (.Trashes)
        in_trash_path = None
        for t_dir in trashes_folders:
            trash_file = t_dir / fname
            if trash_file.exists():
                in_trash_path = str(trash_file)
                break

        # 2. Busca no banco de Sound Seals pelo nome aproximado ou exato
        cursor.execute("SELECT filepath, filename, filesize, bpm, key, duration, audio_seal FROM sound_seals WHERE filename LIKE ? LIMIT 5", (f"%{fname}%",))
        matches = cursor.fetchall()

        for m in matches:
            m_path, m_name, m_size, m_bpm, m_key, m_dur, m_seal = m
            if not Path(m_path).exists():
                continue

            # Calcula score de similaridade
            score = 77
            if m_name == fname:
                score = 100
            elif m_bpm and m_key:
                score = 87

            candidates.append({
                "caminho": m_path,
                "nome": m_name,
                "tamanho": m_size,
                "bpm": m_bpm,
                "key": m_key,
                "duracao": m_dur,
                "score": score
            })

        results.append({
            "faixa_perdida": missing["caminho_serato"],
            "nome": fname,
            "crate": missing["crate_origem"],
            "in_trash": in_trash_path is not None,
            "trash_path": in_trash_path,
            "candidatos": sorted(candidates, key=lambda x: x["score"], reverse=True)
        })

    conn.close()
    return {
        "sucesso": True,
        "total_perdidas": len(missing_tracks),
        "analisadas": results
    }


def relink_track(mp3_base_dir: str, rel_path: str, source_path_str: str):
    """
    Restaura ou religa o arquivo de som ao local esperado pela crate do Serato.
    Se a fonte estiver em .Trashes, move de volta; caso contrário, copia.
    """
    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    target_path = base_path.parent / rel_path
    src = Path(source_path_str)

    if not src.exists():
        return {"sucesso": False, "erro": "Arquivo de som de origem não encontrado."}

    try:
        import shutil
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if ".Trashes" in str(src) or ".Trash" in str(src):
            shutil.move(str(src), str(target_path))
        else:
            shutil.copy2(str(src), str(target_path))
        return {
            "sucesso": True,
            "arquivo": target_path.name,
            "destino": str(target_path),
            "mensagem": f"Faixa religada com sucesso ao Serato em: {target_path}"
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def batch_relink_tracks(mp3_base_dir: str, relink_items: list):
    """Executa a relocalização/restauração em lote para todas as correspondências confirmadas."""
    total = len(relink_items)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    relinked = 0
    errors = []

    for idx, item in enumerate(relink_items, 1):
        rel_p = item.get("rel_path") or item.get("faixa_perdida", "")
        src_p = item.get("source_path") or item.get("candidato_caminho", "")
        res = relink_track(mp3_base_dir, rel_p, src_p)
        if res.get("sucesso"):
            relinked += 1
        else:
            errors.append(f"{rel_p}: {res.get('erro')}")

        pct = round((idx / total) * 100, 1)
        print(json.dumps({
            "tipo": "progresso",
            "processados": idx,
            "total": total,
            "percentual": pct,
            "atualizados": relinked,
            "faixa_atual": Path(rel_p).name
        }, ensure_ascii=False), flush=True)

    print(json.dumps({
        "tipo": "fim",
        "sucesso": True,
        "total": total,
        "atualizados": relinked,
        "erros": errors[:10]
    }, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Sound Seal & Relocate")
    parser.add_argument("--scan", action="store_true", help="Gera Sound Seals na pasta MP3")
    parser.add_argument("--mp3", type=str, default="", help="Caminho da pasta MP3")
    parser.add_argument("--serato", type=str, default="", help="Caminho da pasta Serato")
    parser.add_argument("--status", action="store_true", help="Retorna status do banco de Sound Seals")
    parser.add_argument("--duplicates", action="store_true", help="Retorna duplicatas por som")
    parser.add_argument("--relocate", action="store_true", help="Analisa faixas perdidas do Serato")
    parser.add_argument("--batch", type=int, default=500, help="Tamanho do lote de varredura")
    parser.add_argument("--relink", action="store_true", help="Religa uma faixa específica")
    parser.add_argument("--rel-path", type=str, default="", help="Caminho relativo esperado pelo Serato")
    parser.add_argument("--source-path", type=str, default="", help="Caminho do arquivo localizado no HD")
    parser.add_argument("--batch-relink", type=str, default="", help="JSON de lista de faixas a religar")

    args = parser.parse_args()

    if args.status:
        res = get_sound_seal_status()
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

    if args.duplicates:
        res = get_sound_seal_duplicates()
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

    mp3_dir = args.mp3 or "/Volumes/Pastteyr/Music/MP3"

    if args.relink:
        res = relink_track(mp3_dir, args.rel_path, args.source_path)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.batch_relink:
        try:
            if args.batch_relink.startswith('['):
                items = json.loads(args.batch_relink)
            else:
                with open(args.batch_relink, 'r', encoding='utf-8') as f:
                    items = json.load(f)
            batch_relink_tracks(mp3_dir, items)
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"tipo": "fim", "sucesso": False, "erro": str(e)}))
            sys.exit(1)

    if args.scan:
        res = scan_sound_seals(mp3_dir, batch_size=args.batch)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

    if args.relocate:
        serato_dir = args.serato or "/Volumes/Pastteyr/Serato"
        res = scan_missing_and_relocate(serato_dir, mp3_dir)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
