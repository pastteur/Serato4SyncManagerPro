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
import json
import shutil
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path

JOURNAL_PATH = Path.home() / ".serato_sync_journal.sqlite"


def get_journal_db():
    conn = sqlite3.connect(str(JOURNAL_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            criado_em TEXT NOT NULL,
            acao TEXT NOT NULL,
            arquivo TEXT NOT NULL,
            id3_anterior BLOB,
            desfeita INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ops_arquivo ON operacoes(arquivo);")
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
    """Grava no journal o bloco ID3 atual do arquivo. Chamar ANTES de salvar tags."""
    path = str(Path(filepath).resolve())
    block, _ = read_leading_id3(path)
    conn = get_journal_db()
    with conn:
        cur = conn.execute(
            "INSERT INTO operacoes (criado_em, acao, arquivo, id3_anterior, desfeita) VALUES (?, ?, ?, ?, 0)",
            (datetime.now().isoformat(timespec='seconds'), action, path, sqlite3.Binary(block)),
        )
        op_id = cur.lastrowid
    conn.close()
    return op_id


def list_operations(limit=200, only_active=False):
    if not JOURNAL_PATH.exists():
        return {"sucesso": True, "total": 0, "items": []}
    conn = get_journal_db()
    query = "SELECT id, criado_em, acao, arquivo, desfeita, LENGTH(id3_anterior) FROM operacoes"
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
    } for r in rows]
    return {"sucesso": True, "total": len(items), "items": items}


def undo_operation(op_id=None):
    """
    Desfaz uma operação. Sem op_id, desfaz a mais recente ainda ativa.
    Restaura o bloco ID3 anterior preservando o áudio byte a byte.
    """
    if not JOURNAL_PATH.exists():
        return {"sucesso": False, "erro": "Nenhuma operação registrada"}
    conn = get_journal_db()
    if op_id is None:
        row = conn.execute(
            "SELECT id, arquivo, id3_anterior FROM operacoes WHERE desfeita = 0 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, arquivo, id3_anterior FROM operacoes WHERE id = ? AND desfeita = 0", (int(op_id),)
        ).fetchone()
    conn.close()
    if row is None:
        return {"sucesso": False, "erro": "Nenhuma operação disponível para desfazer"}

    op, arquivo, anterior = row
    anterior = bytes(anterior or b'')
    path = Path(arquivo)
    if not path.exists():
        return {"sucesso": False, "erro": "Arquivo não encontrado no disco; não é possível desfazer"}

    tmp = path.with_name(path.name + ".undo_tmp")
    try:
        _, atual_len = read_leading_id3(str(path))
        with open(path, 'rb') as src, open(tmp, 'wb') as dst:
            dst.write(anterior)
            src.seek(atual_len)
            shutil.copyfileobj(src, dst, 1024 * 1024)
        os.replace(str(tmp), str(path))
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
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
        print(json.dumps(list_operations(limit=args.limit), ensure_ascii=False))
        sys.exit(0)
    if args.undo is not None:
        op = None if args.undo == "__last__" else int(args.undo)
        res = undo_operation(op)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)
    parser.print_help()


if __name__ == "__main__":
    main()
