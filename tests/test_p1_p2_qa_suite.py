import json
import os
import shutil
import sqlite3
import struct
import sys
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import crate_ops
import journal
import serato_macos_app


def _make_audio(path: Path, content: bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00FAKE_MP3_AUDIO") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _make_valid_crate(path: Path, tracks: List[str], extra_blocks: Optional[List[bytes]] = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000"
    payload = bytearray(header)
    for blk in (extra_blocks or []):
        payload.extend(blk)
    for rel in tracks:
        ptrk = crate_ops.criar_tag_tlv("ptrk", rel)
        payload.extend(b"otrk" + struct.pack(">I", len(ptrk)) + ptrk)
    path.write_bytes(bytes(payload))
    return path


# ==============================================================================
# 1. PARSER E CRATES
# ==============================================================================

def test_parser_crate_valido(tmp_path):
    crate_file = _make_valid_crate(tmp_path / "House.crate", ["Music/Track1.mp3", "Music/Track2.mp3"])
    hdr, tracks, track_blocks, outros = crate_ops.parse_crate_binary(crate_file.read_bytes())
    assert hdr is not None
    assert tracks == ["Music/Track1.mp3", "Music/Track2.mp3"]
    assert len(track_blocks) == 2
    assert outros == []


def test_parser_crate_vazio(tmp_path):
    hdr, tracks, _, _ = crate_ops.parse_crate_binary(b"")
    assert hdr is None
    assert tracks == []
    empty_file = tmp_path / "Empty.crate"
    empty_file.write_bytes(b"")
    with pytest.raises(ValueError):
        crate_ops.read_and_validate_crate(empty_file)


def test_parser_crate_truncado(tmp_path):
    truncated = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000otrk\x00\x00\x00\x20"
    hdr, _, _, _ = crate_ops.parse_crate_binary(truncated)
    assert hdr is None
    trunc_file = tmp_path / "Trunc.crate"
    trunc_file.write_bytes(truncated)
    with pytest.raises(ValueError):
        crate_ops.read_and_validate_crate(trunc_file)


def test_parser_bloco_interno_invalido(tmp_path):
    # otrk com sub-bloco ptrk truncado
    bad = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000otrk\x00\x00\x00\x06ptrk\x00\x00"
    hdr, _, _, _ = crate_ops.parse_crate_binary(bad)
    assert hdr is None
    bad_file = tmp_path / "BadBlock.crate"
    bad_file.write_bytes(bad)
    with pytest.raises(ValueError):
        crate_ops.read_and_validate_crate(bad_file)


def test_parser_estrutura_desconhecida_preservada():
    unknown_blk = b"osrt" + struct.pack(">I", 4) + b"\x00\x01\x02\x03"
    ptrk = crate_ops.criar_tag_tlv("ptrk", "Music/A.mp3")
    raw = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000" + unknown_blk + b"otrk" + struct.pack(">I", len(ptrk)) + ptrk
    hdr, tracks, _, outros = crate_ops.parse_crate_binary(raw)
    assert hdr is not None
    assert tracks == ["Music/A.mp3"]
    assert outros == [unknown_blk]


def test_parser_arquivo_inexistente(tmp_path):
    missing = tmp_path / "nao_existe.crate"
    f_set, f_ord, outros, hdr = serato_macos_app.ler_faixas_crate_binaria(missing)
    assert f_set == set()
    assert f_ord == []
    assert outros == []
    assert hdr is None
    with pytest.raises(FileNotFoundError):
        crate_ops.read_and_validate_crate(missing)


# ==============================================================================
# 2. BACKUP, GRAVAÇÃO E ROLLBACK ATÔMICO
# ==============================================================================

def test_backup_e_gravacao_sucesso(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    crate_file = _make_valid_crate(tmp_path / "Techno.crate", ["Music/Old.mp3"])
    res = crate_ops.write_crate_atomic(crate_file, ["Music/New.mp3"], action_name="test_ok")
    assert res["sucesso"] is True
    assert Path(res["backup"]).exists()
    _, tracks, _, _ = crate_ops.parse_crate_binary(crate_file.read_bytes())
    assert tracks == ["Music/New.mp3"]


def test_falha_criacao_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    crate_file = _make_valid_crate(tmp_path / "Techno.crate", ["Music/Old.mp3"])
    orig_bytes = crate_file.read_bytes()

    with patch("crate_ops.shutil.copy2", side_effect=PermissionError("Sem permissão")):
        res = crate_ops.write_crate_atomic(crate_file, ["Music/New.mp3"])
    assert res["sucesso"] is False
    assert crate_file.read_bytes() == orig_bytes


def test_falha_validacao_sha256_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    crate_file = _make_valid_crate(tmp_path / "Techno.crate", ["Music/Old.mp3"])
    hashes = iter(["hash_original", "hash_divergente"])
    monkeypatch.setattr(crate_ops, "calc_crate_sha256", lambda _: next(hashes))
    res = crate_ops.write_crate_atomic(crate_file, ["Music/New.mp3"])
    assert res["sucesso"] is False
    assert "SHA-256" in res["erro"]


def test_falha_gravacao_temporaria(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    crate_file = _make_valid_crate(tmp_path / "Techno.crate", ["Music/Old.mp3"])
    orig_bytes = crate_file.read_bytes()

    with patch("crate_ops.os.fsync", side_effect=[OSError("Disk I/O error"), None]):
        res = crate_ops.write_crate_atomic(crate_file, ["Music/New.mp3"])
    assert res["sucesso"] is False
    assert res["rollback_confirmado"] is True
    assert crate_file.read_bytes() == orig_bytes


def test_falha_substituicao_atomica_e_rollback_confirmado(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    crate_file = _make_valid_crate(tmp_path / "Techno.crate", ["Music/Old.mp3"])
    orig_hash = crate_ops.calc_crate_sha256(crate_file)

    real_replace = os.replace
    calls = {"n": 0}

    def fail_first_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("Simulated atomic replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(crate_ops.os, "replace", fail_first_replace)
    res = crate_ops.write_crate_atomic(crate_file, ["Music/New.mp3"])

    assert res["sucesso"] is False
    assert res["rollback_confirmado"] is True
    assert crate_ops.calc_crate_sha256(crate_file) == orig_hash
    assert Path(res["backup"]).exists()


def test_falha_journal_dispara_rollback_confirmado(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    crate_file = _make_valid_crate(tmp_path / "Techno.crate", ["Music/Old.mp3"])
    orig_hash = crate_ops.calc_crate_sha256(crate_file)

    monkeypatch.setattr(
        journal,
        "record_crate_operation",
        lambda **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )
    res = crate_ops.write_crate_atomic(crate_file, ["Music/New.mp3"])
    assert res["sucesso"] is False
    assert res["rollback_confirmado"] is True
    assert crate_ops.calc_crate_sha256(crate_file) == orig_hash


def test_rollback_nao_confirmado_sinaliza_recuperacao_manual(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    crate_file = _make_valid_crate(tmp_path / "Techno.crate", ["Music/Old.mp3"])

    monkeypatch.setattr(
        journal,
        "record_crate_operation",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("Journal down")),
    )
    monkeypatch.setattr(
        crate_ops,
        "restore_crate_from_backup_atomic",
        lambda *args, **kwargs: (False, "ALERTA CRÍTICO: Falha no rollback. Recuperação manual necessária."),
    )
    res = crate_ops.write_crate_atomic(crate_file, ["Music/New.mp3"])
    assert res["sucesso"] is False
    assert res["rollback_confirmado"] is False
    assert "Recuperação manual necessária" in res["erro"]


# ==============================================================================
# 3. SINCRONIZAÇÃO TRANSACIONAL (P1)
# ==============================================================================

def _setup_library(tmp_path: Path, folders: list[str]):
    mp3_dir = tmp_path / "MP3"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "Logs"
    (serato_dir / "Subcrates").mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    for folder in folders:
        _make_audio(mp3_dir / folder / f"{folder}_track.mp3")
    return mp3_dir, serato_dir, logs_dir


def test_sync_completa_e_journal(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_dir, serato_dir, logs_dir = _setup_library(tmp_path, ["A_House", "B_Tech", "C_Funk"])

    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False
    )
    assert ok is True
    assert resumo["sucesso"] is True
    assert resumo["crates_gravadas"] == 3
    assert (serato_dir / "neworder.pref").exists()
    assert (logs_dir / ".serato_sync_cache.json").exists()

    conn = sqlite3.connect(str(j_path))
    row = conn.execute("SELECT estado, sucesso FROM sync_operacoes ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row == ("completo", 1)


@pytest.mark.parametrize("fail_index", [0, 1, 2])
def test_sync_falha_em_crate_preserva_antigos_pref_e_cache(tmp_path, monkeypatch, capsys, fail_index):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir, serato_dir, logs_dir = _setup_library(tmp_path, ["01_Alpha", "02_Beta", "03_Gamma"])

    # Crate antiga que deveria ser removida apenas se o sync inteiro tivesse sucesso
    old_crate = _make_valid_crate(serato_dir / "Subcrates" / "99_Obsoleta.crate", ["Old/Track.mp3"])
    pref_file = serato_dir / "neworder.pref"
    pref_orig = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000"
    pref_file.write_bytes(pref_orig)
    cache_file = logs_dir / ".serato_sync_cache.json"
    cache_orig = json.dumps({"__meta__": {"lib_path": str(mp3_dir.resolve())}, "crates": {}})
    cache_file.write_text(cache_orig, encoding="utf-8")

    real_write = crate_ops.write_crate_atomic
    counter = {"n": 0}

    def failing_write(crate_path, *args, **kwargs):
        idx = counter["n"]
        counter["n"] += 1
        if idx == fail_index:
            return {"sucesso": False, "rollback_confirmado": True, "erro": f"Erro simulado no crate #{idx + 1}"}
        return real_write(crate_path, *args, **kwargs)

    monkeypatch.setattr(crate_ops, "write_crate_atomic", failing_write)

    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False
    )
    out = capsys.readouterr().out

    assert ok is False
    assert resumo["sucesso"] is False
    assert len(resumo["erros_gravacao"]) >= 1
    assert old_crate.exists(), "Crate antiga não pode ser excluída após falha"
    assert pref_file.read_bytes() == pref_orig, "neworder.pref deve permanecer preservado"
    assert cache_file.read_text(encoding="utf-8") == cache_orig, "Cache deve permanecer preservado"
    assert "Sincronização concluída com sucesso" not in out


def test_sync_falha_exclusao_crate_antigo(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir, serato_dir, logs_dir = _setup_library(tmp_path, ["01_Alpha"])
    old_crate_1 = _make_valid_crate(serato_dir / "Subcrates" / "98_Obsoleta1.crate", ["Old/Track1.mp3"])
    old_crate_2 = _make_valid_crate(serato_dir / "Subcrates" / "99_Obsoleta2.crate", ["Old/Track2.mp3"])
    cache_file = logs_dir / ".serato_sync_cache.json"

    real_replace = os.replace

    def fail_second_staging_move(src, dst):
        if Path(src).name == "99_Obsoleta2.crate" and ".staging_delete_" in str(dst):
            raise PermissionError("Locked crate 2")
        return real_replace(src, dst)

    monkeypatch.setattr(serato_macos_app.os, "replace", fail_second_staging_move)
    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False
    )
    assert ok is False
    assert old_crate_1.exists(), "Primeira crate antiga deve ser restaurada do staging"
    assert old_crate_2.exists(), "Segunda crate antiga deve permanecer intacta"
    assert not (serato_dir / "Subcrates" / "01_Alpha.crate").exists(), "Crate nova deve sofrer rollback"
    assert not cache_file.exists()


def test_sync_falha_neworder_pref(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir, serato_dir, logs_dir = _setup_library(tmp_path, ["01_Alpha"])
    old_crate = _make_valid_crate(serato_dir / "Subcrates" / "99_Obsoleta.crate", ["Old/Track.mp3"])
    pref_file = serato_dir / "neworder.pref"
    pref_orig = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000"
    pref_file.write_bytes(pref_orig)
    cache_file = logs_dir / ".serato_sync_cache.json"

    real_replace = os.replace

    def fail_pref_replace(src, dst):
        if Path(dst).name == "neworder.pref":
            raise OSError("Pref write error")
        return real_replace(src, dst)

    monkeypatch.setattr(serato_macos_app.os, "replace", fail_pref_replace)
    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False
    )
    assert ok is False
    assert old_crate.exists(), "Crate antiga deve ser restaurada do staging se neworder.pref falhar"
    assert pref_file.read_bytes() == pref_orig
    assert not (serato_dir / "Subcrates" / "01_Alpha.crate").exists()
    assert not cache_file.exists()


def test_sync_falha_atualizacao_cache(tmp_path, monkeypatch):
    """Simula falha real de escrita DENTRO de salvar_cache() original e valida rollback integral."""
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir, serato_dir, logs_dir = _setup_library(tmp_path, ["01_Alpha"])
    old_crate = _make_valid_crate(serato_dir / "Subcrates" / "99_Obsoleta.crate", ["Old/Track.mp3"])
    pref_file = serato_dir / "neworder.pref"
    pref_orig = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000"
    pref_file.write_bytes(pref_orig)

    cache_file = logs_dir / ".serato_sync_cache.json"
    cache_orig = json.dumps({"_meta": {"lib_path": str(mp3_dir.resolve())}, "crates": {"old": 1}})
    cache_file.write_text(cache_orig, encoding="utf-8")

    real_replace = os.replace

    def fail_cache_replace(src, dst):
        if Path(dst).name == ".serato_sync_cache.json":
            raise OSError("Simulated disk failure inside salvar_cache")
        return real_replace(src, dst)

    monkeypatch.setattr(serato_macos_app.os, "replace", fail_cache_replace)
    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False
    )
    assert ok is False
    assert resumo["sucesso"] is False
    assert cache_file.read_text(encoding="utf-8") == cache_orig, "Cache original deve ser preservado"
    assert pref_file.read_bytes() == pref_orig, "neworder.pref deve ser revertido"
    assert old_crate.exists(), "Crate antiga deve ser restaurada do staging"
    assert not (serato_dir / "Subcrates" / "01_Alpha.crate").exists(), "Crate nova deve sofrer rollback"


def test_sync_broken_symlink_preservado_em_falha_e_removido_em_sucesso(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir, serato_dir, logs_dir = _setup_library(tmp_path, ["01_Alpha"])
    broken_link = mp3_dir / "01_Alpha" / "broken_track.mp3"
    os.symlink(str(tmp_path / "nao_existe.mp3"), str(broken_link))
    assert broken_link.is_symlink()

    # 1. Em caso de falha na gravação, o symlink quebrado NÃO pode ser removido antes da confirmação
    monkeypatch.setattr(
        crate_ops,
        "write_crate_atomic",
        lambda *a, **kw: {"sucesso": False, "rollback_confirmado": True, "erro": "Falha simulada"},
    )
    ok_fail, _ = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False
    )
    assert ok_fail is False
    assert broken_link.is_symlink(), "Symlink quebrado não deve ser removido se a transação falhar"


def test_smart_crate_plano_imutavel_previa_e_execucao(tmp_path, monkeypatch):
    import library_tools

    monkeypatch.setattr(library_tools, "SMART_RULES_PATH", tmp_path / "smart_rules.json")
    monkeypatch.setattr(library_tools, "library_root_for", lambda _: tmp_path)
    mp3_dir = tmp_path / "MP3"
    serato_dir = tmp_path / "_Serato_"
    (serato_dir / "Subcrates").mkdir(parents=True, exist_ok=True)
    track1 = _make_audio(mp3_dir / "House" / "track1.mp3", b"ID3\x03\x00\x00\x00\x00\x00\x00AUDIO_1")

    # 1. Gera prévia (plano imutável)
    prev = library_tools.create_smart_crate(str(mp3_dir), str(serato_dir), "MinhaSmart", {}, dry_run=True)
    assert prev["sucesso"] is True
    assert prev["total"] == 1
    plano = prev["plano"]
    assert plano["caminhos"] == ["MP3/House/track1.mp3"]
    assert plano["plan_id"]
    assert plano["plan_hash"]

    # 2. Adiciona uma segunda faixa no disco DEPOIS da prévia — execução com plano deve gravar APENAS a da prévia
    _make_audio(mp3_dir / "House" / "track2_nova.mp3", b"ID3\x03\x00\x00\x00\x00\x00\x00AUDIO_2")
    res_exec = library_tools.create_smart_crate(
        str(mp3_dir), str(serato_dir), "MinhaSmart", {}, dry_run=False, plan=plano
    )
    assert res_exec["sucesso"] is True
    assert res_exec["plan_id"] == plano["plan_id"]
    crate_path = serato_dir / "Subcrates" / "MinhaSmart.crate"
    _, tracks, _, _ = crate_ops.parse_crate_binary(crate_path.read_bytes())
    assert len(tracks) == 1

    # 3. Plano adulterado (regras diferentes do hash) deve ser recusado
    bad_exec = library_tools.create_smart_crate(
        str(mp3_dir), str(serato_dir), "MinhaSmart", {"bpm_min": 120}, dry_run=False, plan=plano
    )
    assert bad_exec["sucesso"] is False
    assert "Plano" in bad_exec["erro"]


def test_sync_dry_run_nao_altera_filesystem(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_dir = tmp_path / "MP3"
    _make_audio(mp3_dir / "01_Alpha" / "track.mp3")
    serato_dir = tmp_path / "_Serato_Fresh"
    logs_dir = tmp_path / "Logs_Fresh"

    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=True, dry_run=True
    )
    assert ok is True
    assert resumo["dry_run"] is True
    assert not serato_dir.exists()
    assert not logs_dir.exists()
    assert not j_path.exists()


def test_sync_varredura_incompleta_bloqueia_gravacao(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir, serato_dir, logs_dir = _setup_library(tmp_path, ["01_Alpha"])
    old_crate = _make_valid_crate(serato_dir / "Subcrates" / "99_Obsoleta.crate", ["Old/Track.mp3"])

    def bad_walk(top, onerror=None):
        if onerror:
            onerror(PermissionError("Denied"))
        return iter([])

    monkeypatch.setattr(serato_macos_app.os, "walk", bad_walk)
    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False
    )
    assert ok is False
    assert old_crate.exists()
    assert not (serato_dir / "Subcrates" / "01_Alpha.crate").exists()
