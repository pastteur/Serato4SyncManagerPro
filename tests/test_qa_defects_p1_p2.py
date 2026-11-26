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
