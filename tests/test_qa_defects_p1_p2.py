import copy
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serato_macos_app
import journal
import crate_ops


def _make_audio(path: Path, content: bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 32):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _assert_no_side_effects(serato_dir: Path, logs_dir: Path, journal_path: Path):
    assert not (serato_dir / "Subcrates").exists(), "Subcrates não deve ser criado para plano inválido"
    assert not logs_dir.exists(), "Diretório de logs não deve ser criado para plano inválido"
    assert not journal_path.exists(), "Journal não deve ser inicializado para plano inválido"


def test_qa001_immutable_plan_executes_exact_operations(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"

    _make_audio(mp3_dir / "House" / "Track One.mp3")
    _make_audio(mp3_dir / "Techno" / "Track Two.mp3")

    ok_dry, resumo_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    assert ok_dry is True
    assert resumo_dry["dry_run"] is True
    assert resumo_dry["plan_id"].startswith("plan-")
    assert resumo_dry["plan_hash"]
    plan = resumo_dry["plan"]
    assert len(plan["files"]) == 2
    assert all(f["sha256"] for f in plan["files"])
    _assert_no_side_effects(serato_dir, logs_dir, j_path)

    ok_exec, resumo_exec = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_exec is True
    assert resumo_exec["plan_invalidated"] is False
    assert (serato_dir / "Subcrates" / "House.crate").exists()
    assert (serato_dir / "Subcrates" / "Techno.crate").exists()


def test_qa001_nonexistent_plan_file_leaves_no_side_effects(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"
    _make_audio(mp3_dir / "House" / "Track One.mp3")

    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir),
        str(serato_dir),
        str(logs_dir),
        export_csv=False,
        dry_run=False,
        plan_file=str(tmp_path / "does_not_exist.json"),
    )
    assert ok is False
    assert resumo["plan_invalidated"] is True
    _assert_no_side_effects(serato_dir, logs_dir, j_path)


def test_qa001_invalid_plan_id_rejected_without_side_effects(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"
    _make_audio(mp3_dir / "House" / "Track One.mp3")

    _, resumo_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    bad_plan = copy.deepcopy(resumo_dry["plan"])
    bad_plan["plan_id"] = "invalid-id"
    bad_plan["plan_hash"] = serato_macos_app._build_plan_hash(bad_plan)

    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=bad_plan
    )
    assert ok is False
    assert resumo["plan_invalidated"] is True
    _assert_no_side_effects(serato_dir, logs_dir, j_path)


def test_qa001_divergent_sha256_rejected_without_side_effects(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"
    _make_audio(mp3_dir / "House" / "Track One.mp3")

    _, resumo_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    bad_plan = copy.deepcopy(resumo_dry["plan"])
    bad_plan["plan_hash"] = "0" * 64

    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=bad_plan
    )
    assert ok is False
    assert resumo["plan_invalidated"] is True
    _assert_no_side_effects(serato_dir, logs_dir, j_path)


def test_qa001_plan_invalidated_when_audio_added_removed_or_modified(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"

    t1 = mp3_dir / "House" / "Track One.mp3"
    t2 = mp3_dir / "House" / "Track Two.mp3"
    _make_audio(t1, content=b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xaa" * 64)
    _make_audio(t2, content=b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xcc" * 64)

    _, resumo_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    plan = resumo_dry["plan"]

    # 1. Arquivo alterado
    _make_audio(t1, content=b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xbb" * 64)
    ok_mod, res_mod = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_mod is False and res_mod["plan_invalidated"] is True
    _assert_no_side_effects(serato_dir, logs_dir, j_path)

    # Restaura t1 e remove t2
    _make_audio(t1, content=b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xaa" * 64)
    t2.unlink()
    ok_rem, res_rem = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_rem is False and res_rem["plan_invalidated"] is True
    _assert_no_side_effects(serato_dir, logs_dir, j_path)

    # Restaura t2 e adiciona t3
    _make_audio(t2, content=b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xcc" * 64)
    _make_audio(mp3_dir / "House" / "Track Intruder.mp3")
    ok_add, res_add = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_add is False and res_add["plan_invalidated"] is True
    _assert_no_side_effects(serato_dir, logs_dir, j_path)


def test_qa001_plan_invalidated_when_crate_or_neworder_modified(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"
    subcrates = serato_dir / "Subcrates"
    subcrates.mkdir(parents=True, exist_ok=True)

    _make_audio(mp3_dir / "House" / "Track One.mp3")
    crate_path = subcrates / "House.crate"
    crate_ops.write_crate_atomic(crate_path, ["Old/Track.mp3"])
    pref_path = serato_dir / "neworder.pref"
    pref_path.write_bytes(b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000")

    _, resumo_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    plan = resumo_dry["plan"]

    # Modifica crate externamente
    orig_crate_bytes = crate_path.read_bytes()
    crate_ops.write_crate_atomic(crate_path, ["Tampered/Track.mp3"])
    journal_size_before = j_path.stat().st_size if j_path.exists() else 0
    ok_c, res_c = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_c is False and res_c["plan_invalidated"] is True
    assert not logs_dir.exists()
    assert (j_path.stat().st_size if j_path.exists() else 0) == journal_size_before

    # Restaura crate e modifica neworder.pref externamente
    crate_path.write_bytes(orig_crate_bytes)
    pref_path.write_bytes(b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x001")
    ok_p, res_p = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_p is False and res_p["plan_invalidated"] is True
    assert not logs_dir.exists()
    assert (j_path.stat().st_size if j_path.exists() else 0) == journal_size_before


def test_qa001_plan_invalidated_for_different_library(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_a = tmp_path / "music_a"
    serato_a = tmp_path / "serato_a"
    mp3_b = tmp_path / "music_b"
    serato_b = tmp_path / "serato_b"
    logs_dir = tmp_path / "logs"

    _make_audio(mp3_a / "House" / "Track One.mp3")
    _make_audio(mp3_b / "House" / "Track One.mp3")

    _, resumo_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_a), str(serato_a), str(logs_dir), export_csv=False, dry_run=True
    )
    plan = resumo_dry["plan"]

    ok, res = serato_macos_app.sincronizar_biblioteca(
        str(mp3_b), str(serato_b), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok is False and res["plan_invalidated"] is True
    _assert_no_side_effects(serato_b, logs_dir, j_path)


def test_qa001_plan_cannot_be_consumed_twice_or_concurrently(tmp_path, monkeypatch):
    j_path = tmp_path / "journal.sqlite"
    monkeypatch.setattr(journal, "JOURNAL_PATH", j_path)
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"
    _make_audio(mp3_dir / "House" / "Track One.mp3")

    _, resumo_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    plan = resumo_dry["plan"]

    # Duas tentativas simultâneas: apenas 1 pode passar; a outra deve ser invalidada
    barrier = threading.Barrier(2)
    results = []

    def _worker():
        barrier.wait()
        ok_w, res_w = serato_macos_app.sincronizar_biblioteca(
            str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
        )
        results.append((ok_w, res_w.get("plan_invalidated", False)))

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [r for r in results if r[0] is True]
    invalidated = [r for r in results if r[0] is False and r[1] is True]
    assert len(successes) == 1
    assert len(invalidated) == 1

    # Terceira tentativa sequencial também deve ser rejeitada
    ok3, res3 = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok3 is False and res3["plan_invalidated"] is True


def test_qa002_summary_records_canonical_library_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"
    _make_audio(mp3_dir / "House" / "Track One.mp3")

    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False
    )
    assert ok is True
    assert resumo["mp3_path"] == str(mp3_dir.resolve())
    assert resumo["serato_path"] == str(serato_dir.resolve())
    assert len(resumo["library_id"]) == 16
    assert (logs_dir / "summaries" / f"{resumo['library_id']}.json").exists()


def test_qa004_custom_paths_preserve_exact_caminho_abs(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "serato"
    logs_dir = tmp_path / "logs"

    track = mp3_dir / "House" / "Track One.mp3"
    _make_audio(track)

    ok, resumo = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    assert ok is True
    faixas = resumo["crates_arvore"]["House"]["faixas"]
    assert len(faixas) == 1
    abs_reported = Path(faixas[0]["caminho_abs"])
    assert abs_reported == track.resolve()
    assert abs_reported.exists()


def test_qa02_strict_target_paths_rejects_invalid_and_isolated_libraries(tmp_path):
    import sound_seal
    import struct
    from serato_macos_app import criar_tag_tlv, parse_crate_binary

    mp3_dir = tmp_path / "Music" / "MP3"
    serato_a = tmp_path / "LibA" / "_Serato_"
    serato_b = tmp_path / "LibB" / "_Serato_"
    for d in (mp3_dir, serato_a / "Subcrates", serato_b / "Subcrates"):
        d.mkdir(parents=True, exist_ok=True)

    _make_audio(mp3_dir / "House" / "KeepMe.mp3")
    _make_audio(mp3_dir / "Techno" / "SameName.mp3")

    def make_crate(path, tracks, extra=b""):
        hdr = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000"
        body = bytearray(hdr + extra)
        for t in tracks:
            pt = criar_tag_tlv("ptrk", t)
            body.extend(b"otrk" + struct.pack(">I", len(pt)) + pt)
        path.write_bytes(bytes(body))

    crate_a = serato_a / "Subcrates" / "House.crate"
    crate_b = serato_b / "Subcrates" / "OtherLib.crate"
    make_crate(crate_a, ["Music/MP3/House/KeepMe.mp3", "Music/MP3/Ghost.mp3"], extra=b"osrt" + struct.pack(">I", 4) + b"\x00\x01\x02\x03")
    make_crate(crate_b, ["Music/MP3/Ghost.mp3"])
    crate_b_before = crate_b.read_bytes()

    # Negative inputs: invalid JSON, dict instead of list, empty list, None, omitted global flag
    for bad_arg in ["{bad json", '{"a": 1}', "[]", "[123]", None, ""]:
        res = sound_seal.remove_lost_tracks_from_crates(
            str(serato_a), str(mp3_dir), target_paths_json=bad_arg
        )
        assert res["sucesso"] is False
        assert res["total_removidas"] == 0

    # Valid targeted removal preserves unknown block osrt and does NOT touch LibB
    res_ok = sound_seal.remove_lost_tracks_from_crates(
        str(serato_a),
        str(mp3_dir),
        target_paths_json='["Music/MP3/Ghost.mp3", "Music/MP3/Ghost.mp3", "Music/MP3/NotPresent.mp3"]',
    )
    assert res_ok["sucesso"] is True
    assert res_ok["crates_removidas"] == 1
    _, rem_a, _, outros_a = parse_crate_binary(crate_a.read_bytes())
    assert rem_a == ["Music/MP3/House/KeepMe.mp3"]
    assert len(outros_a) == 1
    assert crate_b.read_bytes() == crate_b_before


def test_qa05_sound_seal_rejects_corrupt_crate_via_crate_ops(tmp_path):
    import sound_seal
    mp3_dir = tmp_path / "Music" / "MP3"
    serato_dir = tmp_path / "_Serato_"
    (serato_dir / "Subcrates").mkdir(parents=True, exist_ok=True)
    _make_audio(mp3_dir / "Keep.mp3")

    corrupt = serato_dir / "Subcrates" / "Corrupt.crate"
    corrupt_bytes = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000otrk\x00\x00\x01\x00broken"
    corrupt.write_bytes(corrupt_bytes)

    res = sound_seal.remove_lost_tracks_from_crates(
        str(serato_dir), str(mp3_dir), target_paths_json='["Music/MP3/Keep.mp3"]'
    )
    assert res["sucesso"] is True
    assert corrupt.read_bytes() == corrupt_bytes
    assert any("Corrupt" in item.get("crate", "") and "erro" in item for item in res["crates_afetadas"])


def test_p1_p2_remediations_smoke(tmp_path, monkeypatch):
    import auto_cue
    import crate_ops
    import pioneer_usb_exporter
    import scan_unused_files
    import track_matcher
    import subprocess
    from mutagen.id3 import ID3, TIT2, TBPM

    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    monkeypatch.setattr(auto_cue, "BACKUP_DB_PATH", tmp_path / "cues.sqlite")

    # 1. Pioneer cue conversion + deterministic content_id (no duplicate djmdCue rows on re-export)
    mp3 = tmp_path / "Lib" / "Track.mp3"
    mp3.parent.mkdir(parents=True, exist_ok=True)
    # 1200 MPEG frames (~31s duration) so auto_cue duration check (>=10s) succeeds
    mp3.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 1200)
    tags = ID3()
    tags.add(TIT2(encoding=3, text="DJ Track"))
    tags.add(TBPM(encoding=3, text="128.75"))
    tags.save(str(mp3), v2_version=3)
    res_cue = auto_cue.generate_and_save_serato_cues(str(mp3), overwrite_existing=True)
    assert res_cue["sucesso"] is True, res_cue

    usb_dir = tmp_path / "USB"
    exporter = pioneer_usb_exporter.PioneerUsbExporter(usb_dir)
    tlist = [{"filepath": str(mp3), "title": "DJ Track", "artist": "Art", "bpm": 128.75}]
    s1 = exporter.export_crate("House", tlist, copy_audio=False)
    s2 = exporter.export_crate("House", tlist, copy_audio=False)
    assert s1["cues_converted"] > 0
    assert s2["cues_converted"] == s1["cues_converted"]

    # 2. Track matcher upgrade preserves DJ Serato Markers2 without mutating source incoming file
    inc = tmp_path / "Downloads" / "TrackNew.mp3"
    inc.parent.mkdir(parents=True, exist_ok=True)
    inc.write_bytes((b"\xff\xfb\x90\x00" + b"\x00" * 413) * 1200)
    inc_before = inc.read_bytes()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "FakeHome"))
    up = track_matcher.replace_track_with_upgrade(str(inc), str(mp3), force=True)
    assert up["sucesso"] is True
    assert inc.read_bytes() == inc_before
    assert "GEOB:Serato Markers2" in ID3(str(mp3))

    # 3. UnusedFilesScanner distinguishes homonyms across folders and never overwrites duplicates in quarantine
    m_dir = tmp_path / "Media"
    s_dir = tmp_path / "MediaSerato"
    (s_dir / "Subcrates").mkdir(parents=True, exist_ok=True)
    _make_audio(m_dir / "Used" / "Intro.mp3")
    _make_audio(m_dir / "UnusedA" / "Intro.mp3", b"ID3\x03\x00A")
    _make_audio(m_dir / "UnusedB" / "Intro.mp3", b"ID3\x03\x00B")
    crate_ops.write_crate_atomic(s_dir / "Subcrates" / "Used.crate", ["Media/Used/Intro.mp3"])
    scanner = scan_unused_files.UnusedFilesScanner(str(m_dir), str(s_dir))
    scan_res = scanner.scan()
    assert scan_res["total_unused"] == 2
    q_res = scanner.quarantine_files([str(m_dir / "UnusedA" / "Intro.mp3"), str(m_dir / "UnusedB" / "Intro.mp3")])
    assert q_res["moved_count"] == 2

    # 4. audio_health.py CLI accepts --categoria fake_320k cleanly
    help_proc = subprocess.run(
        [sys.executable, "audio_health.py", "--mp3", str(m_dir), "--categoria", "fake_320k", "--scan"],
        capture_output=True, text=True, check=False
    )
    assert help_proc.returncode == 0
