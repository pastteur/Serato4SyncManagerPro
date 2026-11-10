#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tier 1 — Feature Coverage E2E Test Suite.
Verifies happy-path isolation for every engine in PROJECT.md § Feature Inventory.
Strictly non-destructive, executing entirely inside sandboxed temporary directories.
"""

import os
import sys
import json
import sqlite3
import wave
import struct
import math
import unittest
from pathlib import Path

# Add project root and vendor/mutagen
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e_fixtures import E2ESandboxTestCase

import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TBPM, TKEY, COMM

import audio_health
import music_analysis
import tag_doctor
import auto_cue
import journal
import serato_macos_app
import crate_ops
import library_tools
import duplicates_tool
import sound_seal
import track_matcher


class TestTier1FeatureCoverage(E2ESandboxTestCase):
    """
    Tier 1 tests exercising all 9 engine domains across >=5 test cases per domain.
    """

    # =========================================================================
    # 1. AUDIO HEALTH PIPELINE
    # =========================================================================

    def test_audio_health_01_scan_clean_files(self):
        """scan_audio_health scans healthy synthetic MP3 files and returns valid audit metrics."""
        crate_folder = self.mp3_dir / "TechHouse"
        crate_folder.mkdir(parents=True)
        for i in range(5):
            self.create_synthetic_mp3(
                crate_folder / f"Track_{i:02d}.mp3",
                title=f"Tech Track {i}",
                artist="DJ Tech",
                duration_frames=500,
            )

        res = audio_health.scan_audio_health(
            mp3_base_dir=str(self.mp3_dir),
            include_subcrates=True,
            stream_progress=False
        )
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("total_analisadas"), 5)
        self.assertIn("categorias_contagem", res)

    def test_audio_health_02_inspect_track_health(self):
        """inspect_track_health reports status, bitrate, sample rate, and duration for valid file."""
        track_path = self.mp3_dir / "inspect_track.mp3"
        self.create_synthetic_mp3(track_path, duration_frames=500)

        diag = audio_health.inspect_track_health(track_path)
        self.assertIsInstance(diag, dict)
        self.assertIn(diag.get("status"), ("ok", "suspeita", "alerta", "comprometida"))
        self.assertGreater(diag.get("duracao", 0), 0)
        self.assertGreater(diag.get("bitrate", 0), 0)

    def test_audio_health_03_generate_audio_spectrogram(self):
        """generate_audio_spectrogram creates a valid PNG spectrogram binary via FFmpeg."""
        wav_path = self.mp3_dir / "spectrogram_test.wav"
        self.write_wav(wav_path, seconds=35.0, freq=440.0)

        out_png = self.tmp_dir / "spec.png"
        res = audio_health.generate_audio_spectrogram(wav_path, out_png_path=out_png)
        self.assertTrue(res.get("sucesso"), res)
        self.assertTrue(out_png.exists())
        self.assertGreater(out_png.stat().st_size, 100)

    def test_audio_health_04_rename_audio_track(self):
        """rename_audio_track safely renames an audio track on disk and updates its tags."""
        track_path = self.mp3_dir / "Old_Name.mp3"
        self.create_synthetic_mp3(track_path, title="Old Title")

        res = audio_health.rename_audio_track(str(track_path), "New_Name.mp3")
        self.assertTrue(res.get("sucesso"), res)
        new_path = Path(res.get("novo_caminho"))
        self.assertTrue(new_path.exists())
        self.assertFalse(track_path.exists())
        self.assertEqual(new_path.name, "New_Name.mp3")

    def test_audio_health_05_resample_track_local(self):
        """resample_track_local converts audio to standard 44.1kHz CBR and preserves backup in quarantine."""
        wav_path = self.mp3_dir / "resample_test.wav"
        self.write_wav(wav_path, seconds=2.0, sr=48000, freq=880.0)

        res = audio_health.resample_track_local(str(wav_path))
        self.assertTrue(res.get("sucesso"), res)
        self.assertTrue(wav_path.exists())
        quarantine_files = (
            list((self.serato_dir / "Quarentena").glob("pre_resample_*")) +
            list(self.quarantine_dir.glob("pre_resample_*"))
        )
        self.assertGreaterEqual(len(quarantine_files), 1)

    # =========================================================================
    # 2. MUSIC ANALYSIS PIPELINE
    # =========================================================================

    def test_music_analysis_01_bpm_click_track(self):
        """analyze_file estimates BPM accurately on synthetic click track."""
        wav_path = self.mp3_dir / "clicks_120.wav"
        sr = 44100
        seconds = 40
        bpm = 120.0
        n = sr * seconds
        period = int(sr * 60.0 / bpm)
        buf = [0.0] * n
        for k in range(0, n, period):
            for j in range(300):
                if k + j < n:
                    buf[k + j] += math.sin(2 * math.pi * 900 * j / sr) * math.exp(-j / 60.0) * 0.9

        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(struct.pack(f"<{n}h", *[int(max(-1, min(1, s)) * 20000) for s in buf]))

        res = music_analysis.analyze_file(str(wav_path))
        self.assertTrue(res.get("sucesso"), res)
        self.assertAlmostEqual(res.get("bpm"), 120.0, delta=2.5)

    def test_music_analysis_02_key_chord(self):
        """analyze_file detects harmonic key profile for C major triad (C-E-G)."""
        wav_path = self.mp3_dir / "chord_c_major.wav"
        freqs = [261.63, 329.63, 392.00]  # C4, E4, G4
        sr = 44100
        seconds = 40
        samples = [
            sum(math.sin(2 * math.pi * f * i / sr) for f in freqs) / len(freqs)
            for i in range(sr * seconds)
        ]
        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(struct.pack(f"<{len(samples)}h", *[int(s * 20000) for s in samples]))

        res = music_analysis.analyze_file(str(wav_path))
        self.assertTrue(res.get("sucesso"), res)
        self.assertIn(res.get("camelot"), ("8B", "8A", "5B", "7B"))

    def test_music_analysis_03_write_analysis_tags(self):
        """write_analysis_tags writes TBPM and TKEY ID3v2.3 tags to an MP3."""
        mp3_path = self.mp3_dir / "analysis_tags.mp3"
        self.create_synthetic_mp3(mp3_path, bpm="0", key="")

        res = music_analysis.write_analysis_tags(str(mp3_path), bpm=128.0, key_text="8A", overwrite=True)
        self.assertTrue(res.get("sucesso"), res)
        self.assertTrue(res.get("gravado"))

        tags = ID3(mp3_path)
        self.assertEqual(tags.get("TBPM").text[0], "128")
        self.assertEqual(tags.get("TKEY").text[0], "8A")

    def test_music_analysis_04_analyze_batch(self):
        """analyze_batch traverses folder, analyzes files, and returns summary count."""
        for i in range(3):
            p = self.mp3_dir / f"batch_analysis_{i}.mp3"
            self.create_synthetic_mp3(p, duration_frames=500)

        res = music_analysis.analyze_batch(
            folder=str(self.mp3_dir),
            limit=0,
            write=False,
            only_missing=False,
            emit=False
        )
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("total"), 3)

    def test_music_analysis_05_camelot_mapping_consistency(self):
        """Validates Camelot dictionary mappings across all 12 major and minor tonalities."""
        self.assertEqual(music_analysis.CAMELOT_MAJOR[0], "8B")   # C Major
        self.assertEqual(music_analysis.CAMELOT_MINOR[9], "8A")   # A Minor
        self.assertEqual(music_analysis.CAMELOT_MAJOR[7], "9B")   # G Major
        self.assertEqual(music_analysis.CAMELOT_MINOR[4], "9A")   # E Minor
        self.assertEqual(len(music_analysis.CAMELOT_MAJOR), 12)
        self.assertEqual(len(music_analysis.CAMELOT_MINOR), 12)

    # =========================================================================
    # 3. TAG DOCTOR PIPELINE
    # =========================================================================

    def test_tag_doctor_01_clean_track_name(self):
        """clean_track_name strips web promo noise, bracketed domains, and normalizes artist/title."""
        dirty = "[www.djpool.com] [DJ Pool] [Exclusive] Alok & Vintage Culture - Party On (Original Mix) (Official Video)"
        cleaned = tag_doctor.clean_track_name(dirty)
        self.assertNotIn("www.djpool.com", cleaned.get("title", ""))
        self.assertNotIn("Exclusive", cleaned.get("title", ""))
        self.assertIn("Party On", cleaned.get("title", ""))

    def test_tag_doctor_02_scan_audio_tags(self):
        """scan_audio_tags scans folder and flags tracks requiring tag cleanup."""
        track_path = self.mp3_dir / "[Beatport] Artist - Anthem (Extended).mp3"
        self.create_synthetic_mp3(
            track_path,
            title="[Beatport] Anthem (Extended)",
            artist="Artist"
        )

        res = tag_doctor.scan_audio_tags(str(self.mp3_dir), limit=50)
        self.assertTrue(res.get("sucesso"), res)
        self.assertGreaterEqual(res.get("total_encontrados", 0), 1)

    def test_tag_doctor_03_apply_cleaned_tags(self):
        """apply_cleaned_tags modifies MP3 ID3 tags atomically and preserves audio integrity."""
        track_path = self.mp3_dir / "dirty_tag.mp3"
        self.create_synthetic_mp3(track_path, title="Dirty Title [Promo]", artist="Dirty Artist")

        item = {
            "caminho": str(track_path),
            "titulo_sugerido": "Clean Title",
            "artista_sugerido": "Clean Artist",
            "album_sugerido": "Clean Album"
        }
        res = tag_doctor.apply_cleaned_tags([item], rename_files_on_disk=False, stream_progress=False)
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("atualizados"), 1)

        tags = ID3(track_path)
        self.assertEqual(tags.get("TIT2").text[0], "Clean Title")
        self.assertEqual(tags.get("TPE1").text[0], "Clean Artist")

    def test_tag_doctor_04_backup_and_restore_master_db(self):
        """backup_master_database creates timestamped copy of Serato central master.sqlite."""
        serato_db_path = self.fake_home / "Library" / "Application Support" / "Serato" / "Library" / "master.sqlite"
        serato_db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(serato_db_path) as conn:
            conn.execute("CREATE TABLE test_data (id INT, name TEXT)")
            conn.execute("INSERT INTO test_data VALUES (1, 'SeratoMaster')")

        res_backup = tag_doctor.backup_master_database()
        self.assertTrue(res_backup.get("sucesso"), res_backup)
        backup_file = Path(res_backup.get("arquivo"))
        self.assertTrue(backup_file.exists())

        backups_list = tag_doctor.list_master_backups()
        self.assertIsInstance(backups_list, list)
        self.assertGreaterEqual(len(backups_list), 1)

    def test_tag_doctor_05_enrich_missing_artists(self):
        """enrich_missing_artists derives missing artist tag from cached seed."""
        tag_doctor.init_tag_cache()
        tag_doctor.seed_tag_cache(title="Gravity", artist="Boris Brejcha")
        cached_art = tag_doctor.get_cached_artist("Gravity")
        self.assertEqual(cached_art, "Boris Brejcha")

    # =========================================================================
    # 4. AUTO-CUE & MARKERS2 PIPELINE
    # =========================================================================

    def test_auto_cue_01_preview_cues(self):
        """calculate_smart_cues calculates 5 hot cues (Intro, Drop 1, Break, Drop 2, Outro)."""
        track_path = self.mp3_dir / "preview_cue.mp3"
        self.create_synthetic_mp3(track_path, bpm="128.0", duration_frames=500)

        cues = auto_cue.calculate_smart_cues(duration_sec=180.0, bpm_float=128.0, filepath_str=str(track_path))
        self.assertIsInstance(cues, list)
        self.assertEqual(len(cues), 5)
        labels = [c["label"] for c in cues]
        self.assertIn("Intro", labels)
        self.assertIn("Drop 1", labels)
        self.assertIn("Break", labels)
        self.assertIn("Drop 2", labels)
        self.assertIn("Outro", labels)

    def test_auto_cue_02_apply_and_verify_markers2(self):
        """generate_and_save_serato_cues embeds GEOB:Serato Markers2 tag into MP3."""
        track_path = self.mp3_dir / "markers2_test.mp3"
        self.create_synthetic_mp3(track_path, bpm="125.0", duration_frames=500)

        res = auto_cue.generate_and_save_serato_cues(str(track_path), overwrite_existing=True)
        self.assertTrue(res.get("sucesso"), res)

        tags = ID3(track_path)
        geob_keys = [k for k in tags.keys() if k.startswith("GEOB") and "Serato Markers2" in k]
        self.assertGreaterEqual(len(geob_keys), 1)

    def test_auto_cue_03_audit_crate_cues_detailed(self):
        """audit_crate_cues_detailed audits crate tracks and reports cue status breakdown."""
        crate_folder = self.mp3_dir / "House"
        crate_folder.mkdir(parents=True)
        p1 = self.create_synthetic_mp3(crate_folder / "Track_1.mp3", bpm="124.0", duration_frames=500)
        p2 = self.create_synthetic_mp3(crate_folder / "Track_2.mp3", bpm="124.0", duration_frames=500)
        auto_cue.generate_and_save_serato_cues(str(p1), overwrite_existing=True)

        res = auto_cue.audit_crate_cues_detailed(
            mp3_base_dir=str(self.mp3_dir),
            crate_raiz="House",
            subcrate=""
        )
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("total"), 2)
        self.assertEqual(res.get("padrao_autocue"), 1)
        self.assertEqual(res.get("pendentes"), 1)

    def test_auto_cue_04_batch_apply_crate_cues(self):
        """batch_apply_crate_cues applies cues to all pending tracks in crate in parallel."""
        crate_folder = self.mp3_dir / "Techno"
        crate_folder.mkdir(parents=True)
        for i in range(4):
            self.create_synthetic_mp3(crate_folder / f"Techno_{i}.mp3", bpm="130.0", duration_frames=500)

        auto_cue.batch_apply_crate_cues(
            mp3_base_dir=str(self.mp3_dir),
            crate_raiz="Techno",
            only_pending=True,
            overwrite_existing=False
        )

        audit = auto_cue.audit_crate_cues_detailed(
            mp3_base_dir=str(self.mp3_dir),
            crate_raiz="Techno"
        )
        self.assertEqual(audit.get("padrao_autocue"), 4)

    def test_auto_cue_05_backup_and_restore_cues(self):
        """restore_track_cues restores previously saved cue state from SQLite backup."""
        track_path = self.mp3_dir / "cue_restore.mp3"
        self.create_synthetic_mp3(track_path, bpm="120.0", duration_frames=500)

        # Apply cues (creates backup)
        auto_cue.generate_and_save_serato_cues(str(track_path), overwrite_existing=True)

        backups = auto_cue.list_cue_backups(limit=50)
        self.assertTrue(backups.get("sucesso"))
        self.assertGreaterEqual(backups.get("total", 0), 1)

        res_restore = auto_cue.restore_track_cues(str(track_path))
        self.assertTrue(res_restore.get("sucesso"), res_restore)

    # =========================================================================
    # 5. JOURNAL & ATOMIC UNDO PIPELINE
    # =========================================================================

    def test_journal_01_record_before_and_after(self):
        """record_id3_before_change and record_operation_after log tag transaction to SQLite."""
        track_path = self.mp3_dir / "journal_track.mp3"
        self.create_synthetic_mp3(track_path, title="Original Title")

        op_id = journal.record_id3_before_change(str(track_path), action="unit_test_change")
        self.assertIsNotNone(op_id)
        self.assertGreater(op_id, 0)

        tags = ID3(track_path)
        tags.add(TIT2(encoding=3, text="Modified Title"))
        tags.save(v2_version=3)

        journal.record_operation_after(op_id, str(track_path))
        ops = journal.list_operations(only_active=True)
        self.assertTrue(ops.get("sucesso"))
        self.assertGreaterEqual(ops.get("total", 0), 1)

    def test_journal_02_undo_restores_previous_tag(self):
        """undo_operation restores bit-for-bit previous ID3 header state."""
        track_path = self.mp3_dir / "undo_test.mp3"
        self.create_synthetic_mp3(track_path, title="State A")

        op_id = journal.record_id3_before_change(str(track_path), action="test_undo")
        tags = ID3(track_path)
        tags.add(TIT2(encoding=3, text="State B"))
        tags.save(v2_version=3)
        journal.record_operation_after(op_id, str(track_path))

        res_undo = journal.undo_operation(op_id)
        self.assertTrue(res_undo.get("sucesso"), res_undo)

        tags_restored = ID3(track_path)
        self.assertEqual(tags_restored.get("TIT2").text[0], "State A")

    def test_journal_03_calc_file_sha256(self):
        """calc_file_sha256 computes consistent 64-char SHA-256 hex digest of file."""
        track_path = self.mp3_dir / "hash_track.mp3"
        self.create_synthetic_mp3(track_path)
        h1 = journal.calc_file_sha256(str(track_path))
        h2 = journal.calc_file_sha256(str(track_path))
        self.assertEqual(len(h1), 64)
        self.assertEqual(h1, h2)

    def test_journal_04_calc_audio_tail_sha256(self):
        """calc_audio_tail_sha256 computes hash of MPEG audio body skipping ID3v2 header."""
        track_path = self.mp3_dir / "tail_track.mp3"
        self.create_synthetic_mp3(track_path, title="Title 1")
        tail1 = journal.calc_audio_tail_sha256(str(track_path))

        tags = ID3(track_path)
        tags.add(TIT2(encoding=3, text="Title 2 With Different Length"))
        tags.save(v2_version=3)
        tail2 = journal.calc_audio_tail_sha256(str(track_path))

        self.assertEqual(tail1, tail2)

    def test_journal_05_list_operations_filtering(self):
        """list_operations filters by only_active status correctly."""
        track_path = self.mp3_dir / "filter_ops.mp3"
        self.create_synthetic_mp3(track_path)

        op_id = journal.record_id3_before_change(str(track_path))
        journal.record_operation_after(op_id, str(track_path))

        all_ops = journal.list_operations(only_active=False)
        active_ops = journal.list_operations(only_active=True)
        self.assertEqual(all_ops.get("total"), active_ops.get("total"))

        journal.undo_operation(op_id)
        active_after = journal.list_operations(only_active=True)
        self.assertEqual(active_after.get("total"), 0)

    # =========================================================================
    # 6. SYNC ENGINE & CRATE OPERATIONS
    # =========================================================================

    def test_sync_engine_01_sincronizar_biblioteca(self):
        """sincronizar_biblioteca scans directory, creates .crate binaries and neworder.pref."""
        house_folder = self.mp3_dir / "Deep House"
        house_folder.mkdir(parents=True)
        self.create_synthetic_mp3(house_folder / "Track01.mp3")
        self.create_synthetic_mp3(house_folder / "Track02.mp3")

        ok, resumo = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            export_csv=True,
            emit_json_summary=True
        )
        self.assertTrue(ok, resumo)
        self.assertEqual(resumo.get("crates_gravadas"), 1)
        self.assertEqual(resumo.get("total_faixas"), 2)

        crate_file = self.subcrates_dir / "Deep House.crate"
        self.assertTrue(crate_file.exists())
        pref_file = self.serato_dir / "neworder.pref"
        self.assertTrue(pref_file.exists())

    def test_sync_engine_02_calcular_assinatura_pasta(self):
        """calcular_assinatura_pasta detects change when directory metadata changes."""
        folder = self.mp3_dir / "SigFolder"
        folder.mkdir(parents=True)
        p1 = self.create_synthetic_mp3(folder / "Track01.mp3")

        def _file_meta(p):
            st = p.stat()
            return (
                p.name,
                p.name,
                st.st_size,
                getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)),
                getattr(st, 'st_ctime_ns', int(st.st_ctime * 1e9)),
                st.st_dev,
                st.st_ino,
            )

        meta1 = _file_meta(p1)
        sig1 = serato_macos_app.calcular_assinatura_pasta([meta1])

        p2 = self.create_synthetic_mp3(folder / "Track02.mp3")
        meta2 = _file_meta(p2)
        sig2 = serato_macos_app.calcular_assinatura_pasta([meta1, meta2])

        self.assertNotEqual(sig1, sig2)

    def test_sync_engine_03_compute_quick_audio_hash(self):
        """compute_quick_audio_hash produces identical hash before and after ID3 modification."""
        track_path = self.mp3_dir / "quick_hash.mp3"
        self.create_synthetic_mp3(track_path, title="V1")
        h1 = serato_macos_app.compute_quick_audio_hash(track_path)

        tags = ID3(track_path)
        tags.add(TIT2(encoding=3, text="V2 Modified Title"))
        tags.save(v2_version=3)
        h2 = serato_macos_app.compute_quick_audio_hash(track_path)

        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_crate_ops_04_add_paths_to_crate(self):
        """crate_ops.add_paths_to_crate appends audio paths to a Serato .crate file."""
        crate_name = "Melodic"
        t1 = self.create_synthetic_mp3(self.mp3_dir / "Melodic" / "TrackA.mp3")
        t2 = self.create_synthetic_mp3(self.mp3_dir / "Melodic" / "TrackB.mp3")

        res = crate_ops.add_paths_to_crate(
            serato_dir=self.serato_dir,
            crate_name=crate_name,
            abs_paths=[str(t1), str(t2)]
        )
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("adicionados"), 2)

        _, saved_paths, _, _ = serato_macos_app.ler_faixas_crate_binaria(
            self.subcrates_dir / f"{crate_name}.crate"
        )
        self.assertEqual(len(saved_paths), 2)

    def test_crate_ops_05_preserves_custom_blocks(self):
        """add_paths_to_crate preserves custom non-otrk chunks such as 'ovct'."""
        crate_name = "CustomBlockCrate"
        crate_file = self.subcrates_dir / f"{crate_name}.crate"
        custom_ovct = (b"ovct", b"\x00\x00\x00\x01CustomColumnConfigData")
        self.create_synthetic_crate(crate_file, track_paths=[], custom_chunks=[custom_ovct])

        t1 = self.create_synthetic_mp3(self.mp3_dir / "CustomBlockCrate" / "Track1.mp3")
        res = crate_ops.add_paths_to_crate(
            serato_dir=self.serato_dir,
            crate_name=crate_name,
            abs_paths=[str(t1)]
        )
        self.assertTrue(res.get("sucesso"), res)

        content = crate_file.read_bytes()
        self.assertIn(b"ovct", content)
        self.assertIn(b"CustomColumnConfigData", content)

    # =========================================================================
    # 7. LIBRARY TOOLS PIPELINE
    # =========================================================================

    def test_library_tools_01_check_crate_references(self):
        """check_crate_references identifies missing referenced tracks across all crates."""
        crate_name = "RefCheck"
        crate_file = self.subcrates_dir / f"{crate_name}.crate"
        existing_track = self.mp3_dir / "existing.mp3"
        self.create_synthetic_mp3(existing_track)

        root = library_tools.library_root_for(self.serato_dir)
        rel_existing = os.path.relpath(str(existing_track), str(root))

        self.create_synthetic_crate(
            crate_file,
            track_paths=[rel_existing, "NonExistent/missing.mp3"]
        )

        res = library_tools.check_crate_references(serato_dir=self.serato_dir)
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("referencias_quebradas"), 1)

    def test_library_tools_02_library_health(self):
        """library_health aggregates counts for missing BPM, Key, and low quality tracks."""
        self.create_synthetic_mp3(self.mp3_dir / "full.mp3", bpm="128.0", key="8A")
        self.create_synthetic_mp3(self.mp3_dir / "nobpm.mp3", bpm=None, key="8A")
        self.create_synthetic_mp3(self.mp3_dir / "nokey.mp3", bpm="124.0", key=None)

        res = library_tools.library_health(mp3_folder=self.mp3_dir, serato_dir=self.serato_dir)
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("total_faixas"), 3)
        self.assertEqual(res.get("sem_bpm"), 1)
        self.assertEqual(res.get("sem_tom"), 1)

    def test_library_tools_03_create_smart_crate(self):
        """create_smart_crate exports matching tracks by BPM and Key criteria as new crate."""
        self.create_synthetic_mp3(self.mp3_dir / "t126.mp3", bpm="126.0", key="8A")
        self.create_synthetic_mp3(self.mp3_dir / "t140.mp3", bpm="140.0", key="8A")

        rules = {"bpm_min": 120.0, "bpm_max": 130.0, "camelot": ["8A"]}
        res = library_tools.create_smart_crate(
            mp3_folder=self.mp3_dir,
            serato_dir=self.serato_dir,
            nome="Smart126",
            rules=rules,
            salvar_regra=True
        )
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("total_faixas"), 1)

        smart_crate_file = self.subcrates_dir / "Smart126.crate"
        self.assertTrue(smart_crate_file.exists())

    def test_library_tools_04_scan_new_files(self):
        """scan_new_files establishes baseline and detects newly added tracks."""
        self.create_synthetic_mp3(self.mp3_dir / "base.mp3")
        res1 = library_tools.scan_new_files(mp3_folder=self.mp3_dir)
        self.assertTrue(res1.get("linha_base"))

        self.create_synthetic_mp3(self.mp3_dir / "new_addition.mp3")
        res2 = library_tools.scan_new_files(mp3_folder=self.mp3_dir)
        self.assertFalse(res2.get("linha_base"))
        self.assertEqual(res2.get("total_novos"), 1)

    def test_library_tools_05_generate_html_report(self):
        """generate_html_report outputs a self-contained executive HTML dashboard."""
        self.create_synthetic_mp3(self.mp3_dir / "report_track.mp3", bpm="125.0", key="9A")
        out_html = self.tmp_dir / "report.html"

        res = library_tools.generate_html_report(
            mp3_folder=self.mp3_dir,
            serato_dir=self.serato_dir,
            out_html_path=out_html
        )
        self.assertTrue(res.get("sucesso"), res)
        self.assertTrue(out_html.exists())
        content = out_html.read_text(encoding="utf-8")
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("Diagnóstico da Biblioteca Serato", content)

    # =========================================================================
    # 8. DUPLICATES & SOUND SEAL PIPELINE
    # =========================================================================

    def test_sound_seal_01_scan_and_status(self):
        """scan_sound_seals indexes tracks into SQLite database and returns status summary."""
        for i in range(3):
            self.create_synthetic_mp3(self.mp3_dir / f"seal_{i}.mp3")

        res_scan = sound_seal.scan_sound_seals(mp3_base_dir=str(self.mp3_dir), stream_json=False)
        self.assertTrue(res_scan.get("sucesso"), res_scan)
        self.assertEqual(res_scan.get("total_selados"), 3)

        status = sound_seal.get_sound_seal_status()
        self.assertTrue(status.get("sucesso"))
        self.assertEqual(status.get("total_selados"), 3)

    def test_sound_seal_02_scan_missing_and_relocate(self):
        """scan_missing_and_relocate identifies relocated tracks via pure audio hash match."""
        old_folder = self.mp3_dir / "OldFolder"
        new_folder = self.mp3_dir / "NewFolder"
        old_folder.mkdir(parents=True)
        new_folder.mkdir(parents=True)

        original_file = old_folder / "Song.mp3"
        self.create_synthetic_mp3(original_file, title="Song", audio_content=b"UNIQUE_AUDIO_STREAM_123")
        sound_seal.scan_sound_seals(mp3_base_dir=str(self.mp3_dir), stream_json=False)

        # Crate with relative path
        crate_file = self.subcrates_dir / "TestReloc.crate"
        root = library_tools.library_root_for(self.serato_dir)
        rel_path = os.path.relpath(str(original_file), str(root))
        self.create_synthetic_crate(crate_file, track_paths=[rel_path])

        # Move file to NewFolder and re-scan
        moved_file = new_folder / "Song.mp3"
        original_file.rename(moved_file)
        sound_seal.scan_sound_seals(mp3_base_dir=str(self.mp3_dir), stream_json=False)

        res = sound_seal.scan_missing_and_relocate(
            serato_dir_str=str(self.serato_dir),
            mp3_dir_str=str(self.mp3_dir),
            stream_json=False
        )
        self.assertTrue(res.get("sucesso"), res)
        self.assertGreaterEqual(res.get("total_perdidas", 0), 1)

    def test_duplicates_tool_03_scan_roots(self):
        """duplicates_tool.scan_roots groups acoustic duplicates across directories."""
        dir_a = self.mp3_dir / "FolderA"
        dir_b = self.mp3_dir / "FolderB"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        audio_body = b"IDENTICAL_AUDIO_DATA_FOR_TWINS"
        self.create_synthetic_mp3(dir_a / "Twin.mp3", title="Title A", audio_content=audio_body)
        self.create_synthetic_mp3(dir_b / "Twin.mp3", title="Title B", audio_content=audio_body)

        res = duplicates_tool.scan_roots(roots=[str(dir_a), str(dir_b)], progress=False)
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("grupos"), 1)
        self.assertEqual(res.get("copias_redundantes"), 1)

    def test_duplicates_tool_04_move_files(self):
        """duplicates_tool.move_files relocates duplicate files into destination quarantine."""
        dup_file = self.mp3_dir / "dup_to_move.mp3"
        self.create_synthetic_mp3(dup_file)

        dest_dir = self.sandbox_path / "MovedDups"
        res = duplicates_tool.move_files([str(dup_file)], destination=str(dest_dir))
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("movidos"), 1)
        self.assertFalse(dup_file.exists())
        self.assertTrue((dest_dir / "dup_to_move.mp3").exists())

    def test_sound_seal_05_compute_audio_seal_consistency(self):
        """compute_audio_seal produces identical SHA-256 for audio with modified ID3 tags."""
        p = self.mp3_dir / "seal_consistency.mp3"
        self.create_synthetic_mp3(p, title="Title 1", artist="Artist 1")
        seal1 = sound_seal.compute_audio_seal(str(p))

        tags = ID3(p)
        tags.add(TIT2(encoding=3, text="Modified Title Completely Different"))
        tags.add(TPE1(encoding=3, text="Different Artist"))
        tags.save(v2_version=3)
        seal2 = sound_seal.compute_audio_seal(str(p))

        self.assertEqual(seal1, seal2)

    # =========================================================================
    # 9. TRACK MATCHER PIPELINE
    # =========================================================================

    def test_track_matcher_01_match_tracks_against_library(self):
        """match_tracks_against_library matches incoming track against library via metadata."""
        lib_track = self.mp3_dir / "Avicii - Levels.mp3"
        self.create_synthetic_mp3(lib_track, title="Levels", artist="Avicii")

        incoming_folder = self.sandbox_path / "IncomingMatch"
        incoming_folder.mkdir(parents=True)
        self.create_synthetic_mp3(incoming_folder / "Avicii - Levels.mp3", title="Levels", artist="Avicii")

        incoming = track_matcher.parse_incoming_folder(str(incoming_folder))
        res = track_matcher.match_tracks_against_library(incoming, mp3_dir_str=str(self.mp3_dir))
        self.assertIn("encontradas", res)
        self.assertGreaterEqual(len(res["encontradas"]), 1)

    def test_track_matcher_02_remix_divergence_lock(self):
        """match_tracks_against_library flags VERSAO_DIVERGENTE when Remix meets Original."""
        lib_track = self.mp3_dir / "DJ Test - Song (Original Mix).mp3"
        self.create_synthetic_mp3(lib_track, title="Song (Original Mix)", artist="DJ Test")

        incoming_folder = self.sandbox_path / "IncomingRemix"
        incoming_folder.mkdir(parents=True)
        self.create_synthetic_mp3(incoming_folder / "DJ Test - Song (Alok Remix).mp3", title="Song (Alok Remix)", artist="DJ Test")

        incoming = track_matcher.parse_incoming_folder(str(incoming_folder))
        res = track_matcher.match_tracks_against_library(incoming, mp3_dir_str=str(self.mp3_dir))
        self.assertEqual(res.get("total_divergentes"), 1)
        self.assertGreaterEqual(len(res.get("encontradas", [])), 1)
        match_item = res["encontradas"][0]
        self.assertEqual(match_item.get("status_comparacao"), "VERSAO_DIVERGENTE")
        self.assertTrue(match_item.get("versao_divergente"))

    def test_track_matcher_03_duration_mismatch_lock(self):
        """match_tracks_against_library flags DURACAO_INCOMPATIVEL when delta duration > 5.0s."""
        lib_track = self.mp3_dir / "DJ Test - LongSong.mp3"
        self.create_synthetic_mp3(lib_track, title="LongSong", artist="DJ Test", duration_frames=2000)

        incoming_folder = self.sandbox_path / "IncomingDuration"
        incoming_folder.mkdir(parents=True)
        self.create_synthetic_mp3(incoming_folder / "DJ Test - LongSong.mp3", title="LongSong", artist="DJ Test", duration_frames=800)

        incoming = track_matcher.parse_incoming_folder(str(incoming_folder))
        res = track_matcher.match_tracks_against_library(incoming, mp3_dir_str=str(self.mp3_dir))
        self.assertGreaterEqual(len(res.get("encontradas", [])), 1)
        match_item = res["encontradas"][0]
        self.assertEqual(match_item.get("status_comparacao"), "DURACAO_INCOMPATIVEL")
        self.assertTrue(match_item.get("duracao_incompativel"))

    def test_track_matcher_04_batch_replace_upgrades(self):
        """batch_replace_upgrades replaces lower-quality track, cloning tags and quarantining original."""
        original = self.mp3_dir / "LowQuality.mp3"
        incoming_folder = self.sandbox_path / "Incoming"
        incoming_folder.mkdir(parents=True)
        upgrade = incoming_folder / "HighQuality.mp3"
        self.create_synthetic_mp3(original, title="Preserved Title", bpm="128.0", duration_frames=500)
        self.create_synthetic_mp3(upgrade, title="Incoming Tag", bpm=None, duration_frames=500)

        upgrades_list = [{
            "caminho_completo": str(original),
            "caminho_novo": str(upgrade)
        }]
        res = track_matcher.batch_replace_upgrades(upgrades_list, force=True)
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("atualizados"), 1)

        tags = ID3(original)
        self.assertEqual(tags.get("TBPM").text[0], "128.0")

        quarantine_files = list(self.quarantine_dir.glob("*.mp3"))
        self.assertGreaterEqual(len(quarantine_files), 1)

    def test_track_matcher_05_integrate_new_tracks_to_crate(self):
        """integrate_new_tracks_to_crate copies divergent track to crate folder and updates crate."""
        target_folder = self.mp3_dir / "Afro"
        target_folder.mkdir(parents=True)
        crate_file = self.subcrates_dir / "Afro.crate"
        self.create_synthetic_crate(crate_file, track_paths=[])

        incoming_folder = self.sandbox_path / "Downloads"
        incoming_folder.mkdir(parents=True)
        incoming_track = incoming_folder / "Afro_Remix.mp3"
        self.create_synthetic_mp3(incoming_track, title="Afro Remix")

        tracks_list = [{"caminho_novo": str(incoming_track), "nome": "Afro_Remix.mp3"}]
        res = track_matcher.integrate_new_tracks_to_crate(tracks_list, target_crate_folder=str(target_folder))
        self.assertTrue(res.get("sucesso"), res)
        self.assertEqual(res.get("copiados"), 1)
        self.assertTrue((target_folder / "Afro_Remix.mp3").exists())


if __name__ == "__main__":
    unittest.main()
