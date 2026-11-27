#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - JOURNAL DE ALTERAÇÕES (journal.py)
================================================================================
Registro único de operações que gravam tags em MP3, com desfazer (undo).

Como funciona: antes de gravar, guarda-se o bloco ID3v2 original do arquivo.
O áudio em si nunca é alterado pela escrita de tags, então restaurar o bloco
ID3 anterior devolve o arquivo ao estado exato de antes.

Banco: ~/.serato_sync_journal.sqlite
Limitações: cobre gravações de tags em MP3. Renomeações e alterações em FLAC/M4A
não são registradas aqui (ver backups específicos de cada módulo).
================================================================================
"""

import os
import sys

sys.dont_write_bytecode = True
import json
import shutil
import sqlite3
import hashlib
import argparse
from datetime import datetime
from pathlib import Path

def get_journal_path() -> Path:
    global JOURNAL_PATH
    if "JOURNAL_PATH" in globals() and JOURNAL_PATH is not None:
        p_val = Path(JOURNAL_PATH).resolve()
        default_home = (Path.home() / ".serato_sync_journal.sqlite").resolve()
        fallback_proj = (Path(__file__).resolve().parent / ".serato_sync_journal.sqlite").resolve()
        if p_val != default_home and p_val != fallback_proj:
            return p_val
    env_p = os.environ.get("SERATO_JOURNAL_PATH")
    if env_p:
        p = Path(env_p).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    default_p = Path.home() / ".serato_sync_journal.sqlite"
    try:
        default_p.parent.mkdir(parents=True, exist_ok=True)
        test_file = default_p.parent / f".serato_perm_{os.getpid()}"
        test_file.touch()
        test_file.unlink()
        return default_p
    except Exception:
        fallback = Path(__file__).resolve().parent / ".serato_sync_journal.sqlite"
        try:
            fallback.parent.mkdir(parents=True, exist_ok=True)
            return fallback
        except Exception:
            import tempfile
            return Path(tempfile.gettempdir()) / ".serato_sync_journal.sqlite"


JOURNAL_PATH = get_journal_path()


def calc_file_sha256(filepath: str) -> str:
    """Calcula o SHA-256 integral do arquivo."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def calc_audio_tail_sha256(filepath: str) -> str:
    """Calcula o SHA-256 da porção de áudio puro ignorando o bloco ID3v2 inicial."""
    _, id3_len = read_leading_id3(filepath)
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        f.seek(id3_len)
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_journal_db():
    p = get_journal_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=15.0)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            criado_em TEXT NOT NULL,
            acao TEXT NOT NULL,
            arquivo TEXT NOT NULL,
            id3_anterior BLOB,
            desfeita INTEGER NOT NULL DEFAULT 0,
            hash_anterior TEXT,
            hash_posterior TEXT,
            audio_tail_hash TEXT
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ops_arquivo ON operacoes(arquivo);")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crate_operacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            criado_em TEXT NOT NULL,
            acao TEXT NOT NULL,
            crate_path TEXT NOT NULL,
            hash_anterior TEXT,
            hash_posterior TEXT,
            backup_path TEXT,
            total_tracks INTEGER,
            desfeita INTEGER DEFAULT 0
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_crate_ops_path ON crate_operacoes(crate_path);")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_operacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iniciado_em TEXT NOT NULL,
            finalizado_em TEXT,
            mp3_dir TEXT NOT NULL,
            serato_dir TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 0,
            estado TEXT NOT NULL,
            sucesso INTEGER,
            fases_json TEXT,
            erros_json TEXT,
            detalhes_json TEXT
        );
    """)
    # Migração idempotente de colunas se a tabela já existir em versão legada
    for col in ["hash_anterior", "hash_posterior", "audio_tail_hash"]:
        try:
            conn.execute(f"ALTER TABLE operacoes ADD COLUMN {col} TEXT;")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def record_sync_start(mp3_dir: str, serato_dir: str, dry_run: bool = False) -> int:
    """Registra o início de uma operação de sincronização no journal."""
    conn = get_journal_db()
    with conn:
        cur = conn.execute(
            """INSERT INTO sync_operacoes
               (iniciado_em, mp3_dir, serato_dir, dry_run, estado, fases_json, erros_json)
               VALUES (?, ?, ?, ?, 'iniciado', '[]', '[]')""",
            (datetime.now().isoformat(timespec='seconds'), str(mp3_dir), str(serato_dir), 1 if dry_run else 0)
        )
        sync_id = cur.lastrowid
    conn.close()
    return sync_id


def record_sync_step(sync_id, fase: str, status: str, detalhes: str = None):
    """Registra a transição/resultado de uma fase da sincronização no journal."""
    if not sync_id:
        return
    conn = get_journal_db()
    with conn:
        row = conn.execute("SELECT fases_json FROM sync_operacoes WHERE id = ?", (int(sync_id),)).fetchone()
        fases = []
        if row and row[0]:
            try:
                fases = json.loads(row[0])
            except Exception:
                fases = []
        fases.append({
            "timestamp": datetime.now().isoformat(timespec='seconds'),
            "fase": fase,
            "status": status,
            "detalhes": detalhes,
        })
        conn.execute(
            "UPDATE sync_operacoes SET estado = ?, fases_json = ? WHERE id = ?",
            (f"{fase}:{status}", json.dumps(fases, ensure_ascii=False), int(sync_id))
        )
    conn.close()


def record_sync_finish(sync_id, sucesso: bool, estado: str, erros: list = None, detalhes: dict = None):
    """Registra o resultado final e eventuais erros da sincronização no journal."""
    if not sync_id:
        return
    conn = get_journal_db()
    with conn:
        conn.execute(
            """UPDATE sync_operacoes
               SET finalizado_em = ?, estado = ?, sucesso = ?, erros_json = ?, detalhes_json = ?
               WHERE id = ?""",
            (
                datetime.now().isoformat(timespec='seconds'),
                estado,
                1 if sucesso else 0,
                json.dumps(erros or [], ensure_ascii=False),
                json.dumps(detalhes or {}, ensure_ascii=False),
                int(sync_id),
            )
        )
    conn.close()


def record_crate_operation(crate_path: str, acao: str, hash_anterior: str = None,
                           hash_posterior: str = None, backup_path: str = None,
                           total_tracks: int = 0) -> int:
    """Registra uma operação de modificação de crate no journal."""
    conn = get_journal_db()
    with conn:
        cur = conn.execute(
            """INSERT INTO crate_operacoes
               (criado_em, acao, crate_path, hash_anterior, hash_posterior, backup_path, total_tracks, desfeita)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (datetime.now().isoformat(timespec='seconds'), acao, str(crate_path),
             hash_anterior, hash_posterior, backup_path, int(total_tracks))
        )
        op_id = cur.lastrowid
    conn.close()
    return op_id


def read_leading_id3(filepath):
    """Retorna (bytes do bloco ID3v2 inicial ou b'', tamanho do bloco)."""
    with open(filepath, 'rb') as f:
        header = f.read(10)
        if len(header) < 10 or header[:3] != b'ID3':
            return b'', 0
        size = ((header[6] & 0x7F) << 21) | ((header[7] & 0x7F) << 14) | ((header[8] & 0x7F) << 7) | (header[9] & 0x7F)
        total = 10 + size
        if header[5] & 0x10:
            total += 10
        f.seek(0)
        return f.read(total), total


def record_id3_before_change(filepath, action="alteracao_tags"):
    """Grava no journal o bloco ID3 atual e hash do arquivo. Chamar ANTES de salvar tags."""
    path = str(Path(filepath).resolve())
    block, _ = read_leading_id3(path)
    hash_ant = calc_file_sha256(path) if Path(path).exists() else None
    audio_tail = calc_audio_tail_sha256(path) if Path(path).exists() else None

    conn = get_journal_db()
    with conn:
        cur = conn.execute(
            """INSERT INTO operacoes
               (criado_em, acao, arquivo, id3_anterior, desfeita, hash_anterior, hash_posterior, audio_tail_hash)
               VALUES (?, ?, ?, ?, 0, ?, NULL, ?)""",
            (datetime.now().isoformat(timespec='seconds'), action, path, sqlite3.Binary(block), hash_ant, audio_tail),
        )
        op_id = cur.lastrowid
    conn.close()
    return op_id


def record_operation_after(op_id, filepath=None):
    """Sela a operação gravando o hash final do arquivo após a conclusão com sucesso."""
    p_db = get_journal_path()
    if not op_id:
        raise ValueError("Identificador de operação inválido para selar Journal.")
    if not p_db.exists():
        raise FileNotFoundError(f"Banco de Journal não encontrado: {p_db}")
    conn = get_journal_db()
    try:
        with conn:
            row = conn.execute("SELECT arquivo FROM operacoes WHERE id = ?", (int(op_id),)).fetchone()
            if not row:
                raise KeyError(f"Operação #{op_id} não localizada no Journal.")
            p = filepath if filepath else row[0]
            if not p or not Path(p).exists():
                raise FileNotFoundError(f"Arquivo pós-operação ausente no disco: {p}")
            hash_post = calc_file_sha256(str(Path(p).resolve()))
            if not hash_post:
                raise IOError(f"Falha ao calcular SHA-256 pós-operação para: {p}")
            cur = conn.execute("UPDATE operacoes SET hash_posterior = ? WHERE id = ?", (hash_post, int(op_id)))
            if cur.rowcount != 1:
                raise IOError(f"Não foi possível atualizar hash_posterior da operação #{op_id}.")
        return True
    finally:
        conn.close()


def validate_undo_state(operation, current_hash):
    """Valida estritamente se o estado atual do arquivo corresponde ao hash_post da operação."""
    hash_post = operation.get("hash_post") or operation.get("hash_posterior")
    if not hash_post:
        raise ValueError("Undo bloqueado: hash posterior ausente")
    if current_hash != hash_post:
        raise ValueError("Undo bloqueado: arquivo foi modificado externamente")
    return True


def list_operations(limit=200, only_active=False):
    p_db = get_journal_path()
    if not p_db.exists():
        return {"sucesso": True, "total": 0, "items": []}
    conn = get_journal_db()
    query = "SELECT id, criado_em, acao, arquivo, desfeita, LENGTH(id3_anterior), hash_anterior, hash_posterior FROM operacoes"
    if only_active:
        query += " WHERE desfeita = 0"
    query += " ORDER BY id DESC LIMIT ?"
    rows = conn.execute(query, (max(1, int(limit)),)).fetchall()
    conn.close()
    items = [{
        "id": r[0],
        "criado_em": r[1],
        "acao": r[2],
        "arquivo": r[3],
        "nome": Path(r[3]).name,
        "desfeita": bool(r[4]),
        "tinha_id3": bool(r[5]),
        "hash_anterior": r[6],
        "hash_posterior": r[7],
    } for r in rows]
    return {"sucesso": True, "total": len(items), "items": items}


def undo_operation(op_id=None):
    """
    Desfaz uma operação de forma estritamente ordenada e segura.
    Sem op_id, desfaz a mais recente ainda ativa.
    Valida:
      1. Se há operações posteriores ativas para o mesmo arquivo (bloqueia undo fora de ordem).
      2. Se o hash do arquivo atual confere com o estado pós-operação (bloqueia se modificado externamente).
      3. Se o áudio puro permanece intacto.
    Restaura o bloco ID3 anterior preservando o áudio byte a byte e substitui atomicamente.
    """
    p_db = get_journal_path()
    if not p_db.exists():
        return {"sucesso": False, "erro": "Nenhuma operação registrada"}
    conn = get_journal_db()
    if op_id is None:
        row = conn.execute(
            """SELECT id, arquivo, id3_anterior, hash_anterior, hash_posterior, audio_tail_hash
               FROM operacoes WHERE desfeita = 0 ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT id, arquivo, id3_anterior, hash_anterior, hash_posterior, audio_tail_hash
               FROM operacoes WHERE id = ? AND desfeita = 0""", (int(op_id),)
        ).fetchone()

    if row is None:
        conn.close()
        return {"sucesso": False, "erro": "Nenhuma operação disponível para desfazer"}

    op, arquivo, anterior, hash_ant, hash_post, tail_hash = row
    anterior = bytes(anterior or b'')
    path = Path(arquivo)

    # 1. Trava estrita contra Undo fora de ordem (apenas a operação ativa mais recente do arquivo pode ser desfeita)
    newer_op = conn.execute(
        "SELECT id FROM operacoes WHERE arquivo = ? AND desfeita = 0 AND id > ? ORDER BY id DESC LIMIT 1",
        (arquivo, op)
    ).fetchone()
    conn.close()

    if newer_op is not None:
        return {
            "sucesso": False,
            "erro": f"Tentativa de Undo fora de ordem: a operação #{newer_op[0]} é mais recente e ainda está ativa para este arquivo. Desfaça as operações posteriores primeiro."
        }

    if not path.exists():
        return {"sucesso": False, "erro": "Arquivo não encontrado no disco; não é possível desfazer"}

    # 2. Verificação de integridade do estado atual do arquivo
    curr_hash = calc_file_sha256(str(path))

    # Se já está no estado anterior exato, apenas marca como desfeita
    if hash_ant and curr_hash == hash_ant:
        conn = get_journal_db()
        with conn:
            conn.execute("UPDATE operacoes SET desfeita = 1 WHERE id = ?", (op,))
        conn.close()
        return {"sucesso": True, "id": op, "arquivo": path.name, "mensagem": "Arquivo já se encontrava no estado original."}

    # Validação estrita: hash_post é obrigatório (nunca pular validação se ausente)
    try:
        validate_undo_state({"hash_post": hash_post}, curr_hash)
    except ValueError as e_val:
        err_str = str(e_val)
        if "modificado externamente" in err_str:
            err_msg = "O arquivo foi modificado externamente ou por outra operação após este registro. Undo recusado para evitar perda de dados."
        else:
            err_msg = f"{err_str}. Undo recusado para evitar sobrescrita insegura."
        return {
            "sucesso": False,
            "erro": err_msg
        }

    # Valida também integridade da cauda de áudio (não deve ter sido corrompida)
    if tail_hash:
        curr_tail = calc_audio_tail_sha256(str(path))
        if curr_tail != tail_hash:
            return {
                "sucesso": False,
                "erro": "O fluxo de áudio do arquivo foi alterado ou corrompido externamente. Undo cancelado por segurança."
            }

    # 3. Restauração atômica do bloco ID3 com arquivo temporário
    tmp = path.with_name(f".tmp_undo_{path.name}_{op}")
    try:
        _, atual_len = read_leading_id3(str(path))
        with open(path, 'rb') as src, open(tmp, 'wb') as dst:
            dst.write(anterior)
            src.seek(atual_len)
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())

        # Validação pós-reconstituição temporária
        if not tmp.exists() or tmp.stat().st_size < len(anterior):
            raise IOError("Arquivo temporário de restauração incompleto.")

        os.replace(str(tmp), str(path))
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        return {"sucesso": False, "erro": "Falha ao desfazer: %s" % e}

    conn = get_journal_db()
    with conn:
        conn.execute("UPDATE operacoes SET desfeita = 1 WHERE id = ?", (op,))
    conn.close()
    return {"sucesso": True, "id": op, "arquivo": path.name, "mensagem": "Alteração desfeita e tags restauradas."}


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Journal de alterações")
    parser.add_argument("--list", action="store_true", help="Lista operações registradas")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--undo", nargs="?", const="__last__", default=None, help="Desfaz a última ou um ID específico")
    args = parser.parse_args()

    if args.list:
        print(json.dumps(list_operations(limit=args.limit), ensure_ascii=False), flush=True)
        sys.exit(0)
    if args.undo is not None:
        op = None if args.undo == "__last__" else int(args.undo)
        res = undo_operation(op)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)
    parser.print_help()


if __name__ == "__main__":
    main()
