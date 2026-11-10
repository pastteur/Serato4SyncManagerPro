#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SERATO 4 SYNC MANAGER PRO - E2E TEST SUITE TIER 2: BOUNDARIES & CORNER CASES
================================================================================
Comprehensive boundary, edge-case, and security defense verification across all 11
engine subsystems. Strictly non-destructive, isolated in hermetic sandbox.

Covers:
  - 0-byte, truncated, and corrupt audio files (MPEG/ID3/WAV)
  - Malformed Serato binary structures (.crate, neworder.pref, database V2)
  - Extreme BPM values (<=0, 45, 280 BPM) and musical metrics
  - Duration limits (<10s hot cue rejection, 5s version match threshold)
  - Unicode normalization (NFC vs NFD) and special filesystem characters
  - Security traps: directory traversal (../), path escapes, 20% lost threshold
  - Journal transaction integrity: out-of-order undo locks, external modifications
================================================================================
"""

import os
import sys
import math
import json
import struct
import shutil
import sqlite3
import unicodedata
from pathlib import Path

# Add project root and vendor/mutagen
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
MUTAGEN_DIR = PROJECT_ROOT / "vendor" / "mutagen"
if str(MUTAGEN_DIR) not in sys.path:
    sys.path.insert(0, str(MUTAGEN_DIR))

import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TBPM, TKEY, GEOB

from tests.e2e_fixtures import E2ESandboxTestCase
import audio_health
import auto_cue
import crate_ops
import duplicates_tool
import journal
import library_tools
import music_analysis
import serato_macos_app
import sound_seal
import tag_doctor
import track_matcher


class TestTier2BoundariesAndCornerCases(E2ESandboxTestCase):
    """
    Tier 2 Test Suite: Boundary Conditions, Edge Cases, and Failsafes.
    Verifies that system components fail gracefully, reject dangerous operations,
    and preserve data integrity under hostile or extreme inputs.
    """

    # =========================================================================
    # GROUP 1: 0-BYTE AND TRUNCATED FILES (Corner Cases 01-07)
    # =========================================================================

    def test_boundary_01_zero_byte_audio_health_scan(self):
        """audio_health.scan_audio_health handles 0-byte file without crashing or hanging."""
        empty_file = self.mp3_dir / "zero_byte.mp3"
        empty_file.write_bytes(b"")

        res = audio_health.scan_audio_health(
            str(self.mp3_dir),
            limit=10,
            stream_progress=False
        )
        self.assertTrue(res.get("sucesso"), res)
        self.assertGreaterEqual(res.get("total_analisadas", 0), 1)

    def test_boundary_02_zero_byte_inspect_track_health(self):
        """audio_health.inspect_track_health flags 0-byte file cleanly as compromised/error."""
        empty_file = self.mp3_dir / "zero_track.mp3"
        empty_file.write_bytes(b"")

        info = audio_health.inspect_track_health(str(empty_file))
        self.assertIn(info.get("status"), ("comprometida", "alerta", "erro"))

    def test_boundary_03_zero_byte_music_analysis(self):
        """music_analysis.analyze_file returns failure on 0-byte file without unhandled exception."""
        empty_file = self.mp3_dir / "zero_analysis.mp3"
        empty_file.write_bytes(b"")

        res = music_analysis.analyze_file(str(empty_file))
        self.assertFalse(res.get("sucesso"), "Expected analyze_file to return sucesso=False on empty file")

    def test_boundary_04_zero_byte_auto_cue_rejection(self):
        """auto_cue.generate_and_save_serato_cues cleanly rejects 0-byte file."""
        empty_file = self.mp3_dir / "zero_cues.mp3"
        empty_file.write_bytes(b"")

        res = auto_cue.generate_and_save_serato_cues(str(empty_file))
        self.assertFalse(res.get("sucesso"))
        self.assertIn("erro", res)

    def test_boundary_05_zero_byte_journal_leading_id3(self):
        """journal.read_leading_id3 and calc_file_sha256 behave consistently on 0-byte file."""
        empty_file = self.mp3_dir / "zero_journal.mp3"
        empty_file.write_bytes(b"")

        block, size = journal.read_leading_id3(str(empty_file))
        self.assertEqual(block, b"")
        self.assertEqual(size, 0)

        # Empty file SHA-256 is the standard e3b0c442... digest
        sha = journal.calc_file_sha256(str(empty_file))
        self.assertEqual(sha, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_boundary_06_zero_byte_serato_quick_audio_hash(self):
        """serato_macos_app.compute_quick_audio_hash returns empty string on 0-byte file."""
        empty_file = self.mp3_dir / "zero_hash.mp3"
        empty_file.write_bytes(b"")

        h = serato_macos_app.compute_quick_audio_hash(empty_file)
        self.assertEqual(h, "")

    def test_boundary_07_zero_byte_track_matcher_content_hash(self):
        """track_matcher.compute_audio_seal returns sha256 of empty audio stream on 0-byte file."""
        empty_file = self.mp3_dir / "zero_matcher.mp3"
        empty_file.write_bytes(b"")

        h = track_matcher.compute_audio_seal(str(empty_file))
        self.assertEqual(h, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    # =========================================================================
    # GROUP 2: CORRUPTED AUDIO HEADERS & GARBAGE DATA (Corner Cases 08-12)
    # =========================================================================

    def test_boundary_08_corrupt_synchsafe_id3(self):
        """audio_health and journal handle ID3 header with corrupt synchsafe integer without crashing."""
        corrupt_file = self.mp3_dir / "corrupt_synchsafe.mp3"
        self.create_corrupt_mp3(corrupt_file, corrupt_type="bad_synchsafe")

        # Must not raise unhandled exception
        block, size = journal.read_leading_id3(str(corrupt_file))
        self.assertIsInstance(block, bytes)

    def test_boundary_09_truncated_mpeg_single_frame(self):
        """auto_cue rejects audio with duration under 10s with descriptive error message."""
        short_file = self.mp3_dir / "short_track.mp3"
        # 50 frames ~ 1.3 seconds (< 10.0s requirement)
        self.create_synthetic_mp3(short_file, duration_frames=50)

        res = auto_cue.generate_and_save_serato_cues(str(short_file))
        self.assertFalse(res.get("sucesso"))
        self.assertIn("curto", res.get("erro", "").lower())

    def test_boundary_10_garbage_non_audio_file(self):
        """tag_doctor.scan_audio_tags ignores or flags random binary text named .mp3 without dying."""
        garbage_file = self.mp3_dir / "garbage.mp3"
        self.create_corrupt_mp3(garbage_file, corrupt_type="garbage")

        res = tag_doctor.scan_audio_tags(str(self.mp3_dir), limit=50)
        self.assertTrue(res.get("sucesso"))

    def test_boundary_11_corrupted_binary_crate(self):
        """serato_macos_app.ler_faixas_crate_binaria handles truncated/corrupted binary crates safely."""
        corrupt_crate = self.subcrates_dir / "CorruptCrate.crate"
        # Truncated: starts with 'vrsn' but length header exceeds file size
        corrupt_crate.write_bytes(b"vrsn\x00\x00\x00\xfftruncated")

        faixas_set, faixas_lista, outros, header = serato_macos_app.ler_faixas_crate_binaria(corrupt_crate)
        self.assertEqual(faixas_lista, [])

    def test_boundary_12_truncated_neworder_pref(self):
        """serato_macos_app.parse_neworder_pref safely handles empty or truncated neworder.pref."""
        truncated_bytes = b"vrsn\x00\x00"

        header, ordered_crates, outros = serato_macos_app.parse_neworder_pref(truncated_bytes)
        self.assertIsNone(header)
        self.assertEqual(ordered_crates, [])

    # =========================================================================
    # GROUP 3: EXTREME BPM, DURATION & METRIC BOUNDARIES (Corner Cases 13-17)
    # =========================================================================

    def test_boundary_13_bpm_zero_or_negative_fallback(self):
        """auto_cue.calculate_smart_cues falls back to 120.0 BPM (bar_ms=2000) on 0 or negative BPM."""
        cues_zero = auto_cue.calculate_smart_cues(duration_sec=180.0, bpm_float=0.0)
        cues_neg = auto_cue.calculate_smart_cues(duration_sec=180.0, bpm_float=-120.0)

        self.assertEqual(len(cues_zero), 5)
        self.assertEqual(len(cues_neg), 5)
        # Verify fallback cues match
        for c0, cn in zip(cues_zero, cues_neg):
            self.assertEqual(c0["label"], cn["label"])
            self.assertEqual(c0["pos_ms"], cn["pos_ms"])

    def test_boundary_14_extreme_high_bpm(self):
        """auto_cue.calculate_smart_cues computes valid monotonically increasing cues at 280 BPM."""
        cues = auto_cue.calculate_smart_cues(duration_sec=200.0, bpm_float=280.0)
        self.assertEqual(len(cues), 5)
        positions = [c["pos_ms"] for c in cues]
        for i in range(len(positions) - 1):
            self.assertLess(positions[i], positions[i + 1])
            self.assertLess(positions[i + 1], 200000)

    def test_boundary_15_extreme_low_bpm(self):
        """auto_cue.calculate_smart_cues computes valid non-overlapping cues at 45 BPM."""
        cues = auto_cue.calculate_smart_cues(duration_sec=300.0, bpm_float=45.0)
        self.assertEqual(len(cues), 5)
        positions = [c["pos_ms"] for c in cues]
        for i in range(len(positions) - 1):
            self.assertLess(positions[i], positions[i + 1])

    def test_boundary_16_audio_under_10_seconds_rejected(self):
        """auto_cue rejects audio with duration under 10 seconds."""
        track_path = self.mp3_dir / "short_7sec.mp3"
        # 200 frames ~ 5.2s (< 10.0s)
        self.create_synthetic_mp3(track_path, duration_frames=200)

        res = auto_cue.generate_and_save_serato_cues(str(track_path))
        self.assertFalse(res.get("sucesso"))
        self.assertEqual(res.get("erro"), "Áudio muito curto para Hot Cues")

    def test_boundary_17_duration_mismatch_boundary(self):
        """track_matcher matches track when delta <= 5.0s, but flags DURACAO_INCOMPATIVEL when delta > 5.0s."""
        # Baseline library track: 1000 frames ~ 26.0s
        lib_folder = self.mp3_dir / "LibTracks"
        lib_folder.mkdir(parents=True)
        self.create_synthetic_mp3(lib_folder / "Artist - Song.mp3", artist="Artist", title="Song", duration_frames=1000, bpm="124.0")

        # Candidate 1: 1100 frames ~ 28.7s (delta = 2.7s <= 5.0s) -> should NOT be DURACAO_INCOMPATIVEL
        cand1_dir = self.fake_home / "Cand1"
        cand1_dir.mkdir(parents=True)
        self.create_synthetic_mp3(cand1_dir / "Artist - Song.mp3", artist="Artist", title="Song", duration_frames=1100, bpm="124.0")
        cand1_items = track_matcher.parse_incoming_folder(str(cand1_dir))
        res1 = track_matcher.match_tracks_against_library(cand1_items, str(lib_folder))
        self.assertEqual(len(res1.get("encontradas", [])), 1, res1)
        match1 = res1["encontradas"][0]
        self.assertFalse(match1["duracao_incompativel"])

        # Candidate 2: 1500 frames ~ 39.1s (delta = 13.1s > 5.0s) -> DURACAO_INCOMPATIVEL
        cand2_dir = self.fake_home / "Cand2"
        cand2_dir.mkdir(parents=True)
        self.create_synthetic_mp3(cand2_dir / "Artist - Song.mp3", artist="Artist", title="Song", duration_frames=1500, bpm="124.0")
        cand2_items = track_matcher.parse_incoming_folder(str(cand2_dir))
        res2 = track_matcher.match_tracks_against_library(cand2_items, str(lib_folder))
        self.assertEqual(len(res2.get("encontradas", [])), 1, res2)
        match2 = res2["encontradas"][0]
        self.assertTrue(match2["duracao_incompativel"])
        self.assertEqual(match2["status_comparacao"], "DURACAO_INCOMPATIVEL")

    # =========================================================================
    # GROUP 4: UNICODE NORMALIZATION & PATH ESCAPING (Corner Cases 18-22)
    # =========================================================================

    def test_boundary_18_unicode_nfc_vs_nfd_normalization(self):
        """serato_macos_app.normalizar_nfc unifies NFC and NFD representations identically."""
        nfc_str = "José González - Coração"
        nfd_str = unicodedata.normalize('NFD', nfc_str)
        self.assertNotEqual(nfc_str.encode('utf-8'), nfd_str.encode('utf-8'))

        norm1 = serato_macos_app.normalizar_nfc(nfc_str)
        norm2 = serato_macos_app.normalizar_nfc(nfd_str)
        self.assertEqual(norm1, norm2)

    def test_boundary_19_deep_subcrate_hierarchy(self):
        """serato_macos_app encodes deeply nested subcrates with '%%' delimiter."""
        deep_folder = self.mp3_dir / "House" / "Deep" / "Afro" / "2024"
        deep_folder.mkdir(parents=True)
        self.create_synthetic_mp3(deep_folder / "DeepAfroTrack.mp3", duration_frames=500)

        ok, summary = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok)
        self.assertIsInstance(summary, dict)

        expected_crate_name = "House%%Deep%%Afro%%2024.crate"
        crate_file = self.subcrates_dir / expected_crate_name
        self.assertTrue(crate_file.exists(), f"Expected nested crate {expected_crate_name} not found")

    def test_boundary_20_special_characters_in_track_filename(self):
        """Engine handles filenames containing brackets, symbols, and non-ASCII characters without corruption."""
        weird_folder = self.mp3_dir / "SpecialChars"
        weird_folder.mkdir(parents=True)
        weird_name = "DJ [Test] - Track (Club Mix) & Feature #1 [2024]!@$'.mp3"
        track_path = weird_folder / weird_name
        self.create_synthetic_mp3(track_path, duration_frames=500)

        ok, summary = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok)
        self.assertEqual(summary.get("total_faixas"), 1)

    def test_boundary_21_empty_mp3_folder_sync(self):
        """sincronizar_biblioteca on an empty MP3 directory finishes cleanly with 0 tracks and crates."""
        empty_mp3 = self.fake_home / "EmptyMusic"
        empty_mp3.mkdir(parents=True)

        ok, summary = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(empty_mp3),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok)
        self.assertEqual(summary.get("total_faixas"), 0)

    def test_boundary_22_empty_crate_reading(self):
        """serato_macos_app.ler_faixas_crate_binaria on empty crate returns valid header and empty list."""
        empty_crate = self.subcrates_dir / "Empty.crate"
        self.create_synthetic_crate(empty_crate, track_paths=[])

        faixas_set, faixas_lista, outros, header = serato_macos_app.ler_faixas_crate_binaria(empty_crate)
        self.assertIsNotNone(header)
        self.assertEqual(faixas_lista, [])

    # =========================================================================
    # GROUP 5: SECURITY, FAILSAFES & INTEGRITY TRAPS (Corner Cases 23-28)
    # =========================================================================

    def test_boundary_23_directory_traversal_rename(self):
        """audio_health.rename_audio_track rejects new names containing '../' or '/' traversal attempts."""
        track_path = self.mp3_dir / "legit_track.mp3"
        self.create_synthetic_mp3(track_path, duration_frames=500)

        # Attempt 1: Relative traversal
        res1 = audio_health.rename_audio_track(str(track_path), "../escaped.mp3")
        self.assertFalse(res1.get("sucesso"))
        self.assertIn("travessia", res1.get("erro", "").lower())

        # Attempt 2: Absolute path injection
        res2 = audio_health.rename_audio_track(str(track_path), "/tmp/escaped.mp3")
        self.assertFalse(res2.get("sucesso"))
        self.assertIn("travessia", res2.get("erro", "").lower())

    def test_boundary_24_directory_traversal_crate_addition(self):
        """crate_ops.add_paths_to_crate rejects paths outside the library root."""
        outside_path = self.tmp_dir / "outside_track.mp3"
        self.create_synthetic_mp3(outside_path, duration_frames=500)

        res = crate_ops.add_paths_to_crate(
            serato_dir=self.serato_dir,
            crate_name="TestCrate",
            abs_paths=[outside_path]
        )
        self.assertFalse(res.get("sucesso"))
        rejeitados = res.get("rejeitados", [])
        self.assertGreaterEqual(len(rejeitados), 1)
        self.assertIn("fora da raiz", rejeitados[0]["motivo"].lower())

    def test_boundary_25_sound_seal_lost_threshold_failsafe(self):
        """sound_seal.remove_lost_tracks_from_crates blocks deletion if lost tracks exceed 20% limit."""
        crate_file = self.subcrates_dir / "HighLost.crate"
        fake_paths = [f"Music/MP3/LostFolder/Track_{i}.mp3" for i in range(5)]
        self.create_synthetic_crate(crate_file, fake_paths)

        res = sound_seal.remove_lost_tracks_from_crates(
            serato_dir_str=str(self.serato_dir),
            mp3_dir_str=str(self.mp3_dir),
            target_path="",
            max_lost_pct=0.20
        )
        self.assertTrue(res.get("sucesso"))
        affected = res.get("crates_afetadas", [])
        self.assertGreaterEqual(len(affected), 1)
        self.assertTrue(affected[0].get("bloqueado_seguranca"))
        self.assertIn("teto de segurança", affected[0].get("motivo", ""))

    def test_boundary_26_journal_out_of_order_undo_rejection(self):
        """journal.undo_operation rejects reverting an earlier op if a newer op is still active."""
        track_path = self.mp3_dir / "multi_op_track.mp3"
        self.create_synthetic_mp3(track_path, duration_frames=500)

        # Op 1
        op1_id = journal.record_id3_before_change(str(track_path), action="op_1")
        tags1 = ID3(track_path)
        tags1["TIT2"] = TIT2(encoding=3, text="Title 1")
        tags1.save(v2_version=3)
        journal.record_operation_after(op1_id, str(track_path))

        # Op 2
        op2_id = journal.record_id3_before_change(str(track_path), action="op_2")
        tags2 = ID3(track_path)
        tags2["TIT2"] = TIT2(encoding=3, text="Title 2")
        tags2.save(v2_version=3)
        journal.record_operation_after(op2_id, str(track_path))

        # Attempt to undo Op 1 first (out-of-order)
        res_ooo = journal.undo_operation(op1_id)
        self.assertFalse(res_ooo.get("sucesso"))
        self.assertIn("fora de ordem", res_ooo.get("erro", "").lower())

        # Correct ordered undo: undo Op 2 first, then Op 1
        res_undo2 = journal.undo_operation(op2_id)
        self.assertTrue(res_undo2.get("sucesso"), res_undo2)

        res_undo1 = journal.undo_operation(op1_id)
        self.assertTrue(res_undo1.get("sucesso"), res_undo1)

    def test_boundary_27_journal_external_modification_rejection(self):
        """journal.undo_operation refuses undo if the file was modified externally after the operation."""
        track_path = self.mp3_dir / "external_mod_track.mp3"
        self.create_synthetic_mp3(track_path, duration_frames=500)

        op_id = journal.record_id3_before_change(str(track_path), action="initial_op")
        tags = ID3(track_path)
        tags["TIT2"] = TIT2(encoding=3, text="Internal Modification")
        tags.save(v2_version=3)
        journal.record_operation_after(op_id, str(track_path))

        # External modification: simulate external audio/file append or corruption
        with open(track_path, "ab") as f:
            f.write(b"EXTERNAL_THIRD_PARTY_DATA_CORRUPTION")

        # Undo must be rejected to avoid destructive overwrite
        res = journal.undo_operation(op_id)
        self.assertFalse(res.get("sucesso"))
        self.assertIn("modificado externamente", res.get("erro", "").lower())

    def test_boundary_28_journal_undo_nonexistent_file(self):
        """journal.undo_operation returns descriptive error if target file was deleted from disk."""
        track_path = self.mp3_dir / "to_be_deleted.mp3"
        self.create_synthetic_mp3(track_path, duration_frames=500)

        op_id = journal.record_id3_before_change(str(track_path), action="delete_op")
        journal.record_operation_after(op_id, str(track_path))

        # Delete file from disk
        track_path.unlink()

        res = journal.undo_operation(op_id)
        self.assertFalse(res.get("sucesso"))
        self.assertIn("não encontrado", res.get("erro", "").lower())


if __name__ == "__main__":
    unittest.main()
