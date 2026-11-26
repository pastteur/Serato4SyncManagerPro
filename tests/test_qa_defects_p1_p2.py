import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serato_macos_app
import journal


def _make_audio(path: Path, content: bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 32):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_qa001_immutable_plan_executes_exact_operations(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
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
    assert not serato_dir.exists()

    ok_exec, resumo_exec = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_exec is True
    assert resumo_exec["plan_invalidated"] is False
    assert (serato_dir / "Subcrates" / "House.crate").exists()
    assert (serato_dir / "Subcrates" / "Techno.crate").exists()


def test_qa001_plan_invalidated_when_library_modified_after_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"

    t1 = mp3_dir / "House" / "Track One.mp3"
    _make_audio(t1)

    ok_dry, resumo_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    assert ok_dry is True
    plan = resumo_dry["plan"]

    # Modificação externa após a análise: adiciona nova faixa
    _make_audio(mp3_dir / "House" / "Track Intruder.mp3")

    ok_exec, resumo_exec = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_exec is False
    assert resumo_exec["plan_invalidated"] is True
    assert not (serato_dir / "Subcrates" / "House.crate").exists()


def test_qa001_plan_invalidated_when_file_content_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.sqlite")
    mp3_dir = tmp_path / "music"
    serato_dir = tmp_path / "_Serato_"
    logs_dir = tmp_path / "logs"

    t1 = mp3_dir / "House" / "Track One.mp3"
    _make_audio(t1, content=b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xaa" * 64)

    ok_dry, resumo_dry = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=True
    )
    assert ok_dry is True
    plan = resumo_dry["plan"]

    # Altera o conteúdo binário do arquivo após a prévia
    _make_audio(t1, content=b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xbb" * 64)

    ok_exec, resumo_exec = serato_macos_app.sincronizar_biblioteca(
        str(mp3_dir), str(serato_dir), str(logs_dir), export_csv=False, dry_run=False, plan=plan
    )
    assert ok_exec is False
    assert resumo_exec["plan_invalidated"] is True


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
