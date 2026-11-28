#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes de regressão para os achados QA-001 a QA-008 da Auditoria QA.
"""

import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
VENDOR_DIR = PROJECT_ROOT / "vendor"
if VENDOR_DIR.is_dir() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

import auto_cue
import crate_ops
import journal
import library_tools
import serato_macos_app
from mutagen.id3 import GEOB, ID3, TBPM, TIT2
from tests.fixtures.acoustic_fixtures import AcousticFixtureGenerator


def _pcm_from_frames(amplitudes):
    buf = bytearray()
    for amp in amplitudes:
        s = max(-32767, min(32767, int(amp)))
        buf.extend(struct.pack("<h", s) * 100)
    return bytes(buf)


# =============================================================================
# QA-001 — Proteção estrita de neworder.pref
# =============================================================================

def test_qa001_parse_neworder_pref_rejects_corrupt_truncated_and_residual_bytes():
    valid_hdr = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000"
    tvcn = serato_macos_app.criar_tag_tlv("tvcn", "House")
    valid_nior = b"nior" + struct.pack(">I", len(tvcn)) + tvcn

    # Válido
    h, crates, outros = serato_macos_app.parse_neworder_pref(valid_hdr + valid_nior, strict=True)
    assert h == valid_hdr
    assert crates == ["House"]
    assert outros == []

    # Cabeçalho inválido / vrsn_len=0
    for bad in (
        b"",
        b"XXXX\x00\x00\x00\x08\x001\x00.\x000\x000",
        b"vrsn\x00\x00\x00\x00",
        b"vrsn\x00\x00\x00\x20short",
        valid_hdr + b"\x01\x02\x03",  # bytes residuais
        valid_hdr + valid_nior + b"\x00\xff",  # bytes residuais após bloco válido
        valid_hdr + valid_nior[:-2],  # bloco truncado
        valid_hdr + b"nior\x00\x00\x00\x04ABCD",  # nior sem tvcn
    ):
        hdr_ns, crates_ns, _ = serato_macos_app.parse_neworder_pref(bad, strict=False)
        assert hdr_ns is None and crates_ns == []
        with pytest.raises(ValueError):
            serato_macos_app.parse_neworder_pref(bad, strict=True)


def test_qa001_sync_preserves_invalid_neworder_pref_and_fails_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir = tmp_path / "MP3" / "House"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"
    mp3_dir.mkdir(parents=True)
    (serato_dir / "Subcrates").mkdir(parents=True)
    logs_dir.mkdir(parents=True)

    AcousticFixtureGenerator.create_tagged_transient_mp3(mp3_dir / "Track.mp3", duration_sec=12.0)

    # neworder.pref inválido com bytes residuais após header válido
    invalid_pref = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000BAD_TRAILING_BYTES"
    pref_path = serato_dir / "neworder.pref"
    pref_path.write_bytes(invalid_pref)

    # 1. Dry Run deve falhar e NÃO gerar plano aprovado
    ok_dry, res_dry = serato_macos_app.sincronizar_biblioteca(
        str(tmp_path / "MP3"), str(serato_dir), str(logs_dir), dry_run=True
    )
    assert ok_dry is False
    assert res_dry["sucesso"] is False
    assert "plan" not in res_dry
    assert any("neworder.pref" in e for e in res_dry["erros_gravacao"])
    assert pref_path.read_bytes() == invalid_pref

    # 2. Execução direta deve falhar e preservar o neworder.pref original intacto
    ok_run, res_run = serato_macos_app.sincronizar_biblioteca(
        str(tmp_path / "MP3"), str(serato_dir), str(logs_dir), dry_run=False
    )
    assert ok_run is False
    assert res_run["sucesso"] is False
    assert any("neworder.pref" in e for e in res_run["erros_gravacao"])
    assert pref_path.read_bytes() == invalid_pref
    assert not (serato_dir / "Subcrates" / "House.crate").exists()


# =============================================================================
# QA-002 — Detecção real de transientes e respeito à confiança
# =============================================================================

def test_qa002_separates_silence_from_onset_and_respects_confidence(tmp_path):
    dummy = tmp_path / "dummy.mp3"
    dummy.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 600)

    # 1. Silêncio inicial de 1.2s seguido de fade-in gradual sem beat/transiente: NÃO confiável
    fade_amps = [0] * 120 + [int(50 + i * 30) for i in range(180)]
    fade_pcm = _pcm_from_frames(fade_amps)
    with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
         patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=fade_pcm, stderr=b"")):
        res_fade = auto_cue.detect_audio_transients(str(dummy), duration_sec=30.0)
    assert res_fade["has_transient"] is False
    assert res_fade["confiavel"] is False
    assert res_fade["first_beat_ms"] is None
    assert res_fade["silence_end_ms"] is not None

    # 2. Pad ambiente suave (0..1.2s a -32dB) seguido de beat/onset forte em 1.2s: detecta 1200ms
    # -32 dB ≈ amplitude ~820; pico forte ≈ amplitude 18000
    pad_beat_pcm = _pcm_from_frames([820] * 120 + [18000] * 80)
    with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
         patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=pad_beat_pcm, stderr=b"")):
        res_beat = auto_cue.detect_audio_transients(str(dummy), duration_sec=30.0)
    assert res_beat["has_transient"] is True
    assert res_beat["confiavel"] is True
    assert res_beat["first_beat_ms"] == 1200
    assert res_beat["silence_end_ms"] == 0

    # 3. FFmpeg indisponível -> não confiável, sem fallback cego, e NÃO gera/grava cues
    with patch("auto_cue.get_ffmpeg_bin", return_value=None):
        res_noff = auto_cue.detect_audio_transients(str(dummy), duration_sec=30.0)
        assert res_noff["confiavel"] is False
        assert res_noff["first_beat_ms"] is None
        assert auto_cue.calculate_smart_cues(30.0, 124.0, filepath_str=str(dummy)) == []

        orig_bytes = dummy.read_bytes()
        save_res = auto_cue.generate_and_save_serato_cues(str(dummy), overwrite_existing=True)
        assert save_res["sucesso"] is False
        assert save_res["confiavel"] is False
        assert dummy.read_bytes() == orig_bytes


def test_qa002_preview_cli_exposes_confidence_and_blocks_inconclusive(tmp_path):
    silent = tmp_path / "silent.mp3"
    silent.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 600)
    proc_fail = subprocess.run(
        [sys.executable, "auto_cue.py", "--preview", str(silent)],
        capture_output=True, text=True, check=False,
    )
    assert proc_fail.returncode != 0
    data_fail = json.loads(proc_fail.stdout.strip())
    assert data_fail["sucesso"] is False
    assert data_fail["confiavel"] is False
    assert data_fail["cues"] == []

    real = tmp_path / "real.mp3"
    AcousticFixtureGenerator.create_tagged_transient_mp3(real, duration_sec=13.0, silence_sec=0.5)
    proc_ok = subprocess.run(
        [sys.executable, "auto_cue.py", "--preview", str(real)],
        capture_output=True, text=True, check=False,
    )
    assert proc_ok.returncode == 0
    data_ok = json.loads(proc_ok.stdout.strip())
    assert data_ok["sucesso"] is True
    assert data_ok["confiavel"] is True
    assert data_ok["confianca"] >= 0.60
    assert len(data_ok["cues"]) == 5


# =============================================================================
# QA-003 — Classificação criteriosa de cues personalizados (cores, índices, etc.)
# =============================================================================

def test_qa003_custom_colors_or_indices_classified_as_custom_dj(tmp_path):
    crate_dir = tmp_path / "MP3" / "CustomTest"
    crate_dir.mkdir(parents=True)
    track = crate_dir / "CustomColorTrack.mp3"
    AcousticFixtureGenerator.create_tagged_transient_mp3(track, duration_sec=14.0)

    # 5 marcadores com rótulos padrão e índices 0..4, mas CORES PERSONALIZADAS
    custom_cues = [
        {"index": 0, "label": "Intro", "pos_ms": 500, "color": b"\x99\x00\xcc"},  # roxo em vez de vermelho
        {"index": 1, "label": "Drop 1", "pos_ms": 2000, "color": b"\x00\x66\xcc"},
        {"index": 2, "label": "Break", "pos_ms": 5000, "color": b"\xcc\xcc\x00"},
        {"index": 3, "label": "Drop 2", "pos_ms": 8000, "color": b"\x00\xcc\x00"},
        {"index": 4, "label": "Outro", "pos_ms": 11000, "color": b"\xcc\x66\x00"},
    ]
    tags = ID3(str(track))
    tags["GEOB:Serato Markers2"] = GEOB(
        encoding=0, mime="application/octet-stream", desc="Serato Markers2",
        data=auto_cue.build_serato_markers2_tag(custom_cues),
    )
    tags.save(str(track), v2_version=3)

    audit = auto_cue.audit_crate_cues_detailed(str(tmp_path / "MP3"), crate_raiz="CustomTest")
    assert audit["sucesso"] is True
    assert audit["personalizadas"] == 1
    assert audit["padrao_autocue"] == 0


# =============================================================================
# QA-004 — Mutagen ausente retorna erro explícito
# =============================================================================

def test_qa004_missing_mutagen_fails_explicitly(tmp_path, monkeypatch):
    crate_dir = tmp_path / "MP3" / "House"
    crate_dir.mkdir(parents=True)
    (crate_dir / "Track.mp3").write_bytes(b"ID3")

    monkeypatch.setattr(auto_cue, "mutagen", None)
    audit = auto_cue.audit_crate_cues_detailed(str(tmp_path / "MP3"))
    assert audit["sucesso"] is False
    assert audit["dependencia_ausente"] == "mutagen"
    assert audit["varredura_incompleta"] is True

    scan = auto_cue.scan_crate_cues(str(tmp_path / "MP3"))
    assert scan["sucesso"] is False
    assert scan["dependencia_ausente"] == "mutagen"


# =============================================================================
# QA-005 — Consistência de library_root_for
# =============================================================================

def test_qa005_unified_library_root_for_nested_home_serato(tmp_path, monkeypatch):
    fake_home = tmp_path / "Users" / "dj"
    serato_app_sup = fake_home / "Library" / "Application Support" / "Serato"
    music_dir = fake_home / "Music" / "MP3"
    (serato_app_sup / "Subcrates").mkdir(parents=True)
    music_dir.mkdir(parents=True)
    track = music_dir / "Anthem.mp3"
    track.write_bytes(b"MP3")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")

    root_ops = crate_ops.library_root_for(serato_app_sup)
    root_tools = library_tools.library_root_for(serato_app_sup)
    assert root_ops == fake_home.resolve()
    assert root_tools == fake_home.resolve()

    res = crate_ops.add_paths_to_crate(str(serato_app_sup), "Set", [str(track)])
    assert res["sucesso"] is True, res
    assert res["adicionados"] == 1


# =============================================================================
# QA-007 — Controle de erro de diretório na varredura de Auto-Cue
# =============================================================================

def test_qa007_audit_and_scan_report_unreadable_directory(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("Teste de permissão chmod 000 não se aplica ao root")

    base = tmp_path / "MP3"
    ok_dir = base / "Ok"
    locked_dir = base / "Locked"
    ok_dir.mkdir(parents=True)
    locked_dir.mkdir(parents=True)
    AcousticFixtureGenerator.create_tagged_transient_mp3(ok_dir / "Ok.mp3", duration_sec=12.0)
    AcousticFixtureGenerator.create_tagged_transient_mp3(locked_dir / "Hidden.mp3", duration_sec=12.0)

    os.chmod(locked_dir, 0o000)
    try:
        audit = auto_cue.audit_crate_cues_detailed(str(base))
        assert audit["sucesso"] is False
        assert audit["varredura_incompleta"] is True
        assert audit["erros_diretorio"] >= 1

        scan = auto_cue.scan_crate_cues(str(base))
        assert scan["sucesso"] is False
        assert scan["varredura_incompleta"] is True
        assert scan["erros_diretorio"] >= 1
    finally:
        os.chmod(locked_dir, 0o755)


# =============================================================================
# QA-008 — Preservação de sub-blocos binários desconhecidos dentro de otrk
# =============================================================================

def test_qa008_preserves_unknown_otrk_subblocks_across_crate_ops(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    serato_dir = tmp_path / "_Serato_"
    subcrates = serato_dir / "Subcrates"
    subcrates.mkdir(parents=True)
    music_dir = tmp_path / "Music"
    music_dir.mkdir(parents=True)
    t1 = music_dir / "Track1.mp3"
    t2 = music_dir / "Track2.mp3"
    t1.write_bytes(b"MP3")
    t2.write_bytes(b"MP3")

    header = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000"
    rel1 = os.path.relpath(t1, crate_ops.library_root_for(serato_dir))
    ptrk1 = serato_macos_app.criar_tag_tlv("ptrk", rel1)
    custom_sub = b"osub\x00\x00\x00\x06SERATO"
    otrk1_payload = ptrk1 + custom_sub
    otrk1 = b"otrk" + struct.pack(">I", len(otrk1_payload)) + otrk1_payload

    crate_a = subcrates / "CrateA.crate"
    crate_a.write_bytes(header + otrk1)

    # 1. add_paths_to_crate deve preservar o sub-bloco `osub` dentro de `otrk1`
    res_add = crate_ops.add_paths_to_crate(str(serato_dir), "CrateA", [str(t2)])
    assert res_add["sucesso"] is True, res_add
    _, tracks_a, otrk_blocks_a, _ = serato_macos_app.parse_crate_binary(crate_a.read_bytes(), strict=True)
    assert len(tracks_a) == 2
    assert any(custom_sub in blk for _, blk in otrk_blocks_a)

    # 2. merge_crates para nova crate também deve preservar `osub` dentro de `otrk1`
    res_merge = crate_ops.merge_crates(str(serato_dir), ["CrateA"], "Merged")
    assert res_merge["sucesso"] is True, res_merge
    merged_path = subcrates / "Merged.crate"
    _, tracks_m, otrk_blocks_m, _ = serato_macos_app.parse_crate_binary(merged_path.read_bytes(), strict=True)
    assert len(tracks_m) == 2
    assert any(custom_sub in blk for _, blk in otrk_blocks_m)


# =============================================================================
# Regra Crítica: Relink / Relocate NUNCA copia nem move arquivos de áudio
# =============================================================================

def test_relink_updates_only_logical_references_without_copying_audio(tmp_path, monkeypatch):
    import sound_seal
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    monkeypatch.setattr(sound_seal, "DB_PATH", tmp_path / "seals.sqlite")

    mp3_dir = tmp_path / "Music" / "MP3"
    serato_dir = tmp_path / "_Serato_"
    subcrates = serato_dir / "Subcrates"
    subcrates.mkdir(parents=True)

    # Faixa foi movida de Black/OldSub/Hit.mp3 para Black/00/Hit.mp3 e OldSub foi apagada
    new_dir = mp3_dir / "Black" / "00"
    new_dir.mkdir(parents=True)
    moved_song = new_dir / "Hit.mp3"
    moved_song.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00" + (b"\xff\xfb\x90\x00" + b"\x11" * 413) * 20)

    old_dir = mp3_dir / "Black" / "OldSub"
    old_abs_deleted = old_dir / "Hit.mp3"
    old_rel = os.path.relpath(old_abs_deleted, crate_ops.library_root_for(serato_dir))
    new_rel = os.path.relpath(moved_song, crate_ops.library_root_for(serato_dir))

    # Crate com sub-bloco extra dentro de otrk apontando para caminho antigo
    header = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000"
    ptrk_old = serato_macos_app.criar_tag_tlv("ptrk", old_rel)
    custom_sub = b"osub\x00\x00\x00\x04KEEP"
    otrk_crate = b"otrk" + struct.pack(">I", len(ptrk_old + custom_sub)) + ptrk_old + custom_sub
    crate_path = subcrates / "Black%%00.crate"
    crate_path.write_bytes(header + otrk_crate)

    # database V2 apontando para caminho antigo + metadado extra
    db_header = b"vrsn\x00\x00\x00\x08\x002\x00.\x000\x000".ljust(72, b"\x00")
    pfil_old = serato_macos_app.criar_tag_tlv("pfil", old_rel)
    tsng = serato_macos_app.criar_tag_tlv("tsng", "Hit Song")
    db_otrk = b"otrk" + struct.pack(">I", len(pfil_old + tsng)) + pfil_old + tsng
    db_path = serato_dir / "database V2"
    db_path.write_bytes(db_header + db_otrk)

    res = sound_seal.relink_track(
        str(mp3_dir),
        old_rel,
        str(moved_song),
        serato_dir_str=str(serato_dir),
    )
    assert res["sucesso"] is True, res
    assert res["crates_atualizadas"] == 1
    assert res["database_v2_atualizadas"] == 1

    # 1. Pasta antiga NÃO foi recriada e nenhum MP3 foi copiado
    assert not old_dir.exists()
    assert not old_abs_deleted.exists()
    all_mp3s = list(mp3_dir.rglob("*.mp3"))
    assert all_mp3s == [moved_song]

    # 2. Crate aponta para novo caminho lógico e preserva sub-bloco `osub`
    _, tracks_after, otrk_after, _ = serato_macos_app.parse_crate_binary(crate_path.read_bytes(), strict=True)
    assert tracks_after == [serato_macos_app.normalizar_nfc(new_rel)]
    assert any(custom_sub in blk for _, blk in otrk_after)

    # 3. database V2 aponta para novo caminho lógico e preserva `tsng`
    db_bytes = db_path.read_bytes()
    assert new_rel.encode("utf-16-be") in db_bytes
    assert old_rel.encode("utf-16-be") not in db_bytes
    assert tsng in db_bytes

    # 4. Arquivo na Lixeira (.Trashes) não deve ser copiado nem movido
    trash_dir = tmp_path / ".Trashes" / "501"
    trash_dir.mkdir(parents=True)
    trashed = trash_dir / "Deleted.mp3"
    trashed.write_bytes(b"MP3")
    res_trash = sound_seal.relink_track(
        str(mp3_dir),
        "Music/MP3/Old/Deleted.mp3",
        str(trashed),
        serato_dir_str=str(serato_dir),
    )
    assert res_trash["sucesso"] is False
    assert trashed.exists()
    assert not (mp3_dir / "Old" / "Deleted.mp3").exists()


def test_snapshot_audio_fingerprint_detects_head_middle_tail_and_preserves_sha256(tmp_path):
    large = tmp_path / "LargeTrack.mp3"
    base = bytearray(b"ID3" + b"\x00" * 350000)
    large.write_bytes(base)

    fp_orig = serato_macos_app._snapshot_audio_fingerprint(large)
    sha_full = serato_macos_app._sha256_file(large)
    assert len(fp_orig) == 64
    assert len(sha_full) == 64

    # Alteração no início (< 64 KB)
    mod_head = bytearray(base)
    mod_head[100] = 0xAA
    large.write_bytes(mod_head)
    assert serato_macos_app._snapshot_audio_fingerprint(large) != fp_orig

    # Alteração no meio exato
    mod_mid = bytearray(base)
    mod_mid[len(base) // 2] = 0xBB
    large.write_bytes(mod_mid)
    assert serato_macos_app._snapshot_audio_fingerprint(large) != fp_orig

    # Alteração no rodapé (últimos 64 KB)
    mod_tail = bytearray(base)
    mod_tail[-10] = 0xCC
    large.write_bytes(mod_tail)
    assert serato_macos_app._snapshot_audio_fingerprint(large) != fp_orig

    # Restaura exatamente
    large.write_bytes(base)
    assert serato_macos_app._snapshot_audio_fingerprint(large) == fp_orig


def test_dry_run_plan_invalidation_with_large_track_fast_fingerprint(tmp_path, monkeypatch):
    import journal
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir = tmp_path / "Music" / "MP3"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"

    track = mp3_dir / "House" / "BigTrack.mp3"
    track.parent.mkdir(parents=True)
    payload = bytearray(b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff" * 320000)
    track.write_bytes(payload)

    ok_dry, res_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    assert ok_dry is True
    plan = res_dry["plan"]
    st_before = track.stat()

    # Altera byte no meio mantendo tamanho e restaurando mtime original para forçar validação pelo fingerprint
    payload[len(payload) // 2] = 0x11
    track.write_bytes(payload)
    os.utime(track, ns=(st_before.st_atime_ns, st_before.st_mtime_ns))

    ok_exec, res_exec = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_exec is False
    assert res_exec["plan_invalidated"] is True


