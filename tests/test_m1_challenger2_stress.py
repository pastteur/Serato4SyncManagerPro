#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_m1_challenger2_stress.py
Empirical Stress Test Harness by Challenger 2 (Milestone 1).

Covers:
1. Load Stress Testing (1,000+ tracks batch, throughput > 2,000 tracks/sec, distinct SHA-256 seals).
2. Acoustic Signal Empirical Verification (click tracks 120/126/130 BPM, harmonic chords 8B/8A, transient alignment 2000ms).
3. Binary Crate Round-Trip Verification (500 tracks, custom ovct blocks, bit-for-bit fidelity).
4. Audio Seal Invariance and Edge Cases.
"""

import os
import shutil
import struct
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path
from typing import Dict, List, Tuple

from tests.fixtures.synthetic_library import (
    CANONICAL_VRSN_HEADER,
    LEGACY_ASCII_VRSN_HEADER,
    SyntheticTrack,
    build_id3v23_tag,
    build_mpeg_frames,
    create_crate_binary,
    create_synthetic_mp3,
    generate_standard_dj_library,
    read_crate_paths,
)
from tests.fixtures.acoustic_fixtures import (
    AcousticFixtureGenerator,
    EdgeCaseFixtureGenerator,
)
from sound_seal import compute_audio_seal
from music_analysis import analyze_file
from auto_cue import detect_audio_transients
from serato_macos_app import parse_crate_binary


class TestMilestone1ChallengerStress(unittest.TestCase):
    """
    Adversarial and Empirical Stress Verification for Milestone 1 Fixtures and Engines.
    """

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.test_dir.name)

    def tearDown(self):
        try:
            self.test_dir.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 1. Load Stress Testing
    # -------------------------------------------------------------------------

    def test_load_stress_1000_tracks_throughput_and_distinct_seals(self):
        """
        Stress-tests synthetic MP3 generation:
        - 1,000 tracks generated in a single batch with diverse metadata.
        - Throughput must exceed 2,000 tracks/second.
        - All 1,000 tracks must produce 100% distinct SHA-256 audio seals.
        """
        genres = ["House", "Techno", "Trance", "Drum & Bass", "Hip Hop", "Latin", "Disco", "Ambient"]
        keys = ["1A", "2A", "3A", "4A", "5A", "6A", "7A", "8A", "9A", "10A", "11A", "12A",
                "1B", "2B", "3B", "4B", "5B", "6B", "7B", "8B", "9B", "10B", "11B", "12B"]

        track_specs = []
        for i in range(1000):
            t = SyntheticTrack(
                title=f"Stress Track {i:04d} (Extended Mix)",
                artist=f"Producer {i % 80:02d}",
                album=f"Summer Anthems Vol. {i % 20 + 1}",
                bpm=f"{115.0 + (i % 50) * 0.5:.1f}",
                key=keys[i % len(keys)],
                genre=genres[i % len(genres)],
                year=str(2000 + (i % 25)),
                comment=f"Stress Harness Run Track {i}",
                duration_sec=2.0 + ((i % 10) * 0.1),
                track_id=i + 1,
            )
            track_specs.append(t)

        # Measure in-memory generation throughput
        t0 = time.perf_counter()
        mem_buffers = []
        for t in track_specs:
            tag_dict = {
                "TIT2": t.title, "TPE1": t.artist, "TALB": t.album,
                "TBPM": t.bpm, "TKEY": t.key, "TCON": t.genre,
                "TYER": t.year, "COMM": t.comment
            }
            id3 = build_id3v23_tag(tag_dict, encoding=3)
            audio = build_mpeg_frames(t.duration_sec, track_id=t.track_id)
            mem_buffers.append(id3 + audio)
        mem_elapsed = time.perf_counter() - t0
        mem_throughput = len(track_specs) / mem_elapsed

        # Measure disk write throughput
        t1 = time.perf_counter()
        file_paths = []
        for i, t in enumerate(track_specs):
            fpath = self.tmp_path / f"track_{i:04d}.mp3"
            create_synthetic_mp3(fpath, track=t)
            file_paths.append(fpath)
        disk_elapsed = time.perf_counter() - t1
        disk_throughput = len(track_specs) / disk_elapsed

        # Measure audio seal calculation throughput and distinctness
        t2 = time.perf_counter()
        hashes = set()
        for fpath in file_paths:
            seal = compute_audio_seal(str(fpath))
            self.assertTrue(bool(seal), f"Seal calculation failed for {fpath}")
            hashes.add(seal)
        seal_elapsed = time.perf_counter() - t2

        print(f"\n[STRESS 1000 TRACKS PERFORMANCE]")
        print(f"  • In-Memory Throughput: {mem_throughput:.1f} tracks/sec (total {mem_elapsed:.4f}s)")
        print(f"  • Disk Write Throughput: {disk_throughput:.1f} tracks/sec (total {disk_elapsed:.4f}s)")
        print(f"  • Audio Seal Verification: {len(hashes)}/1000 distinct seals in {seal_elapsed:.4f}s")

        # Assertions
        self.assertGreater(disk_throughput, 2000.0, f"Disk throughput {disk_throughput:.1f} < 2000 tracks/sec")
        self.assertEqual(len(hashes), 1000, "Collision detected in synthetic track audio seals!")

    def test_audio_seal_tag_invariance_and_audio_divergence(self):
        """
        Verifies that:
        1. Two tracks with identical audio but completely mutated ID3 tags yield identical SHA-256 seals.
        2. Two tracks with identical ID3 tags but different audio payloads yield different SHA-256 seals.
        """
        f1 = self.tmp_path / "track_tag_a.mp3"
        f2 = self.tmp_path / "track_tag_b.mp3"
        f3 = self.tmp_path / "track_audio_diff.mp3"

        # f1 and f2: identical audio (track_id=999, duration=2.5), divergent tags
        create_synthetic_mp3(f1, title="Original Title", artist="Original DJ", bpm="120.0", key="8A", track_id=999, duration_sec=2.5)
        create_synthetic_mp3(f2, title="Altered Title", artist="Completely New Artist", bpm="140.0", key="1B", track_id=999, duration_sec=2.5)

        # f3: identical tags as f1, but different audio (track_id=1000)
        create_synthetic_mp3(f3, title="Original Title", artist="Original DJ", bpm="120.0", key="8A", track_id=1000, duration_sec=2.5)

        seal1 = compute_audio_seal(str(f1))
        seal2 = compute_audio_seal(str(f2))
        seal3 = compute_audio_seal(str(f3))

        self.assertEqual(seal1, seal2, "Audio seal must be strictly invariant to ID3 tag changes.")
        self.assertNotEqual(seal1, seal3, "Audio seal must be strictly sensitive to audio frame differences.")

    # -------------------------------------------------------------------------
    # 2. Acoustic Signal Empirical Verification
    # -------------------------------------------------------------------------

    def test_acoustic_click_tracks_bpm_accuracy_and_confidence(self):
        """
        Generates click tracks at 120.0, 126.0, 130.0 BPM and tests them with music_analysis.analyze_file.
        Verifies BPM accuracy within ±0.5 and confidence >= 0.95.
        """
        test_bpms = [120.0, 126.0, 130.0]
        for target_bpm in test_bpms:
            fpath = self.tmp_path / f"click_{int(target_bpm)}.mp3"
            AcousticFixtureGenerator.generate_click_track(fpath, bpm=target_bpm, duration_sec=15.0)

            res = analyze_file(str(fpath))
            self.assertTrue(res.get("sucesso"), f"Analysis failed for BPM {target_bpm}: {res.get('erro')}")

            detected_bpm = res["bpm"]
            confidence = res["bpm_confianca"]
            bpm_error = abs(detected_bpm - target_bpm)

            print(f"\n[ACOUSTIC CLICK BPM {target_bpm}] Detected={detected_bpm:.1f}, Conf={confidence:.3f}, Error={bpm_error:.2f}")

            self.assertLessEqual(bpm_error, 0.5, f"BPM error {bpm_error} exceeded ±0.5 for target {target_bpm}")
            self.assertGreaterEqual(confidence, 0.95, f"BPM confidence {confidence} < 0.95 for target {target_bpm}")

    def test_acoustic_chord_camelot_key_detection(self):
        """
        Generates C Major and A Minor chords and verifies Camelot key detection yields '8B' and '8A'
        with confidence >= 0.80.
        """
        chord_specs = [
            ("C_major", "8B", "C major"),
            ("A_minor", "8A", "A minor"),
        ]

        for chord_name, expected_camelot, expected_name in chord_specs:
            fpath = self.tmp_path / f"chord_{chord_name}.mp3"
            AcousticFixtureGenerator.generate_chord_audio(fpath, chord=chord_name, duration_sec=10.0)

            res = analyze_file(str(fpath))
            self.assertTrue(res.get("sucesso"), f"Analysis failed for chord {chord_name}: {res.get('erro')}")

            detected_camelot = res["camelot"]
            detected_key_name = res["tom"]
            confidence = res["tom_confianca"]

            print(f"\n[ACOUSTIC CHORD {chord_name}] Detected={detected_camelot} ({detected_key_name}), Conf={confidence:.3f}")

            self.assertEqual(detected_camelot, expected_camelot, f"Expected Camelot {expected_camelot}, got {detected_camelot}")
            self.assertGreaterEqual(confidence, 0.80, f"Key confidence {confidence} < 0.80 for chord {chord_name}")

    def test_acoustic_transient_phase_alignment(self):
        """
        Generates a transient track with 2.0s silence + 8.0s audio.
        Verifies auto_cue.detect_audio_transients reports first_beat_ms == 2000.
        Also verifies boundary condition: 0.0s silence starts immediately (first_beat_ms == 100).
        """
        # Test 1: 2.0s silence
        f_2s = self.tmp_path / "transient_2s.mp3"
        AcousticFixtureGenerator.generate_transient_audio(f_2s, silence_sec=2.0, audio_sec=8.0)

        res_2s = detect_audio_transients(str(f_2s), duration_sec=10.0)
        print(f"\n[ACOUSTIC TRANSIENT 2.0s SILENCE] Result: {res_2s}")

        self.assertTrue(res_2s.get("has_transient"), "Transient must be detected for 2.0s silence + audio")
        self.assertEqual(res_2s.get("first_beat_ms"), 2000, f"Expected first_beat_ms == 2000, got {res_2s.get('first_beat_ms')}")
        self.assertTrue(res_2s.get("confiavel"), "Transient result must be marked confiavel=True")

        # Test 2: Boundary test with 0.0s silence (immediate audio burst)
        f_0s = self.tmp_path / "transient_0s.mp3"
        AcousticFixtureGenerator.generate_transient_audio(f_0s, silence_sec=0.0, audio_sec=8.0)

        res_0s = detect_audio_transients(str(f_0s), duration_sec=8.0)
        print(f"[ACOUSTIC TRANSIENT 0.0s SILENCE] Result: {res_0s}")
        self.assertTrue(res_0s.get("has_transient"))
        self.assertEqual(res_0s.get("first_beat_ms"), 100)

    # -------------------------------------------------------------------------
    # 3. Binary Crate Round-Trip Verification
    # -------------------------------------------------------------------------

    def test_binary_crate_roundtrip_500_tracks_and_custom_blocks(self):
        """
        Builds a .crate file containing 500 tracks and custom 'ovct' blocks.
        Parses it with serato_macos_app.parse_crate_binary.
        Verifies all 500 paths and custom blocks are preserved bit-for-bit.
        """
        # 500 distinct realistic track relative paths across diverse crates
        paths = [
            f"Music/MP3/Genre_{i % 15:02d}/Artist_{i % 40:03d} - Track_{i:04d} (Club Mix).mp3"
            for i in range(500)
        ]

        # Custom Serato blocks: ovct (column views), osrt (sorting column)
        col_title = b"ovct" + struct.pack(">I", 8) + b"song\x00\x00\x00\x64"
        col_artist = b"ovct" + struct.pack(">I", 10) + b"artist\x00\x00\x00\x96"
        col_bpm = b"ovct" + struct.pack(">I", 7) + b"bpm\x00\x00\x00\x46"
        sort_block = b"osrt" + struct.pack(">I", 5) + b"bpm\x00\x01"

        custom_blocks = [col_title, col_artist, col_bpm, sort_block]

        # Generate binary crate
        crate_binary = create_crate_binary(paths, custom_blocks=custom_blocks)
        self.assertTrue(crate_binary.startswith(CANONICAL_VRSN_HEADER))

        # Parse with production engine serato_macos_app.parse_crate_binary
        header, faixas, blocos_otrk, outros = parse_crate_binary(crate_binary)

        print(f"\n[BINARY CRATE 500 ROUNDTRIP]")
        print(f"  • Total crate bytes: {len(crate_binary):,} bytes")
        print(f"  • Header preserved: {header == CANONICAL_VRSN_HEADER}")
        print(f"  • Tracks parsed: {len(faixas)}/500")
        print(f"  • Custom blocks preserved: {len(outros)}/{len(custom_blocks)}")

        self.assertEqual(header, CANONICAL_VRSN_HEADER)
        self.assertEqual(len(faixas), 500)
        self.assertEqual(faixas, paths)
        self.assertEqual(len(blocos_otrk), 500)

        # Check custom blocks preserved bit-for-bit in identical order
        self.assertEqual(len(outros), len(custom_blocks))
        for orig, parsed in zip(custom_blocks, outros):
            self.assertEqual(orig, parsed, f"Custom block mismatch: {orig!r} != {parsed!r}")

        # Verify read_crate_paths matches
        crate_file = self.tmp_path / "test_500.crate"
        crate_file.write_bytes(crate_binary)
        read_paths = read_crate_paths(crate_file)
        self.assertEqual(read_paths, paths)

    def test_binary_crate_unicode_nfd_to_nfc_normalization(self):
        """
        Verifies that NFD decomposed Unicode paths are automatically normalized to NFC
        during parsing, matching Serato macOS filesystem standards.
        """
        nfd_raw = unicodedata.normalize("NFD", "Music/MP3/Samba & Café/Coração de Melodia.mp3")
        self.assertFalse(unicodedata.is_normalized("NFC", nfd_raw))

        crate_bin = create_crate_binary([nfd_raw])
        header, faixas, otrk, outros = parse_crate_binary(crate_bin)

        self.assertEqual(len(faixas), 1)
        self.assertTrue(unicodedata.is_normalized("NFC", faixas[0]))
        self.assertEqual(faixas[0], unicodedata.normalize("NFC", nfd_raw))

    # -------------------------------------------------------------------------
    # 4. Edge-Case Fixtures Empirical Verification
    # -------------------------------------------------------------------------

    def test_edge_case_fixtures_containment(self):
        """
        Empirically tests that EdgeCaseFixtureGenerator generates well-formed corruptions
        and engines handle them without unhandled exceptions.
        """
        # 1. 0-byte file
        z_file = EdgeCaseFixtureGenerator.create_zero_byte_file(self.tmp_path / "zero.mp3")
        self.assertEqual(z_file.stat().st_size, 0)
        self.assertEqual(compute_audio_seal(str(z_file)), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

        # 2. Truncated audio
        tr_file = EdgeCaseFixtureGenerator.create_truncated_audio(self.tmp_path / "short.mp3", duration_sec=1.5)
        self.assertGreater(tr_file.stat().st_size, 0)

        # 3. Bad synchsafe ID3 header
        bad_id3 = EdgeCaseFixtureGenerator.create_bad_synchsafe_id3(self.tmp_path / "corrupt_id3.mp3")
        # Ensure compute_audio_seal does not crash
        seal = compute_audio_seal(str(bad_id3))
        self.assertIsInstance(seal, str)

        # 4. Corrupted crate
        corrupt_crate = EdgeCaseFixtureGenerator.create_corrupted_crate(self.tmp_path / "corrupt.crate")
        header, faixas, otrk, outros = parse_crate_binary(corrupt_crate.read_bytes())
        self.assertIsNone(header)
        self.assertEqual(faixas, [])

        # 5. Path traversal crate
        trav_crate = EdgeCaseFixtureGenerator.create_traversal_path_crate(
            self.tmp_path / "trav.crate",
            "../../../../../../etc/passwd"
        )
        header, faixas, otrk, outros = parse_crate_binary(trav_crate.read_bytes())
        self.assertEqual(faixas, ["../../../../../../etc/passwd"])


if __name__ == "__main__":
    unittest.main()
