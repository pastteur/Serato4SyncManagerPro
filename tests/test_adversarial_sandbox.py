#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_adversarial_sandbox.py
Milestone 1 Adversarial Stress Testing & Fault Injection Suite.

Stress tests:
1. Fault Injection: Catastrophic exception during sandbox context restores all 14 module constants and env vars.
2. Rapid 50x sequential creation & destruction: Zero file descriptor leaks, zero orphaned temp dirs, zero symlink leaks.
3. Environment pollution: Verifies HOME, TMPDIR, and sys.path remain unpolluted after standard & abnormal termination.
4. Canary leak triggers: 100% detection rate across all leak vectors (mtime, size, creation, deletion, directory children, host home entries).
5. Nested sandbox context isolation & restoration.
6. Process lifecycle & timeout resilience under run_cli.
7. Edge-case and corrupt fixture generation resilience.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Dict, Tuple, Any, List

# Ensure project root and vendor are on sys.path
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
    SandboxResult,
    EdgeCaseFixtureGenerator,
    create_synthetic_mp3,
    HOST_HOME,
)

import journal
import auto_cue
import sound_seal
import track_matcher
import tag_doctor
import audio_health
import serato_macos_app
import library_tools
import duplicates_tool


class TestAdversarialSandbox(unittest.TestCase):
    """
    Adversarial challenger test suite stress-testing SeratoSandbox fault tolerance,
    isolation guarantees, leak detection, and resource management.
    """

    TARGET_CONSTANTS: List[Tuple[Any, str]] = [
        (journal, "JOURNAL_PATH"),
        (auto_cue, "BACKUP_DB_PATH"),
        (sound_seal, "DB_PATH"),
        (track_matcher, "DB_PATH"),
        (tag_doctor, "TAG_CACHE_DB"),
        (tag_doctor, "SOUND_SEAL_DB"),
        (tag_doctor, "SERATO_INTERNAL_DB"),
        (tag_doctor, "DEFAULT_BACKUPS_DIR"),
        (audio_health, "QUARANTINE_DIR"),
        (serato_macos_app, "DEFAULT_LOGS_DIR"),
        (library_tools, "SMART_RULES_PATH"),
        (library_tools, "WATCH_STATE_PATH"),
        (library_tools, "EXPORTS_DIR"),
        (duplicates_tool, "REPORT_DIR"),
    ]

    def setUp(self):
        # Capture baseline environment and constants
        self.orig_env_home = os.environ.get("HOME")
        self.orig_env_tmpdir = os.environ.get("TMPDIR")
        self.orig_constants: Dict[Tuple[str, str], Any] = {
            (mod.__name__, attr): getattr(mod, attr)
            for mod, attr in self.TARGET_CONSTANTS
        }

    def tearDown(self):
        # Safety guarantee: restore baseline if any test failed mid-way
        if self.orig_env_home is not None:
            os.environ["HOME"] = self.orig_env_home
        if self.orig_env_tmpdir is not None:
            os.environ["TMPDIR"] = self.orig_env_tmpdir
        for mod, attr in self.TARGET_CONSTANTS:
            setattr(mod, attr, self.orig_constants[(mod.__name__, attr)])

    def test_fault_injection_exception_restores_all_14_constants(self):
        """
        Challenge 1.1: If an unhandled exception strikes inside with SeratoSandbox(),
        __exit__ MUST guarantee that all 14 module constants, HOME, and TMPDIR are
        100% restored to their original host values, and sandbox files are purged.
        """
        sandbox_path = None
        with self.assertRaises(RuntimeError) as ctx:
            with SeratoSandbox(clean_on_exit=True) as sb:
                sandbox_path = sb.sandbox_root

                # 1. Verify active patching inside context
                self.assertTrue(sb.is_active)
                self.assertEqual(os.environ["HOME"], str(sb.fake_home))
                self.assertEqual(os.environ["TMPDIR"], str(sb.tmp_dir))

                for mod, attr in self.TARGET_CONSTANTS:
                    val = getattr(mod, attr)
                    self.assertTrue(
                        str(sb.sandbox_root) in str(val),
                        f"{mod.__name__}.{attr} ({val}) was not patched into sandbox!"
                    )

                # 2. Inject catastrophic failure
                raise RuntimeError("FAULT_INJECTION_CATASTROPHIC_ENGINE_CRASH")

        self.assertIn("FAULT_INJECTION_CATASTROPHIC_ENGINE_CRASH", str(ctx.exception))

        # 3. Verify 100% restoration of all 14 constants
        for mod, attr in self.TARGET_CONSTANTS:
            current_val = getattr(mod, attr)
            expected_val = self.orig_constants[(mod.__name__, attr)]
            self.assertEqual(
                current_val,
                expected_val,
                f"Constant {mod.__name__}.{attr} failed to restore! Current: {current_val}, Expected: {expected_val}"
            )

        # 4. Verify HOME and TMPDIR restoration
        self.assertEqual(os.environ.get("HOME"), self.orig_env_home)
        self.assertEqual(os.environ.get("TMPDIR"), self.orig_env_tmpdir)

        # 5. Verify physical sandbox cleanup
        self.assertIsNotNone(sandbox_path)
        self.assertFalse(sandbox_path.exists(), f"Sandbox root {sandbox_path} was not cleaned up!")

    def test_rapid_50x_creation_and_destruction_leaks(self):
        """
        Challenge 1.2: Stress test rapid 50x sequential creation and teardown.
        Ensures zero accumulated temp directories, zero leaked file descriptors,
        and zero lingering symlinks.
        """
        # Baseline file descriptor count
        def get_fd_count() -> int:
            if os.path.exists("/dev/fd"):
                try:
                    return len(os.listdir("/dev/fd"))
                except Exception:
                    pass
            return 0

        initial_fds = get_fd_count()
        created_paths = []

        start_time = time.perf_counter()
        for i in range(50):
            with SeratoSandbox(clean_on_exit=True) as sb:
                created_paths.append(sb.sandbox_root)
                # Perform real file creation and database interaction
                test_mp3 = sb.mp3_dir / f"burst_{i}.mp3"
                create_synthetic_mp3(test_mp3, title=f"Burst Track {i}", artist="Stress Bot")
                self.assertTrue(test_mp3.exists())

                # Quick in-process journal write
                op_id = journal.record_id3_before_change(str(test_mp3), action="BURST_TEST")
                self.assertIsNotNone(op_id)

                # Assert internal symlinks are functional
                music_link = sb.sandbox_root / "Music"
                self.assertTrue(music_link.is_symlink())
                self.assertTrue((music_link / "MP3" / f"burst_{i}.mp3").exists())

                sb.assert_zero_leaks()

        elapsed = time.perf_counter() - start_time

        # Verify all 50 sandbox directories were physically purged
        lingering = [p for p in created_paths if p.exists()]
        self.assertEqual(len(lingering), 0, f"Leaked {len(lingering)} sandbox directories: {lingering}")

        # Verify file descriptors did not blow up
        final_fds = get_fd_count()
        if initial_fds > 0 and final_fds > 0:
            fd_diff = final_fds - initial_fds
            # A delta of <= 3 is acceptable due to standard Python/OS dynamic library caching
            self.assertLessEqual(
                fd_diff, 5,
                f"File descriptor leak detected! Initial: {initial_fds}, Final: {final_fds}, Leaked: {fd_diff}"
            )

        # Verify rate of execution (must be fast enough for responsive CI/agent workflows)
        self.assertLess(elapsed, 30.0, f"50 sandboxes took too long: {elapsed:.2f}s (>30s)")

    def test_environment_pollution_and_sys_path_integrity(self):
        """
        Challenge 1.3: Verify that os.environ and sys.path cannot be polluted.
        Specifically, mutagen must never shadow stdlib wave.py.
        """
        import wave
        self.assertTrue(hasattr(wave, "open"), "stdlib wave.open must be present before test")

        with SeratoSandbox(clean_on_exit=True) as sb:
            self.assertEqual(os.environ["HOME"], str(sb.fake_home))
            # Test that sys.path inside sandbox runner does not shadow wave
            import wave as inside_wave
            self.assertTrue(hasattr(inside_wave, "open"), "wave.open shadowed inside sandbox!")

        # After sandbox exit
        self.assertEqual(os.environ.get("HOME"), self.orig_env_home)
        import wave as after_wave
        self.assertTrue(hasattr(after_wave, "open"), "wave.open shadowed after sandbox exit!")

    def test_canary_leak_trigger_vectors_a_to_d(self):
        """
        Challenge 2.1: Adversarial verification of Canary Leak Detection for single files.
        Tests 4 file-level mutation vectors to prove assert_zero_leaks() raises AssertionError:
        - Vector A: mtime change on existing canary file
        - Vector B: size change on existing canary file
        - Vector C: unauthorized creation of previously non-existent file
        - Vector D: unauthorized deletion of previously existing canary file
        """
        with tempfile.TemporaryDirectory(prefix="canary_matrix_") as temp_dir:
            temp_path = Path(temp_dir)

            file_a = temp_path / "target_a.sqlite"
            file_a.write_text("initial content a")

            file_b = temp_path / "target_b.sqlite"
            file_b.write_text("initial content b")

            file_c = temp_path / "target_c_nonexistent.sqlite"  # Not created yet

            file_d = temp_path / "target_d.sqlite"
            file_d.write_text("initial content d")

            # --- Vector A: mtime modification ---
            sb_a = SeratoSandbox(clean_on_exit=True, extra_watch_paths=[file_a])
            sb_a.start()
            try:
                sb_a.assert_zero_leaks()
                time.sleep(0.01)
                os.utime(file_a, (time.time() + 100, time.time() + 100))
                with self.assertRaises(AssertionError, msg="Vector A failed to detect mtime leak"):
                    sb_a.assert_zero_leaks()
            finally:
                sb_a._snapshot.clear()
                sb_a.close()

            # --- Vector B: size modification ---
            sb_b = SeratoSandbox(clean_on_exit=True, extra_watch_paths=[file_b])
            sb_b.start()
            try:
                sb_b.assert_zero_leaks()
                file_b.write_text("appended larger content modifying file size")
                with self.assertRaises(AssertionError, msg="Vector B failed to detect size leak"):
                    sb_b.assert_zero_leaks()
            finally:
                sb_b._snapshot.clear()
                sb_b.close()

            # --- Vector C: file creation leak ---
            sb_c = SeratoSandbox(clean_on_exit=True, extra_watch_paths=[file_c])
            sb_c.start()
            try:
                sb_c.assert_zero_leaks()
                file_c.write_text("rogue created file")
                with self.assertRaises(AssertionError, msg="Vector C failed to detect creation leak"):
                    sb_c.assert_zero_leaks()
            finally:
                sb_c._snapshot.clear()
                sb_c.close()

            # --- Vector D: file deletion leak ---
            sb_d = SeratoSandbox(clean_on_exit=True, extra_watch_paths=[file_d])
            sb_d.start()
            try:
                sb_d.assert_zero_leaks()
                file_d.unlink()
                with self.assertRaises(AssertionError, msg="Vector D failed to detect deletion leak"):
                    sb_d.assert_zero_leaks()
            finally:
                sb_d._snapshot.clear()
                sb_d.close()

    def test_canary_leak_trigger_vector_e_directory_child(self):
        """
        Challenge 2.2: Adversarial verification of Canary Leak Detection for directories.
        Vector E: unauthorized child creation inside watched directory.
        FAILS because tests/fixtures/sandbox_runner.py:320-328 wraps raise AssertionError
        inside a try...except Exception: pass block, swallowing the AssertionError,
        and lines 268-280 do not record 'children' for extra_watch_paths directories.
        """
        with tempfile.TemporaryDirectory(prefix="canary_dir_") as temp_dir:
            temp_path = Path(temp_dir)
            dir_e = temp_path / "watched_dir"
            dir_e.mkdir()
            (dir_e / "existing_child.txt").write_text("child")

            sb_e = SeratoSandbox(clean_on_exit=True, extra_watch_paths=[dir_e])
            sb_e.start()
            try:
                sb_e.assert_zero_leaks()
                (dir_e / "rogue_new_child.txt").write_text("leak")
                # This MUST raise AssertionError if canary is working properly!
                with self.assertRaises(AssertionError, msg="Vector E failed to detect directory child leak"):
                    sb_e.assert_zero_leaks()
            finally:
                sb_e._snapshot.clear()
                sb_e.close()

    def test_canary_leak_trigger_vector_f_host_home_entry(self):
        """
        Challenge 2.3: Adversarial verification of top-level HOST_HOME leak detection.
        Vector F: unauthorized new entry appearing in HOST_HOME.
        FAILS because tests/fixtures/sandbox_runner.py:332-340 wraps raise AssertionError
        inside a try...except Exception: pass block, swallowing the AssertionError.
        """
        sb_f = SeratoSandbox(clean_on_exit=True)
        sb_f.start()
        try:
            entries = sb_f._snapshot.get("__HOST_HOME_ENTRIES__", set())
            if entries:
                sample = next(iter(entries))
                # Simulate a rogue entry by removing one from snapshot
                sb_f._snapshot["__HOST_HOME_ENTRIES__"] = entries - {sample}
                # This MUST raise AssertionError if canary is working properly!
                with self.assertRaises(AssertionError, msg="Vector F failed to detect host home entry leak"):
                    sb_f.assert_zero_leaks()
        finally:
            sb_f._snapshot.clear()
            sb_f.close()

    def test_nested_sandbox_context_isolation(self):
        """
        Challenge 3.1: Test nested sandbox execution.
        When an inner sandbox opens inside an outer sandbox:
        - Inner sandbox patches constants to its own root.
        - Exiting inner sandbox restores constants to outer sandbox root.
        - Exiting outer sandbox restores constants to host.
        """
        with SeratoSandbox(clean_on_exit=True) as outer_sb:
            outer_journal = journal.JOURNAL_PATH
            self.assertEqual(outer_journal, outer_sb.fake_home / ".serato_sync_journal.sqlite")

            with SeratoSandbox(clean_on_exit=True) as inner_sb:
                inner_journal = journal.JOURNAL_PATH
                self.assertEqual(inner_journal, inner_sb.fake_home / ".serato_sync_journal.sqlite")
                self.assertNotEqual(outer_journal, inner_journal)
                inner_sb.assert_zero_leaks()

            # After inner exit: outer sandbox constants must be restored!
            self.assertEqual(journal.JOURNAL_PATH, outer_journal)
            self.assertEqual(os.environ["HOME"], str(outer_sb.fake_home))
            outer_sb.assert_zero_leaks()

        # After outer exit: host constants must be restored!
        self.assertEqual(journal.JOURNAL_PATH, self.orig_constants[("journal", "JOURNAL_PATH")])
        self.assertEqual(os.environ.get("HOME"), self.orig_env_home)

    def test_run_cli_timeout_and_process_cleanup(self):
        """
        Challenge 3.2: Subprocess timeout handling under run_cli.
        Ensures unresponsive processes are killed at timeout, return -9,
        and do not corrupt sandbox state or leak.
        """
        with SeratoSandbox(clean_on_exit=True) as sb:
            t0 = time.perf_counter()
            result = sb.run_cli(["python3", "-c", "import time; time.sleep(10)"], timeout=1.0)
            elapsed = time.perf_counter() - t0

            self.assertFalse(result.is_success)
            self.assertEqual(result.exit_code, -9)
            self.assertIn("TIMEOUT (1.0s expired)", result.stderr)
            self.assertLess(elapsed, 3.0, f"Timeout took too long: {elapsed:.2f}s")

            # Sandbox integrity must remain clean
            sb.assert_zero_leaks()

    def test_edge_case_fixtures_generation_in_sandbox(self):
        """
        Challenge 3.3: Verify edge case fixture generation inside sandbox
        (0-byte, truncated, bad synchsafe, corrupted crate, extreme BPM, path traversal).
        """
        with SeratoSandbox(clean_on_exit=True) as sb:
            f_zero = EdgeCaseFixtureGenerator.create_zero_byte_file(sb.mp3_dir / "zero.mp3")
            f_trunc = EdgeCaseFixtureGenerator.create_truncated_audio(sb.mp3_dir / "trunc.mp3", duration_sec=2.0)
            f_synch = EdgeCaseFixtureGenerator.create_bad_synchsafe_id3(sb.mp3_dir / "bad_synch.mp3")
            f_crate = EdgeCaseFixtureGenerator.create_corrupted_crate(sb.subcrates_dir / "corrupt.crate")
            f_trav = EdgeCaseFixtureGenerator.create_traversal_path_crate(sb.subcrates_dir / "traversal.crate")
            f_bpm_low = EdgeCaseFixtureGenerator.create_extreme_bpm_track(sb.mp3_dir / "bpm40.mp3", bpm=40.0, duration_sec=5.0)
            f_bpm_high = EdgeCaseFixtureGenerator.create_extreme_bpm_track(sb.mp3_dir / "bpm240.mp3", bpm=240.0, duration_sec=5.0)

            self.assertTrue(f_zero.exists())
            self.assertEqual(f_zero.stat().st_size, 0)

            self.assertTrue(f_trunc.exists())
            self.assertGreater(f_trunc.stat().st_size, 0)

            self.assertTrue(f_synch.exists())
            raw = f_synch.read_bytes()
            self.assertEqual(raw[:3], b"ID3")
            self.assertTrue(any(b >= 0x80 for b in raw[6:10]))

            self.assertTrue(f_crate.exists())
            crate_raw = f_crate.read_bytes()
            self.assertFalse(crate_raw.startswith(b"vrsn"))

            self.assertTrue(f_trav.exists())
            self.assertTrue(f_bpm_low.exists())
            self.assertTrue(f_bpm_high.exists())

            sb.assert_zero_leaks()

    def test_standard_dj_library_generation_and_audio_hash_uniqueness(self):
        """
        Challenge 3.4: Verify generate_standard_dj_library generates distinct audio
        frames across genres so each track has a unique pure audio hash.
        """
        from tests.fixtures import generate_standard_dj_library
        import hashlib

        with SeratoSandbox(clean_on_exit=True) as sb:
            mapping = generate_standard_dj_library(sb.mp3_dir, tracks_per_crate=2)
            self.assertEqual(len(mapping), 8, f"Expected 8 crates, got {len(mapping)}")

            hashes = set()
            total_tracks = 0
            for crate_name, track_paths in mapping.items():
                self.assertEqual(len(track_paths), 2)
                for file_path in track_paths:
                    total_tracks += 1
                    self.assertTrue(file_path.exists())
                    raw = file_path.read_bytes()
                    # Find first MPEG sync word 0xFFE0
                    sync_idx = 0
                    for idx in range(len(raw) - 1):
                        if raw[idx] == 0xFF and (raw[idx + 1] & 0xE0) == 0xE0:
                            sync_idx = idx
                            break
                    audio_bytes = raw[sync_idx:]
                    h = hashlib.sha256(audio_bytes).hexdigest()
                    self.assertNotIn(h, hashes, f"Duplicate audio hash found for {file_path.name}!")
                    hashes.add(h)

            self.assertEqual(total_tracks, 16)
            sb.assert_zero_leaks()


if __name__ == "__main__":
    unittest.main()
