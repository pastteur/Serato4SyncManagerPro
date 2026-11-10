#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_sandbox_isolation.py
Milestone 1 Verification Test Suite — Filesystem Sandbox Containment & Zero-Leak Assurance.

Proves:
1. Sandbox directory structure and convenience symlinks.
2. Subprocess environment variable containment (HOME, TMPDIR).
3. Engine SQLite database generation strictly isolated within fake_home.
4. In-process module constant monkey-patching and clean restoration.
5. Zero-leak canary assertion failsafe detection upon mutation.
6. Relative crate path encoding without host system path leaks.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root and vendor
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
VENDOR_DIR = PROJECT_ROOT / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))
bad_mutagen_dir = str(PROJECT_ROOT / "vendor" / "mutagen")
if bad_mutagen_dir in sys.path:
    sys.path.remove(bad_mutagen_dir)

from tests.fixtures import (
    SeratoSandbox,
    create_synthetic_mp3,
    read_crate_paths,
    HOST_HOME,
)
import journal


class TestSandboxIsolation(unittest.TestCase):
    """
    Verification test suite confirming 100% leak-proof isolation across subprocess
    and in-process engine invocations.
    """

    def test_sandbox_directory_structure_and_symlinks(self):
        """
        Test 1: Confirms all required directories exist under fake_home and tmp,
        and all convenience symlinks at sandbox root resolve correctly.
        """
        with SeratoSandbox(clean_on_exit=True) as sb:
            self.assertTrue(sb.fake_home.is_dir(), "fake_home must be a directory")
            self.assertTrue(sb.tmp_dir.is_dir(), "tmp_dir must be a directory")
            self.assertTrue(sb.mp3_dir.is_dir(), "Music/MP3 must exist")
            self.assertTrue(sb.serato_dir.is_dir(), "Music/_Serato_ must exist")
            self.assertTrue(sb.subcrates_dir.is_dir(), "Music/_Serato_/Subcrates must exist")
            self.assertTrue(sb.logs_dir.is_dir(), "SeratoSync/logs must exist")
            self.assertTrue(sb.exports_dir.is_dir(), "SeratoSync/exports must exist")
            self.assertTrue(sb.quarantine_dir.is_dir(), ".serato_quarentena_audio must exist")
            self.assertTrue(sb.serato_app_support.is_dir(), "Application Support/Serato/Library must exist")
            self.assertTrue((sb.serato_app_support / "master.sqlite").is_file(), "Dummy master.sqlite must exist")
            self.assertTrue(sb.desktop_dir.is_dir(), "Desktop must exist")
            self.assertTrue(sb.trash_dir.is_dir(), ".Trash must exist")
            self.assertTrue(sb.backups_dir.is_dir(), "pasync/backups must exist")

            # Check convenience symlinks
            music_link = sb.sandbox_root / "Music"
            logs_link = sb.sandbox_root / "logs"
            quarantine_link = sb.sandbox_root / "quarantine"

            self.assertTrue(music_link.is_symlink(), "Music link must be a symlink")
            self.assertEqual(music_link.resolve(), (sb.fake_home / "Music").resolve())
            self.assertTrue(logs_link.is_symlink(), "logs link must be a symlink")
            self.assertEqual(logs_link.resolve(), sb.logs_dir.resolve())
            self.assertTrue(quarantine_link.is_symlink(), "quarantine link must be a symlink")
            self.assertEqual(quarantine_link.resolve(), sb.quarantine_dir.resolve())

    def test_subprocess_environment_containment(self):
        """
        Test 2: Spawns child Python process via sb.run_cli and asserts that
        Path.home() and tempfile.gettempdir() point strictly inside sandbox.
        """
        probe_code = (
            "import os, pathlib, tempfile, json;"
            "home = str(pathlib.Path.home().resolve());"
            "tmp = str(pathlib.Path(tempfile.gettempdir()).resolve());"
            "canary = pathlib.Path.home() / 'subprocess_canary.txt';"
            "canary.write_text('contained');"
            "print(json.dumps({'home': home, 'tmp': tmp, 'canary': str(canary.resolve())}))"
        )

        with SeratoSandbox(clean_on_exit=True) as sb:
            result = sb.run_cli(["python3", "-c", probe_code])
            self.assertTrue(result.is_success, f"Subprocess failed: {result.stderr}")
            self.assertIsNotNone(result.json_payload, "Expected JSON output from probe")

            payload = result.json_payload
            self.assertEqual(payload["home"], str(sb.fake_home.resolve()))
            self.assertEqual(payload["tmp"], str(sb.tmp_dir.resolve()))

            canary_file = sb.fake_home / "subprocess_canary.txt"
            self.assertTrue(canary_file.exists(), "Canary file must exist in fake_home")
            self.assertEqual(canary_file.read_text(), "contained")

            # Real host directory must NOT contain the canary
            host_canary = HOST_HOME / "subprocess_canary.txt"
            self.assertFalse(host_canary.exists(), "Host home must not be touched")

            sb.assert_zero_leaks()

    def test_engine_sqlite_databases_isolated(self):
        """
        Test 3: Executes journal.py, auto_cue.py --list-backups, and sound_seal.py --status
        via sb.run_cli. Confirms databases are created in fake_home and real host files are untouched.
        """
        with SeratoSandbox(clean_on_exit=True) as sb:
            # 1. journal.py: record an operation in sandbox
            dummy_mp3 = sb.mp3_dir / "journal_probe.mp3"
            create_synthetic_mp3(dummy_mp3, title="Journal Probe")
            res_j = sb.run_cli([
                "python3", "-c",
                f"import journal; journal.record_id3_before_change('{dummy_mp3}', action='PROBE'); print('OK')"
            ])
            self.assertTrue(res_j.is_success, f"journal recording failed: {res_j.stderr}")
            journal_db = sb.fake_home / ".serato_sync_journal.sqlite"
            self.assertTrue(journal_db.exists(), f"Journal DB should be in fake_home: {journal_db}")

            # Verify journal.py --list reads the operation cleanly
            res_list = sb.run_cli(["journal.py", "--list"])
            self.assertTrue(res_list.is_success, f"journal.py --list failed: {res_list.stderr}")
            self.assertIsNotNone(res_list.json_payload)

            # 2. auto_cue.py: initialize backup db in sandbox
            res_c_init = sb.run_cli(["python3", "-c", "import auto_cue; auto_cue.get_backup_db().close()"])
            self.assertTrue(res_c_init.is_success, f"auto_cue init failed: {res_c_init.stderr}")
            cue_db = sb.fake_home / ".serato_sync_cues_backup.sqlite"
            self.assertTrue(cue_db.exists(), f"Cue DB should be in fake_home: {cue_db}")

            res_c = sb.run_cli(["auto_cue.py", "--list-backups"])
            self.assertTrue(res_c.is_success, f"auto_cue.py failed: {res_c.stderr}")

            # 3. sound_seal.py
            res_s = sb.run_cli(["sound_seal.py", "--status"])
            self.assertTrue(res_s.is_success, f"sound_seal.py failed: {res_s.stderr}")
            seal_db = sb.fake_home / ".serato_sound_seals.sqlite"
            self.assertTrue(seal_db.exists(), f"Sound seal DB should be in fake_home: {seal_db}")

            # Assert 100% zero leaks to host
            sb.assert_zero_leaks()

    def test_in_process_engine_patching(self):
        """
        Test 4: Uses with SeratoSandbox() as sb, invokes journal.record_id3_before_change in-process.
        Verifies operation written to fake_home, not host home, and constant restored on exit.
        """
        orig_journal_path = journal.JOURNAL_PATH

        with SeratoSandbox(clean_on_exit=True) as sb:
            # Constant must point inside fake_home
            self.assertEqual(journal.JOURNAL_PATH, sb.fake_home / ".serato_sync_journal.sqlite")

            # Create a dummy audio file in fake_home
            test_mp3 = sb.mp3_dir / "test_track.mp3"
            create_synthetic_mp3(test_mp3, title="Original Title")

            # Record operation in journal using in-process module
            op_id = journal.record_id3_before_change(
                filepath=str(test_mp3),
                action="TEST_PATCHING"
            )
            self.assertIsNotNone(op_id)
            self.assertTrue(op_id > 0)

            # Assert database file exists in fake_home
            sandbox_db = sb.fake_home / ".serato_sync_journal.sqlite"
            self.assertTrue(sandbox_db.exists(), "Journal DB must exist in sandbox fake_home")

            # Assert zero leaks to host
            sb.assert_zero_leaks()

        # After exiting sandbox context, constant must be restored
        self.assertEqual(journal.JOURNAL_PATH, orig_journal_path, "JOURNAL_PATH must be restored")

    def test_zero_leak_assertion_detects_leak(self):
        """
        Test 5: Failsafe test verifying that assert_zero_leaks accurately catches
        any unauthorized filesystem modification and raises AssertionError.
        (Operates strictly within /tmp to protect host integrity).
        """
        with tempfile.TemporaryDirectory(prefix="canary_watch_test_") as tmp_watch:
            watch_path = Path(tmp_watch) / "canary.sqlite"
            watch_path.write_text("initial state")

            sb = SeratoSandbox(clean_on_exit=True, extra_watch_paths=[watch_path])
            sb.start()
            try:
                # Should pass initially
                sb.assert_zero_leaks()

                # Simulate a leak by modifying the watched file
                watch_path.write_text("unauthorized leak modification")

                with self.assertRaises(AssertionError) as ctx:
                    sb.assert_zero_leaks()

                self.assertIn("CRITICAL SANDBOX LEAK DETECTED", str(ctx.exception))
            finally:
                # Remove mock canary from snapshot so sb.close() does not complain about test canary
                sb._snapshot.pop(str(watch_path.resolve()), None)
                sb.close()

    def test_relative_crate_path_encoding(self):
        """
        Test 6: Synthesizes tracks in sb.mp3_dir, executes serato_macos_app.py via sb.run_cli,
        and parses generated .crate binary in Subcrates/.
        Verifies that all 'ptrk' entries are relative (Music/MP3/...) and contain NO host path leaks.
        """
        with SeratoSandbox(clean_on_exit=True) as sb:
            house_dir = sb.mp3_dir / "House"
            create_synthetic_mp3(house_dir / "Track01.mp3", title="Deep House 1")
            create_synthetic_mp3(house_dir / "Track02.mp3", title="Deep House 2")

            cmd = [
                "serato_macos_app.py",
                "--mp3", str(sb.mp3_dir),
                "--serato", str(sb.serato_dir),
                "--logs", str(sb.logs_dir),
            ]
            result = sb.run_cli(cmd)
            self.assertTrue(result.is_success, f"serato_macos_app.py failed: {result.stderr}")

            crate_file = sb.subcrates_dir / "House.crate"
            self.assertTrue(crate_file.exists(), f"Expected crate file at {crate_file}")

            paths = read_crate_paths(crate_file)
            self.assertEqual(len(paths), 2, f"Expected 2 tracks in crate, got: {paths}")

            for p in paths:
                self.assertTrue(
                    p.startswith("Music/MP3/House/"),
                    f"Path {p} should be relative starting with Music/MP3/House/"
                )
                self.assertNotIn(str(HOST_HOME), p, f"Path {p} leaked host home path!")
                self.assertNotIn("/Users/", p, f"Path {p} leaked absolute user path!")
                self.assertNotIn("/Volumes/", p, f"Path {p} leaked external volume path!")

            sb.assert_zero_leaks()


if __name__ == "__main__":
    unittest.main()
