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

sys.dont_write_bytecode = True
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

# Vendor fallback: permite carregar dependências empacotadas sem exigir pip local
_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sound_seal_masters (
            audio_seal TEXT PRIMARY KEY,
            master_filepath TEXT,
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


def scan_sound_seals(mp3_base_dir: str, batch_size: int = 0, stream_json: bool = True):
    """
    Varre a pasta de MP3 e gera os Sound Seals de forma incremental e resiliente.
    batch_size = 0 significa varrer toda a biblioteca sem interrupção.
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
                fp = Path(root) / f
                if fp.is_symlink() and not fp.exists():
                    try:
                        fp.unlink()
                    except OSError:
                        pass
                    continue
                all_files.append((fp, f, os.path.relpath(root, str(base_path))))

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
        is_cached = False
        if path_str in cached:
            c_size, c_mtime, c_seal = cached[path_str]
            if c_size == size and abs(c_mtime - mtime) < 0.1 and c_seal:
                is_cached = True

        if not is_cached:
            # Calcula novo Sound Seal
            seal = compute_audio_seal(path_str)
            if seal:
                bpm, key, duration = get_track_metadata(path_str)
                crate_parts = [p for p in rel_folder.replace('\\', '/').split('/') if p]
                crate_raiz = crate_parts[0] if crate_parts else ""

                cursor.execute("""
                    INSERT OR REPLACE INTO sound_seals (filepath, filename, filesize, mtime, audio_seal, bpm, key, duration, crate_raiz, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (path_str, filename, size, mtime, seal, bpm, key, duration, crate_raiz))

                new_computed += 1

        # Streaming de progresso fluido e responsivo
        if stream_json and (processed_count % 35 == 0 or processed_count == total_files or (new_computed > 0 and new_computed % 5 == 0)):
            if new_computed > 0 and new_computed % 25 == 0:
                conn.commit()
            pct = round((processed_count / max(1, total_files)) * 100, 1)
            print(json.dumps({
                "tipo": "progresso",
                "processados": processed_count,
                "total": total_files,
                "percentual": pct,
                "novos": new_computed,
                "faixa": filename
            }, ensure_ascii=False), flush=True)

        if batch_size > 0 and new_computed >= batch_size:
            break

    conn.commit()
    conn.close()

    st = get_sound_seal_status()
    if stream_json:
        print(json.dumps({
            "tipo": "fim",
            "sucesso": True,
            "total_processados": processed_count,
            "total_arquivos": total_files,
            "novos_selados": new_computed,
            **st
        }, ensure_ascii=False), flush=True)
    return st


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


def norm_key(s: str) -> str:
    """Normaliza texto para NFC minúsculo para comparações exatas no macOS."""
    if not s:
        return ""
    import unicodedata
    return unicodedata.normalize('NFC', s.strip().lstrip('/')).lower()


def resolve_serato_dir(serato_dir_str: str) -> Path:
    """
    Localiza confiavelmente o diretório do Serato (ex: /Volumes/Pastteyr/_Serato_),
    mesmo que o usuário tenha passado /Volumes/Pastteyr/Serato ou /Volumes/Pastteyr.
    """
    if not serato_dir_str or not serato_dir_str.strip():
        p = Path.home() / "Music" / "_Serato_"
        return p if p.exists() else Path.home() / "Music" / "Serato"

    raw_path = Path(os.path.expanduser(serato_dir_str.strip())).resolve()

    # 1. Se o caminho exato existe e contém Subcrates ou database V2:
    if raw_path.exists():
        if (raw_path / "Subcrates").exists() or (raw_path / "database V2").exists():
            return raw_path
        if (raw_path / "_Serato_").exists():
            return raw_path / "_Serato_"
        if (raw_path / "Serato").exists():
            return raw_path / "Serato"

    # 2. Se foi passado /Volumes/Pastteyr/Serato mas a pasta real é /Volumes/Pastteyr/_Serato_:
    parent = raw_path.parent
    if (parent / "_Serato_").exists():
        return parent / "_Serato_"
    if (parent / "Serato").exists():
        return parent / "Serato"

    # 3. Se foi passada a raiz do volume (/Volumes/Pastteyr)
    if (raw_path / "_Serato_").exists():
        return raw_path / "_Serato_"
    if (raw_path / "Serato").exists():
        return raw_path / "Serato"

    # 4. Fallback no usuário atual
    home_serato = Path.home() / "Music" / "_Serato_"
    if home_serato.exists():
        return home_serato

    return raw_path


def score_master_candidate(filepath: str, crate_raiz: str = "", bpm: str = None, key: str = None) -> int:
    """
    Pontuação inteligente para eleger o arquivo de referência protegida (Master):
    - Penaliza nomes contendo 'cópia', '(1)', etc.
    - Penaliza pastas de staging/despejo ('01', '1', 'temp', 'downloads', 'inbox')
    - Pontua hierarquia mais profunda e específica (subcrates curadas)
    - Pontua anos mais recentes (ex: 2026, 2025...)
    - Pontua completude de metadados (BPM e Key)
    """
    score = 0
    p = Path(filepath)
    fname = p.name.lower()
    fpath = filepath.lower()

    # Penalidades severas para nomes de cópia
    copy_patterns = ['cópia', 'copia', 'copy', '(1)', '(2)', '(3)', '_1', '_2', ' - 1', ' - 2', 'dup']
    if any(pat in fname for pat in copy_patterns):
        score -= 2000

    # Penalidades para pastas genéricas ou temporárias
    staging_patterns = ['/downloads/', '/temp/', '/tmp/', '/inbox/', '/quarentena/', '/novas/', '/01/', '/1/']
    if any(pat in fpath for pat in staging_patterns):
        score -= 1000

    # Bônus para profundidade da pasta (subpastas mais organizadas ganham prioridade)
    depth = len(p.parts)
    score += depth * 50

    # Bônus para anos mais recentes no caminho (ex: 2026, 2025, 2024...)
    for year in range(2026, 2010, -1):
        if str(year) in fpath:
            score += (year - 2010) * 30
            break

    # Bônus para metadados ricos (BPM / Key presentes)
    if bpm and str(bpm).strip() not in ('', '0', '0.0'):
        score += 20
    if key and str(key).strip() != '':
        score += 20

    return score


def get_sound_seal_duplicates(limit: int = 5000, strategy: str = "desc"):
    """
    Lista cópias que possuem exatamente o mesmo selo sonoro (áudio idêntico), podando arquivos deletados.
    strategy:
      - 'desc': Inverte a ordem alfabética (Z -> A), priorizando crates específicas e edições mais recentes.
      - 'smart': Algoritmo inteligente baseado em hierarquia, nome limpo e metadados.
      - 'asc': Ordem alfabética padrão (A -> Z).
    """
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
    dead_paths = []

    # 'desc' e 'smart' ordenam s.filepath DESC no banco por padrão para que o Master inicial seja o mais qualificado
    order_sql = "s.filepath DESC" if strategy in ("desc", "smart") else "s.filepath ASC"

    for seal, cnt in groups:
        cursor.execute(f"""
            SELECT s.filepath, s.filename, s.filesize, s.bpm, s.key, s.duration, s.crate_raiz,
                   CASE WHEN m.master_filepath = s.filepath THEN 1 ELSE 0 END as is_master
            FROM sound_seals s
            LEFT JOIN sound_seal_masters m ON s.audio_seal = m.audio_seal
            WHERE s.audio_seal = ?
            ORDER BY is_master DESC, {order_sql}
        """, (seal,))
        rows = cursor.fetchall()

        items = []
        for r in rows:
            p = Path(r[0])
            if not p.exists():
                dead_paths.append(r[0])
                continue

            score = score_master_candidate(r[0], r[6], r[3], r[4])
            items.append({
                "caminho": r[0],
                "nome": r[1],
                "tamanho": r[2],
                "bpm": r[3],
                "key": r[4],
                "duracao": r[5],
                "crate": r[6],
                "is_master": bool(r[7]),
                "score": score
            })

        # Se a estratégia for "smart" e nenhum master manual foi fixado (nenhum is_master == True):
        # Ordenamos os candidatos por pontuação inteligente decrescente
        if strategy == "smart" and not any(it["is_master"] for it in items):
            items.sort(key=lambda x: (x["score"], x["caminho"]), reverse=True)

        # Só retorna o grupo se restarem 2 ou mais cópias físicas existentes no disco
        if len(items) > 1:
            results.append({
                "seal": seal,
                "total_copias": len(items),
                "faixas": items
            })

    # Prune automático de arquivos que não existem mais
    if dead_paths:
        for dp in dead_paths:
            cursor.execute("DELETE FROM sound_seals WHERE filepath = ?", (dp,))
        conn.commit()

    conn.close()
    return {"sucesso": True, "duplicados_som": results, "estrategia": strategy}


def set_sound_seal_master(audio_seal: str, filepath: str):
    """
    Define manualmente qual caminho físico é a referência protegida (master) de um determinado selo acústico.
    Persiste a preferência no SQLite para que o usuário controle qual pasta/cópia deve ser preservada.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sound_seal_masters (audio_seal, master_filepath, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(audio_seal) DO UPDATE SET
            master_filepath = excluded.master_filepath,
            updated_at = CURRENT_TIMESTAMP
    """, (audio_seal, filepath))
    conn.commit()
    conn.close()
    return {"sucesso": True, "audio_seal": audio_seal, "master_filepath": filepath}


def batch_set_sound_seal_masters(masters: list):
    """
    Atualiza em lote múltiplos arquivos de referência protegida (masters).
    masters: list de dicts [{"audio_seal": str, "filepath": str}]
    """
    if not masters:
        return {"sucesso": True, "total_atualizados": 0}
    conn = get_db()
    cursor = conn.cursor()
    params = [(m["audio_seal"], m["filepath"]) for m in masters if "audio_seal" in m and "filepath" in m]
    cursor.executemany("""
        INSERT INTO sound_seal_masters (audio_seal, master_filepath, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(audio_seal) DO UPDATE SET
            master_filepath = excluded.master_filepath,
            updated_at = CURRENT_TIMESTAMP
    """, params)
    conn.commit()
    conn.close()
    return {"sucesso": True, "total_atualizados": len(params)}


def clear_all_sound_seal_masters():
    """Limpa todas as preferências manuais de master, voltando à ordenação automática."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sound_seal_masters")
    conn.commit()
    conn.close()
    return {"sucesso": True}


def validate_safe_relative_path(rel_path: str) -> bool:
    """Verifica se o caminho relativo é seguro e não contém travessia de diretório (../)."""
    if not rel_path or not isinstance(rel_path, str):
        return False
    clean = rel_path.replace('\\', '/')
    parts = [p.strip() for p in clean.split('/') if p.strip()]
    if '..' in parts or any(p == '..' for p in parts):
        return False
    return True


def extract_volume_from_path(rel_path: str) -> str:
    """Extrai o nome do volume se o caminho referenciar /Volumes/<VolumeName>/..."""
    if not rel_path or not isinstance(rel_path, str):
        return ""
    clean = rel_path.strip().lstrip('/')
    parts = clean.split('/')
    if len(parts) >= 2 and parts[0] == 'Volumes':
        return parts[1]
    return ""


def is_volume_mounted(vol_name: str, volumes_root: Path = Path("/Volumes")) -> bool:
    """Verifica se o volume especificado está montado no sistema."""
    if not vol_name:
        return True
    vol_path = volumes_root / vol_name
    return vol_path.exists() and vol_path.is_dir()


def is_track_volume_available(rel_path: str, mp3_base: Path, volumes_root: Path = Path("/Volumes")) -> bool:
    """
    Verifica se o volume onde a faixa reside está montado e acessível.
    Retorna False se o caminho apontar para um volume desmontado/desconectado.
    """
    vol_name = extract_volume_from_path(rel_path)
    if vol_name:
        return is_volume_mounted(vol_name, volumes_root)

    # Se o caminho for relativo ao mp3_base, verifica o volume do mp3_base
    try:
        mp3_base_res = mp3_base.resolve()
        parts = mp3_base_res.parts
        if len(parts) >= 3 and parts[1] == 'Volumes':
            base_vol = parts[2]
            return is_volume_mounted(base_vol, volumes_root)
    except Exception:
        pass

    return True


def resolve_serato_path(rel_path: str, mp3_base: Path):
    """
    Resolve com precisão o caminho físico de uma faixa registrada no Serato.
    Suporta caminhos relativos ao volume (/Volumes/Pastteyr/Music/MP3),
    caminhos absolutos (/Users/...) e outros volumes montados.
    """
    if not rel_path:
        return None

    clean_rel = rel_path.strip().lstrip('/')

    # 1. Caminho absoluto
    p_abs = Path(rel_path)
    if p_abs.is_absolute() and p_abs.exists():
        return p_abs

    # 2. Caminho a partir da raiz do volume do mp3_base (ex: /Volumes/Pastteyr / Music/MP3/...)
    parts = mp3_base.resolve().parts
    if len(parts) >= 3 and parts[1] == 'Volumes':
        vol_root = Path(parts[0]) / parts[1] / parts[2]
        cand = vol_root / clean_rel
        if cand.exists():
            return cand

    # 3. Caminho a partir da raiz do sistema (ex: Users/pastteur/Music/...)
    cand_sys = Path('/') / clean_rel
    if cand_sys.exists():
        return cand_sys

    # 4. Alinhamento com a pasta MP3 base ou seus ancestrais
    curr = mp3_base
    while curr != curr.parent:
        cand = curr / clean_rel
        if cand.exists():
            return cand
        cand_p = curr.parent / clean_rel
        if cand_p.exists():
            return cand_p
        curr = curr.parent

    # 5. Outros volumes montados no Mac
    if Path("/Volumes").exists():
        for vol in Path("/Volumes").iterdir():
            if vol.is_dir() and not vol.name.startswith('.'):
                cand_vol = vol / clean_rel
                if cand_vol.exists():
                    return cand_vol

    return None


def get_serato_target_path(rel_path: str, mp3_base: Path) -> Path:
    """Calcula o caminho de destino ideal no disco onde o Serato espera o arquivo."""
    clean_rel = rel_path.strip().lstrip('/')
    mp3_base_res = mp3_base.resolve()

    if rel_path.startswith('/Volumes/') or rel_path.startswith('/Users/'):
        return Path(rel_path)
    if clean_rel.startswith('Volumes/') or clean_rel.startswith('Users/'):
        return Path('/') / clean_rel

    parts = mp3_base_res.parts
    if len(parts) >= 3 and parts[1] == 'Volumes':
        vol_root = Path(parts[0]) / parts[1] / parts[2]
        return vol_root / clean_rel

    return mp3_base_res / clean_rel


def scan_missing_and_relocate(serato_dir_str: str, mp3_dir_str: str, stream_json: bool = True):
    """
    Rastreia faixas do Serato cujo arquivo físico não existe no local registrado.
    Procura correspondências com Score de Confiança (100%, 87%, 77%) e na Lixeira (.Trashes).
    """
    conn = get_db()
    cursor = conn.cursor()

    # Mapeia todas as crates do Serato usando resolução inteligente
    serato_dir = resolve_serato_dir(serato_dir_str)
    subcrates_dirs = []
    if (serato_dir / "Subcrates").exists():
        subcrates_dirs.append(serato_dir / "Subcrates")

    mp3_base = Path(os.path.expanduser(mp3_dir_str)).resolve()
    parts = mp3_base.parts
    if len(parts) >= 3 and parts[1] == 'Volumes':
        ext_sc = Path(parts[0]) / parts[1] / parts[2] / "_Serato_" / "Subcrates"
        if ext_sc.exists() and ext_sc not in subcrates_dirs:
            subcrates_dirs.append(ext_sc)
    home_sc = Path.home() / "Music" / "_Serato_" / "Subcrates"
    if home_sc.exists() and home_sc not in subcrates_dirs:
        subcrates_dirs.append(home_sc)

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

    crate_files = []
    for sc_dir in subcrates_dirs:
        crate_files.extend(list(sc_dir.glob("*.crate")))
    total_crates = len(crate_files)

    for c_idx, crate_file in enumerate(crate_files, 1):
        if stream_json and (c_idx % 5 == 0 or c_idx == total_crates):
            pct = round((c_idx / max(1, total_crates)) * 50, 1)
            print(json.dumps({
                "tipo": "progresso",
                "etapa": "crates",
                "processados": c_idx,
                "total": total_crates,
                "percentual": pct,
                "faixa": f"Auditando Crate: {crate_file.stem.replace('%%', ' -> ')}"
            }, ensure_ascii=False), flush=True)

        try:
            content = crate_file.read_bytes()
            idx = 0
            while True:
                p = content.find(b'ptrk', idx)
                if p == -1 or p + 8 > len(content):
                    break
                size = int.from_bytes(content[p+4:p+8], byteorder='big')
                raw_str = content[p+8:p+8+size]
                rel_path = raw_str.decode('utf-16-be', errors='ignore').strip()
                idx = p + 8 + size

                if rel_path in checked_paths:
                    continue
                checked_paths.add(rel_path)

                # Verifica se o arquivo existe usando resolução inteligente de volumes
                resolved = resolve_serato_path(rel_path, mp3_base)
                if not resolved:
                    filename = Path(rel_path).name
                    missing_tracks.append({
                        "caminho_serato": rel_path,
                        "nome": filename,
                        "crate_origem": crate_file.stem.replace('%%', ' -> ')
                    })
        except Exception:
            continue

    # 2. Busca também na database V2 do Serato (banco central de faixas)
    db_candidates = [
        serato_dir / "database V2",
        Path.home() / "Music" / "_Serato_" / "database V2"
    ]
    if len(parts) >= 3 and parts[1] == 'Volumes':
        ext_db = Path(parts[0]) / parts[1] / parts[2] / "_Serato_" / "database V2"
        if ext_db.exists() and ext_db not in db_candidates:
            db_candidates.append(ext_db)

    for db_file in db_candidates:
        if db_file.exists():
            try:
                db_data = db_file.read_bytes()
                pos = 72
                while pos < len(db_data):
                    tag = db_data[pos:pos+4]
                    if len(tag) < 4:
                        break
                    length = int.from_bytes(db_data[pos+4:pos+8], byteorder='big')
                    if tag == b'otrk':
                        block = db_data[pos:pos+8+length]
                        p_idx = block.find(b'pfil')
                        if p_idx != -1 and p_idx + 8 <= len(block):
                            p_len = int.from_bytes(block[p_idx+4:p_idx+8], byteorder='big')
                            rel_p = block[p_idx+8:p_idx+8+p_len].decode('utf-16-be', errors='ignore').strip()
                            if rel_p and rel_p not in checked_paths:
                                checked_paths.add(rel_p)
                                resolved = resolve_serato_path(rel_p, mp3_base)
                                if not resolved:
                                    missing_tracks.append({
                                        "caminho_serato": rel_p,
                                        "nome": Path(rel_p).name,
                                        "crate_origem": "Biblioteca Serato (database V2)"
                                    })
                    pos += 8 + length
            except Exception:
                pass
            break

    # Agora para cada faixa faltante, busca candidatos com score
    results = []
    total_eval = min(len(missing_tracks), 1000)
    for m_idx, missing in enumerate(missing_tracks[:1000], 1):
        if stream_json and (m_idx % 5 == 0 or m_idx == total_eval):
            pct = round(50 + (m_idx / max(1, total_eval)) * 50, 1)
            print(json.dumps({
                "tipo": "progresso",
                "etapa": "matching",
                "processados": m_idx,
                "total": total_eval,
                "percentual": pct,
                "faixa": f"Buscando correspondência: {missing['nome']}"
            }, ensure_ascii=False), flush=True)

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
            if m_name == fname or norm_key(m_name) == norm_key(fname):
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
    res = {
        "sucesso": True,
        "total_perdidas": len(missing_tracks),
        "analisadas": results
    }
    if stream_json:
        print(json.dumps({"tipo": "fim", **res}, ensure_ascii=False), flush=True)
    return res


def relink_track(mp3_base_dir: str, rel_path: str, source_path_str: str):
    """
    Restaura ou religa o arquivo de som ao local esperado pela crate do Serato.
    Se a fonte estiver em .Trashes, move de volta; caso contrário, copia.
    Possui validação estrita contra travessia de diretório (../).
    """
    if not validate_safe_relative_path(rel_path):
        return {
            "sucesso": False,
            "erro": f"Caminho inseguro rejeitado por segurança (travessia de diretório detectada com '..'): {rel_path}"
        }

    mp3_base = Path(os.path.expanduser(mp3_base_dir)).resolve()
    try:
        target_path = get_serato_target_path(rel_path, mp3_base)
        target_res = target_path.resolve()
        # Validação contra fuga de diretório autorizado
        allowed_roots = [mp3_base, Path("/Volumes").resolve(), Path.home().resolve()]
        if not any(str(target_res).startswith(str(r)) for r in allowed_roots):
            return {"sucesso": False, "erro": f"Destino fora do diretório autorizado: {target_res}"}
    except Exception as e:
        return {"sucesso": False, "erro": f"Caminho inválido: {e}"}

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


def remove_from_database_v2(db_file: Path, target_paths: set = None, mp3_base: Path = None, max_pct: float = 0.20) -> int:
    """
    Remove entradas de faixas de database V2 preservando vrsn e blocos válidos.
    Executa verificação obrigatória de volume montado, limite percentual de segurança,
    backup verificado e escrita atômica via arquivo temporário.
    """
    if not db_file.exists():
        return 0
    try:
        data = db_file.read_bytes()
        if len(data) < 72:
            return 0
        header = data[:72]
        pos = 72
        entries = []
        total_entries = 0
        while pos < len(data):
            tag = data[pos:pos+4]
            if len(tag) < 4:
                break
            length = int.from_bytes(data[pos+4:pos+8], byteorder='big')
            block_end = pos + 8 + length
            block = data[pos:block_end]

            p_idx = block.find(b'pfil')
            rel_p = ""
            if p_idx != -1 and p_idx + 8 <= len(block):
                p_len = int.from_bytes(block[p_idx+4:p_idx+8], byteorder='big')
                rel_p = block[p_idx+8:p_idx+8+p_len].decode('utf-16-be', errors='ignore').strip()

            entries.append((rel_p, block))
            total_entries += 1
            pos = block_end

        kept_blocks = []
        removed = 0
        skipped_unmounted = 0
        for rel_p, block in entries:
            should_remove = False
            # Checagem de volume montado: JAMAIS remover faixas de volumes desmontados
            if rel_p and not is_track_volume_available(rel_p, mp3_base if mp3_base else Path("/")):
                skipped_unmounted += 1
                kept_blocks.append(block)
                continue

            if rel_p:
                if target_paths is not None:
                    norm_p = norm_key(rel_p)
                    norm_fname = norm_key(Path(rel_p).name)
                    if norm_p in target_paths or norm_fname in target_paths:
                        should_remove = True
                elif mp3_base is not None:
                    if not resolve_serato_path(rel_p, mp3_base):
                        should_remove = True

            if should_remove:
                removed += 1
            else:
                kept_blocks.append(block)

        # Limite percentual de segurança para database V2 (evita corrupção catastrófica por biblioteca movida)
        if target_paths is None and total_entries > 0 and (removed / total_entries) > max_pct:
            print(f"[PROTEÇÃO] Remoção em database V2 abortada: percentual de faixas ausentes ({removed}/{total_entries} = {round(removed/total_entries*100, 1)}%) excede o teto de segurança de {int(max_pct*100)}%.", file=sys.stderr)
            return 0

        if removed > 0:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            bak = db_file.parent / f"database_V2_{ts}.bak"
            import shutil
            shutil.copy2(str(db_file), str(bak))
            if not bak.exists() or bak.stat().st_size != db_file.stat().st_size:
                raise IOError("Falha na criação/verificação de backup do database V2")

            import uuid
            temp_db = db_file.with_name(f".tmp_db_{uuid.uuid4().hex[:8]}")
            new_db_content = header + b''.join(kept_blocks)
            try:
                with open(temp_db, 'wb') as f:
                    f.write(new_db_content)
                    f.flush()
                    os.fsync(f.fileno())

                if not temp_db.exists() or temp_db.stat().st_size < len(header):
                    raise IOError("Arquivo temporário do database V2 incompleto.")

                os.replace(str(temp_db), str(db_file))
            finally:
                if temp_db.exists():
                    try:
                        temp_db.unlink()
                    except Exception:
                        pass
        return removed
    except Exception as e:
        print(f"Erro ao limpar database V2: {e}", file=sys.stderr)
        return 0


def remove_lost_tracks_from_crates(serato_dir_str: str, mp3_dir_str: str, target_path: str = "", target_paths_json: str = "", max_lost_pct: float = 0.20):
    """
    Remove entradas de faixas perdidas (inexistentes no disco ou selecionadas)
    de todas as crates do Serato e também da biblioteca central (database V2).
    Preserva 100% dos cabeçalhos vrsn/ovct e blocos válidos.
    Cria backup automático verificado (.crate.bak / database_V2.bak) antes de alterar qualquer arquivo.
    Possui travas rigorosas:
      - Checagem prévia de volume montado (faixas de discos desconectados NUNCA são removidas)
      - Teto percentual por crate (bloqueia limpeza automática se mais de 20% das faixas forem perdidas)
      - Gravação temporária atômica com os.replace e os.fsync
    """
    serato_dir = resolve_serato_dir(serato_dir_str)
    mp3_base = Path(os.path.expanduser(mp3_dir_str)).resolve()

    # Validação prévia de montagem do volume base
    if not is_track_volume_available("", mp3_base):
        return {
            "sucesso": False,
            "erro": f"Volume base da biblioteca de áudio não está montado ou acessível: {mp3_base}",
            "total_removidas": 0,
            "crates_removidas": 0,
            "database_v2_removidas": 0,
            "crates_afetadas": []
        }

    subcrates_dirs = []
    if (serato_dir / "Subcrates").exists():
        subcrates_dirs.append(serato_dir / "Subcrates")

    parts = mp3_base.resolve().parts
    if len(parts) >= 3 and parts[1] == 'Volumes':
        ext_sc = Path(parts[0]) / parts[1] / parts[2] / "_Serato_" / "Subcrates"
        if ext_sc.exists() and ext_sc not in subcrates_dirs:
            subcrates_dirs.append(ext_sc)

    home_sc = Path.home() / "Music" / "_Serato_" / "Subcrates"
    if home_sc.exists() and home_sc not in subcrates_dirs:
        subcrates_dirs.append(home_sc)

    target_set = None
    if target_path and target_path.strip():
        t = target_path.strip()
        target_set = {norm_key(t), norm_key(Path(t).name)}
    elif target_paths_json and target_paths_json.strip():
        try:
            arr = json.loads(target_paths_json)
            target_set = set()
            for it in arr:
                if it and isinstance(it, str):
                    target_set.add(norm_key(it))
                    target_set.add(norm_key(Path(it).name))
        except Exception:
            target_set = None

    total_removed = 0
    crates_affected = []

    for sc_dir in subcrates_dirs:
        for crate_file in sorted(sc_dir.glob("*.crate")):
            try:
                content = crate_file.read_bytes()
                pos = 0
                header_end = 0
                otrk_blocks = []

                # 1. Varre o arquivo .crate separando o cabeçalho dos blocos de faixas (otrk)
                while pos < len(content):
                    tag = content[pos:pos+4]
                    if len(tag) < 4:
                        break
                    length = int.from_bytes(content[pos+4:pos+8], byteorder='big')
                    if tag == b'otrk':
                        block_end = pos + 8 + length
                        block = content[pos:block_end]
                        p_idx = block.find(b'ptrk')
                        if p_idx != -1 and p_idx + 8 <= len(block):
                            p_len = int.from_bytes(block[p_idx+4:p_idx+8], byteorder='big')
                            path_str = block[p_idx+8:p_idx+8+p_len].decode('utf-16-be', errors='ignore').strip()
                            otrk_blocks.append((path_str, block))
                        pos = block_end
                    else:
                        pos += 8 + length
                        header_end = pos

                if not otrk_blocks:
                    continue

                header_bytes = content[:header_end]
                kept_blocks = []
                removed_in_this = 0
                skipped_unmounted = 0

                # 2. Verifica se a faixa deve ser removida
                for rel_path, block in otrk_blocks:
                    should_remove = False

                    # CRÍTICO: Checagem de volume montado antes de qualquer deliberação
                    if not is_track_volume_available(rel_path, mp3_base):
                        # Faixa reside em volume externo atualmente desconectado: PRESERVAR!
                        skipped_unmounted += 1
                        kept_blocks.append(block)
                        continue

                    if target_set is not None:
                        norm_p = norm_key(rel_path)
                        norm_fname = norm_key(Path(rel_path).name)
                        if norm_p in target_set or norm_fname in target_set:
                            should_remove = True
                    else:
                        resolved = resolve_serato_path(rel_path, mp3_base)
                        if not (resolved and resolved.exists()):
                            should_remove = True

                    if should_remove:
                        removed_in_this += 1
                    else:
                        kept_blocks.append(block)

                # Trava de segurança: limite percentual por crate (ex: 20%)
                # Protege contra deleção acidental massiva se a biblioteca foi movida de pasta
                total_crate_tracks = len(otrk_blocks)
                if target_set is None and total_crate_tracks > 0 and (removed_in_this / total_crate_tracks) > max_lost_pct:
                    crates_affected.append({
                        "crate": crate_file.stem.replace('%%', ' -> '),
                        "bloqueado_seguranca": True,
                        "removidas_propostas": removed_in_this,
                        "total_faixas": total_crate_tracks,
                        "percentual": round((removed_in_this / total_crate_tracks) * 100, 1),
                        "puladas_desconectadas": skipped_unmounted,
                        "motivo": f"Percentual de faixas ausentes ({removed_in_this}/{total_crate_tracks} = {round(removed_in_this/total_crate_tracks*100, 1)}%) excede o teto de segurança de {int(max_lost_pct*100)}%."
                    })
                    continue

                # 3. Se houver faixas removidas, cria backup verificado e regrava a crate atomicamente
                if removed_in_this > 0:
                    new_content = header_bytes + b''.join(kept_blocks)
                    backup_path = crate_file.with_suffix('.crate.bak')
                    try:
                        import shutil
                        shutil.copy2(str(crate_file), str(backup_path))
                        if not backup_path.exists() or backup_path.stat().st_size != crate_file.stat().st_size:
                            raise IOError("Falha na criação ou validação de tamanho do backup .crate.bak")
                    except Exception as e_bak:
                        crates_affected.append({
                            "crate": crate_file.name,
                            "erro": f"Backup prévio obrigatório falhou: {e_bak}. Alteração abortada."
                        })
                        continue

                    import uuid
                    temp_crate = crate_file.with_name(f".tmp_{crate_file.name}_{uuid.uuid4().hex[:8]}")
                    try:
                        with open(temp_crate, 'wb') as f:
                            f.write(new_content)
                            f.flush()
                            os.fsync(f.fileno())

                        if not temp_crate.exists() or temp_crate.stat().st_size < len(header_bytes):
                            raise IOError("Arquivo temporário da crate gerado incompleto.")

                        if not temp_crate.read_bytes().startswith(b'vrsn'):
                            raise IOError("Arquivo temporário da crate não possui cabeçalho vrsn válido.")

                        os.replace(str(temp_crate), str(crate_file))

                        total_removed += removed_in_this
                        crates_affected.append({
                            "crate": crate_file.stem.replace('%%', ' -> '),
                            "removidas": removed_in_this,
                            "restantes": len(kept_blocks),
                            "puladas_desconectadas": skipped_unmounted,
                            "backup": str(backup_path)
                        })
                    finally:
                        if temp_crate.exists():
                            try:
                                temp_crate.unlink()
                            except Exception:
                                pass

            except Exception as e:
                crates_affected.append({
                    "crate": crate_file.name,
                    "erro": str(e)
                })
                continue

    # Limpa também na database V2 do Serato (banco central de faixas)
    db_candidates = [
        serato_dir / "database V2",
        Path.home() / "Music" / "_Serato_" / "database V2"
    ]
    if len(parts) >= 3 and parts[1] == 'Volumes':
        ext_db = Path(parts[0]) / parts[1] / parts[2] / "_Serato_" / "database V2"
        if ext_db.exists() and ext_db not in db_candidates:
            db_candidates.append(ext_db)

    total_db_removed = 0
    for db_cand in db_candidates:
        if db_cand.exists():
            cnt = remove_from_database_v2(db_cand, target_set, mp3_base if target_set is None else None, max_pct=max_lost_pct)
            total_db_removed += cnt

    # Também remove do banco SQLite de Sound Seals para manter o cache sincronizado
    try:
        conn = get_db()
        cursor = conn.cursor()
        if target_set:
            for item in target_set:
                cursor.execute("DELETE FROM sound_seals WHERE filepath LIKE ? OR filename = ?", (f"%{item}%", item))
        conn.commit()
        conn.close()
    except Exception:
        pass

    return {
        "sucesso": True,
        "total_removidas": total_removed + total_db_removed,
        "crates_removidas": total_removed,
        "database_v2_removidas": total_db_removed,
        "crates_afetadas": crates_affected
    }


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Sound Seal & Relocate")
    parser.add_argument("--scan", action="store_true", help="Gera Sound Seals na pasta MP3")
    parser.add_argument("--mp3", type=str, default="", help="Caminho da pasta MP3")
    parser.add_argument("--serato", type=str, default="", help="Caminho da pasta Serato")
    parser.add_argument("--status", action="store_true", help="Retorna status do banco de Sound Seals")
    parser.add_argument("--duplicates", action="store_true", help="Retorna duplicatas por som")
    parser.add_argument("--strategy", type=str, default="desc", choices=["desc", "smart", "asc"], help="Estratégia de ordenação do Master protegido ('desc', 'smart', 'asc')")
    parser.add_argument("--batch-set-masters", type=str, default="", help="JSON de lista de masters a definir em lote")
    parser.add_argument("--clear-masters", action="store_true", help="Limpa todas as preferências manuais de master")
    parser.add_argument("--relocate", action="store_true", help="Analisa faixas perdidas do Serato")
    parser.add_argument("--batch", type=int, default=0, help="Tamanho do lote de varredura (0 = toda a biblioteca)")
    parser.add_argument("--relink", action="store_true", help="Religa uma faixa específica")
    parser.add_argument("--rel-path", type=str, default="", help="Caminho relativo esperado pelo Serato")
    parser.add_argument("--source-path", type=str, default="", help="Caminho do arquivo localizado no HD")
    parser.add_argument("--batch-relink", type=str, default="", help="JSON de lista de faixas a religar")
    parser.add_argument("--remove-lost", action="store_true", help="Remove faixas perdidas de todas as crates do Serato")
    parser.add_argument("--target-path", type=str, default="", help="Caminho relativo específico a remover")
    parser.add_argument("--target-paths", type=str, default="", help="JSON de lista de caminhos a remover")
    parser.add_argument("--set-master", nargs=2, metavar=("SEAL", "FILEPATH"), help="Define manualmente o arquivo protegido de um selo acústico")

    args = parser.parse_args()

    if args.clear_masters:
        res = clear_all_sound_seal_masters()
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0)

    if args.batch_set_masters:
        try:
            masters_data = json.loads(args.batch_set_masters)
            res = batch_set_sound_seal_masters(masters_data)
            print(json.dumps(res, ensure_ascii=False), flush=True)
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}, ensure_ascii=False), flush=True)
            sys.exit(1)

    if args.set_master:
        seal, fp = args.set_master
        res = set_sound_seal_master(seal, fp)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    if args.status:
        res = get_sound_seal_status()
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0)

    if args.duplicates:
        res = get_sound_seal_duplicates(strategy=args.strategy)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0)

    mp3_dir = args.mp3 or "/Volumes/Pastteyr/Music/MP3"

    if args.relink:
        res = relink_track(mp3_dir, args.rel_path, args.source_path)
        print(json.dumps(res, ensure_ascii=False), flush=True)
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
            print(json.dumps({"tipo": "fim", "sucesso": False, "erro": str(e)}), flush=True)
            sys.exit(1)

    if args.scan:
        scan_sound_seals(mp3_dir, batch_size=args.batch, stream_json=True)
        sys.exit(0)

    if args.relocate:
        serato_dir = args.serato or "/Volumes/Pastteyr/Serato"
        scan_missing_and_relocate(serato_dir, mp3_dir, stream_json=True)
        sys.exit(0)

    if args.remove_lost:
        serato_dir = args.serato or "/Volumes/Pastteyr/Serato"
        res = remove_lost_tracks_from_crates(
            serato_dir,
            mp3_dir,
            target_path=args.target_path,
            target_paths_json=args.target_paths
        )
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
