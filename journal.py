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

JOURNAL_PATH = Path.home() / ".serato_sync_journal.sqlite"


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
    conn = sqlite3.connect(str(JOURNAL_PATH))
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
    # Migração idempotente de colunas se a tabela já existir em versão legada
    for col in ["hash_anterior", "hash_posterior", "audio_tail_hash"]:
        try:
            conn.execute(f"ALTER TABLE operacoes ADD COLUMN {col} TEXT;")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


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
    if not op_id or not JOURNAL_PATH.exists():
        return
    conn = get_journal_db()
    with conn:
        row = conn.execute("SELECT arquivo FROM operacoes WHERE id = ?", (int(op_id),)).fetchone()
        if row:
            p = filepath if filepath else row[0]
            if Path(p).exists():
                hash_post = calc_file_sha256(str(Path(p).resolve()))
                conn.execute("UPDATE operacoes SET hash_posterior = ? WHERE id = ?", (hash_post, int(op_id)))
    conn.close()


def list_operations(limit=200, only_active=False):
    if not JOURNAL_PATH.exists():
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
    if not JOURNAL_PATH.exists():
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

    # Se temos o hash registrado do estado gerado pela operação e o arquivo diverge, houve alteração externa
    if hash_post and curr_hash != hash_post:
        return {
            "sucesso": False,
            "erro": "O arquivo foi modificado externamente ou por outra operação após este registro. Undo recusado para evitar perda de dados."
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
