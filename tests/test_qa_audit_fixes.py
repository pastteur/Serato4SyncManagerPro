#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regressão dos achados da Auditoria QA (E-01 a E-05):
- E-01: Parser rejeita crate truncada, sub-bloco truncado e bytes residuais, distinguindo crate vazia legítima.
- E-02: Sincronização usa write_crate_atomic com backup SHA-256 obrigatório (falha de backup cancela escrita).
- E-03: Sincronização em duas fases (erro em pasta posterior impede escrita de pastas anteriores).
- E-04: Falha no Journal impede confirmação de sucesso e executa rollback verificado.
- E-05: Crate existente vazia (0 bytes) é rejeitada sem substituição silenciosa.
"""

import os
import sys
import struct
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serato_macos_app
import crate_ops
import journal


def _make_valid_header() -> bytes:
    return b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000'


def _make_otrk_block(rel_path: str) -> bytes:
    ptrk = serato_macos_app.criar_tag_tlv('ptrk', rel_path)
    return b'otrk' + struct.pack('>I', len(ptrk)) + ptrk


class TestQAAuditFixes(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="qa_audit_"))
        self.mp3_dir = self.tmp_dir / "MP3"
        self.serato_dir = self.tmp_dir / "_Serato_"
        self.subcrates_dir = self.serato_dir / "Subcrates"
        self.logs_dir = self.tmp_dir / "Logs"
        self.mp3_dir.mkdir(parents=True)
        self.subcrates_dir.mkdir(parents=True)
        self.logs_dir.mkdir(parents=True)

        self._orig_journal = journal.JOURNAL_PATH
        journal.JOURNAL_PATH = self.tmp_dir / "test_journal.sqlite"

    def tearDown(self):
        journal.JOURNAL_PATH = self._orig_journal
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # E-01: Parser rejeita crate truncada / residual, aceita vazia legítima
    # ------------------------------------------------------------------
    def test_e01_truncated_otrk_block_rejected(self):
        header = _make_valid_header()
        # Bloco otrk declara 500 bytes, mas só tem 4 bytes de payload
        truncated = header + b'otrk' + struct.pack('>I', 500) + b'ptrk'

        h, tracks, otrk, outros = serato_macos_app.parse_crate_binary(truncated)
        self.assertIsNone(h)
        self.assertEqual(tracks, [])

        with self.assertRaises(ValueError):
            serato_macos_app.parse_crate_binary(truncated, strict=True)

        crate_file = self.subcrates_dir / "Truncated.crate"
        crate_file.write_bytes(truncated)
        with self.assertRaises(ValueError):
            crate_ops.read_and_validate_crate(crate_file)

    def test_e01_truncated_internal_ptrk_rejected(self):
        header = _make_valid_header()
        # otrk tem tamanho exato, mas ptrk interno declara 200 bytes e tem apenas 4
        bad_ptrk = b'ptrk' + struct.pack('>I', 200) + b'\x00a\x00b'
        bad_otrk = b'otrk' + struct.pack('>I', len(bad_ptrk)) + bad_ptrk
        data = header + bad_otrk

        h, tracks, _, _ = serato_macos_app.parse_crate_binary(data)
        self.assertIsNone(h)
        self.assertEqual(tracks, [])

    def test_e01_residual_trailing_bytes_rejected(self):
        header = _make_valid_header()
        data = header + _make_otrk_block("Music/MP3/Track1.mp3") + b'\x01\x02\x03'

        h, tracks, _, _ = serato_macos_app.parse_crate_binary(data)
        self.assertIsNone(h)
        self.assertEqual(tracks, [])

    def test_e01_legitimate_empty_crate_accepted(self):
        header = _make_valid_header()
        crate_file = self.subcrates_dir / "EmptyValid.crate"
        crate_file.write_bytes(header)

        h, tracks, outros = crate_ops.read_and_validate_crate(crate_file)
        self.assertEqual(h, header)
        self.assertEqual(tracks, [])
        self.assertEqual(outros, [])

    # ------------------------------------------------------------------
    # E-02: Falha de backup na sincronização impede substituição
    # ------------------------------------------------------------------
    def test_e02_sync_aborts_crate_write_on_backup_failure(self):
        folder = self.mp3_dir / "01 House"
        folder.mkdir()
        (folder / "Track1.mp3").write_bytes(b"ID3" + b"\x00" * 100)
        (folder / "Track2.mp3").write_bytes(b"ID3" + b"\x00" * 100)

        crate_file = self.subcrates_dir / "01 House.crate"
        orig_bytes = _make_valid_header() + _make_otrk_block("Music/MP3/01 House/Track1.mp3")
        crate_file.write_bytes(orig_bytes)

        with patch("crate_ops.shutil.copy2", side_effect=OSError("Disk full during backup")):
            ok, summary = serato_macos_app.sincronizar_biblioteca(
                str(self.mp3_dir), str(self.serato_dir), str(self.logs_dir), export_csv=False
            )

        self.assertFalse(ok)
        self.assertEqual(crate_file.read_bytes(), orig_bytes)

    # ------------------------------------------------------------------
    # E-03: Sincronização em duas fases (nenhuma escrita se pasta posterior falhar)
    # ------------------------------------------------------------------
    def test_e03_two_phase_sync_no_writes_when_later_folder_fails(self):
        folder_a = self.mp3_dir / "01 Alpha"
        folder_b = self.mp3_dir / "02 Beta"
        folder_a.mkdir()
        folder_b.mkdir()
        (folder_a / "AlphaTrack.mp3").write_bytes(b"ID3" + b"\x00" * 100)
        bad_file = folder_b / "BetaCorruptStat.mp3"
        bad_file.write_bytes(b"ID3" + b"\x00" * 100)

        orig_stat = Path.stat

        def flaky_stat(p_self, *args, **kwargs):
            if p_self.name == "BetaCorruptStat.mp3":
                raise OSError("Simulated I/O disconnect on second folder")
            return orig_stat(p_self, *args, **kwargs)

        with patch.object(Path, "stat", flaky_stat):
            ok, summary = serato_macos_app.sincronizar_biblioteca(
                str(self.mp3_dir), str(self.serato_dir), str(self.logs_dir), export_csv=False
            )

        self.assertFalse(ok)
        self.assertEqual(summary["status_analise"], "parcial_com_erros")
        self.assertFalse((self.subcrates_dir / "01 Alpha.crate").exists())
        self.assertFalse((self.subcrates_dir / "02 Beta.crate").exists())

    # ------------------------------------------------------------------
    # E-04: Falha no Journal impede sucesso e executa rollback
    # ------------------------------------------------------------------
    def test_e04_journal_failure_triggers_rollback_on_existing_crate(self):
        crate_file = self.subcrates_dir / "JournalFail.crate"
        orig_bytes = _make_valid_header() + _make_otrk_block("Music/MP3/Track1.mp3")
        crate_file.write_bytes(orig_bytes)

        with patch("journal.record_crate_operation", side_effect=RuntimeError("SQLite locked")):
            res = crate_ops.write_crate_atomic(
                crate_file, ["Music/MP3/Track1.mp3", "Music/MP3/Track2.mp3"], action_name="test_fail"
            )

        self.assertFalse(res["sucesso"])
        self.assertIn("Journal", res["erro"])
        self.assertEqual(crate_file.read_bytes(), orig_bytes)

    def test_e04_journal_failure_removes_newly_created_crate(self):
        crate_file = self.subcrates_dir / "JournalFailNew.crate"
        self.assertFalse(crate_file.exists())

        with patch("journal.record_crate_operation", side_effect=RuntimeError("SQLite read-only")):
            res = crate_ops.write_crate_atomic(
                crate_file, ["Music/MP3/Track1.mp3"], action_name="test_fail_new"
            )

        self.assertFalse(res["sucesso"])
        self.assertFalse(crate_file.exists())

    # ------------------------------------------------------------------
    # E-05: Arquivo existente vazio (0 bytes) é rejeitado sem substituição
    # ------------------------------------------------------------------
    def test_e05_empty_existing_crate_rejected(self):
        crate_file = self.subcrates_dir / "ZeroBytes.crate"
        crate_file.write_bytes(b"")

        res = crate_ops.write_crate_atomic(
            crate_file, ["Music/MP3/Track1.mp3"], action_name="test_empty"
        )

        self.assertFalse(res["sucesso"])
        self.assertIn("vazia", res["erro"].lower())
        self.assertEqual(crate_file.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
