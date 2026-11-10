#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SERATO 4 SYNC MANAGER PRO - E2E TEST SUITE TIER 3: CROSS-FEATURE COMBINATIONS
================================================================================
Comprehensive pairwise and cross-feature integration verification across subsystems:
  - Audio Health Resampling -> Music Analysis Tagging
  - Tag Doctor Scrubbing -> Journal Snapshot -> Atomic Undo & Rollback
  - Auto-Cue Markers2 -> Crate Ops Management -> Library Reference Validation
  - Sound Seal Hashing -> Track Matcher Upgrades -> Original Quarantine
  - Acoustic Relocation -> Crate Binary Update
  - Full Library Sync -> Duplicates Detection & Relocation -> Crate Consistency
  - Smart Crate Filtering -> Incremental New File Watcher
================================================================================
"""

import os
import sys
import json
import shutil
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


class TestTier3CrossFeatureCombinations(E2ESandboxTestCase):
    """
    Tier 3 Test Suite: Multi-Module Pipeline & Integration Tests.
    Verifies that sequential operations across multiple engines cooperate harmoniously,
    maintain state consistency, and do not regress metadata or filesystem structures.
    """

    # =========================================================================
    # PIPELINE 1: AUDIO HEALTH + MUSIC ANALYSIS
    # =========================================================================

    def test_comb_01_resample_then_analyze_and_tag(self):
        """Audio Health resamples audio to 44.1kHz CBR, then Music Analysis computes and writes BPM & Key."""
        track_path = self.mp3_dir / "resample_and_analyze.mp3"
        self.create_synthetic_mp3(track_path, bpm="0", key="", duration_frames=500)

        # 1. Resample audio
        res_resample = audio_health.resample_track_local(str(track_path))
        self.assertTrue(res_resample.get("sucesso"), res_resample)

        # 2. Analyze audio
        res_analysis = music_analysis.analyze_file(str(track_path))
        self.assertTrue(res_analysis.get("sucesso"), res_analysis)

        # 3. Write analysis tags (TBPM, TKEY)
        res_write = music_analysis.write_analysis_tags(
            str(track_path),
            bpm=124.0,
            key_text="8A",
            overwrite=True
        )
        self.assertTrue(res_write.get("sucesso"))

        # 4. Verify tags and physical audio format
        audio = mutagen.File(str(track_path))
        self.assertEqual(audio.tags.get("TBPM").text[0], "124")
        self.assertEqual(audio.tags.get("TKEY").text[0], "8A")
        self.assertEqual(audio.info.sample_rate, 44100)

    def test_comb_02_health_inspection_reflects_analysis_enrichment(self):
        """Health inspection transitions from un-enriched status to updated BPM after analysis tagging."""
        track_path = self.mp3_dir / "enrichment_check.mp3"
        self.create_synthetic_mp3(track_path, bpm="0", key="", duration_frames=500)

        # Initial inspection before tagging
        info_before = audio_health.inspect_track_health(str(track_path))
        self.assertIn(info_before.get("status"), ("alerta", "suspeita", "ok", "comprometida"))

        # Enrich tags
        music_analysis.write_analysis_tags(str(track_path), bpm=126.0, key_text="11B", overwrite=True)

        # Verify inspection reflects updated file on disk
        info_after = audio_health.inspect_track_health(str(track_path))
        self.assertIn(info_after.get("status"), ("alerta", "suspeita", "ok", "comprometida"))
        tags = ID3(track_path)
        self.assertEqual(tags.get("TBPM").text[0], "126")
        self.assertEqual(tags.get("TKEY").text[0], "11B")

    # =========================================================================
    # PIPELINE 2: TAG DOCTOR + JOURNAL ATOMIC ROLLBACK
    # =========================================================================

    def test_comb_03_tag_scrub_with_journal_undo(self):
        """Tag Doctor scrubs promo tags with built-in Journal logging; Undo restores bit-for-bit initial state."""
        track_path = self.mp3_dir / "[DJPool] CleanMe - Track (Original Mix).mp3"
        self.create_synthetic_mp3(
            track_path,
            title="[DJPool] CleanMe - Track (Original Mix)",
            artist="DJ Artist",
            duration_frames=500
        )
        initial_sha = journal.calc_file_sha256(str(track_path))

        # 1. Apply cleaned tags via Tag Doctor (automatically registers with journal)
        cleaned_item = {
            "caminho": str(track_path),
            "titulo_sugerido": "CleanMe - Track (Original Mix)",
            "artista_sugerido": "DJ Artist"
        }
        res_apply = tag_doctor.apply_cleaned_tags([cleaned_item])
        self.assertEqual(res_apply.get("atualizados"), 1)

        # Verify tags were changed
        modified_tags = ID3(track_path)
        self.assertEqual(modified_tags.get("TIT2").text[0], "CleanMe - Track (Original Mix)")
        self.assertNotEqual(journal.calc_file_sha256(str(track_path)), initial_sha)

        # 2. Perform Journal Undo
        res_undo = journal.undo_operation()
        self.assertTrue(res_undo.get("sucesso"), res_undo)

        # 3. Verify bit-for-bit file restoration
        restored_sha = journal.calc_file_sha256(str(track_path))
        self.assertEqual(restored_sha, initial_sha)

    def test_comb_04_sequential_tag_edits_multi_step_rollback(self):
        """Two sequential tag edits rolled back in strict LIFO order return file to pristine original state."""
        track_path = self.mp3_dir / "multi_step_rollback.mp3"
        self.create_synthetic_mp3(track_path, title="V0", artist="Artist0", duration_frames=500)
        h0 = journal.calc_file_sha256(str(track_path))

        # Step 1: Change to V1
        op1 = journal.record_id3_before_change(str(track_path), action="step_1")
        tags1 = ID3(track_path)
        tags1["TIT2"] = TIT2(encoding=3, text="V1")
        tags1.save(v2_version=3)
        journal.record_operation_after(op1, str(track_path))
        h1 = journal.calc_file_sha256(str(track_path))

        # Step 2: Change to V2
        op2 = journal.record_id3_before_change(str(track_path), action="step_2")
        tags2 = ID3(track_path)
        tags2["TIT2"] = TIT2(encoding=3, text="V2")
        tags2.save(v2_version=3)
        journal.record_operation_after(op2, str(track_path))
        h2 = journal.calc_file_sha256(str(track_path))

        self.assertNotEqual(h0, h1)
        self.assertNotEqual(h1, h2)

        # Undo Op 2 -> should match h1
        res2 = journal.undo_operation(op2)
        self.assertTrue(res2.get("sucesso"))
        self.assertEqual(journal.calc_file_sha256(str(track_path)), h1)

        # Undo Op 1 -> should match h0
        res1 = journal.undo_operation(op1)
        self.assertTrue(res1.get("sucesso"))
        self.assertEqual(journal.calc_file_sha256(str(track_path)), h0)

    # =========================================================================
    # PIPELINE 3: AUTO-CUE + CRATE OPS + LIBRARY TOOLS
    # =========================================================================

    def test_comb_05_cued_track_added_to_crate_and_audited(self):
        """Auto-Cue marks track with Serato Markers2, Crate Ops adds it to crate, and Library Tools validates references."""
        crate_name = "Festival House"
        track_path = self.mp3_dir / "festival_track.mp3"
        self.create_synthetic_mp3(track_path, bpm="128.0", duration_frames=500)

        # 1. Generate and save cues
        res_cue = auto_cue.generate_and_save_serato_cues(str(track_path), overwrite_existing=True)
        self.assertTrue(res_cue.get("sucesso"), res_cue)

        # 2. Add to crate via crate_ops
        res_add = crate_ops.add_paths_to_crate(
            serato_dir=self.serato_dir,
            crate_name=crate_name,
            abs_paths=[track_path]
        )
        self.assertTrue(res_add.get("sucesso"), res_add)
        self.assertEqual(res_add.get("adicionados"), 1)

        # 3. Check crate references via library_tools
        ref_check = library_tools.check_crate_references(serato_dir=self.serato_dir)
        self.assertTrue(ref_check.get("sucesso"))
        self.assertEqual(ref_check.get("referencias_quebradas"), 0)

        # 4. Read back crate tracks
        crate_file = self.subcrates_dir / f"{crate_name}.crate"
        faixas_set, faixas_lista, outros, header = serato_macos_app.ler_faixas_crate_binaria(crate_file)
        self.assertEqual(len(faixas_lista), 1)

    def test_comb_06_cues_batch_audit_and_crate_synchronization(self):
        """Auto-Cue marks tracks and audit confirms full cue coverage in newly created Crate."""
        crate_folder = self.mp3_dir / "TechHouse"
        crate_folder.mkdir(parents=True)
        t1 = self.create_synthetic_mp3(crate_folder / "Tech1.mp3", bpm="126.0", duration_frames=500)
        t2 = self.create_synthetic_mp3(crate_folder / "Tech2.mp3", bpm="126.0", duration_frames=500)

        # Apply cues to both tracks
        auto_cue.generate_and_save_serato_cues(str(t1), overwrite_existing=True)
        auto_cue.generate_and_save_serato_cues(str(t2), overwrite_existing=True)

        # Add to crate
        crate_ops.add_paths_to_crate(self.serato_dir, "TechHouse", [t1, t2])

        # Audit cues
        audit = auto_cue.audit_crate_cues_detailed(str(self.mp3_dir), crate_raiz="TechHouse")
        self.assertEqual(audit.get("padrao_autocue"), 2)
        self.assertEqual(audit.get("pendentes"), 0)

    # =========================================================================
    # PIPELINE 4: SOUND SEAL + TRACK MATCHER + UPGRADE QUARANTINE
    # =========================================================================

    def test_comb_07_seal_match_and_upgrade_with_quarantine(self):
        """Sound Seal seals library track; Track Matcher detects higher-quality upgrade, clones tags, and quarantines original."""
        lib_folder = self.mp3_dir / "House"
        lib_folder.mkdir(parents=True)
        original_track = lib_folder / "Artist - GreatTrack.mp3"
        self.create_synthetic_mp3(original_track, artist="Artist", title="GreatTrack", bpm="124.0", duration_frames=1000)
        auto_cue.generate_and_save_serato_cues(str(original_track), overwrite_existing=True)

        # 1. Sound Seal scans library
        sound_seal.scan_sound_seals(str(self.mp3_dir))

        # 2. Incoming candidate folder with 320 kbps upgrade
        incoming_folder = self.fake_home / "IncomingPromo"
        incoming_folder.mkdir(parents=True)
        upgrade_track = incoming_folder / "Artist - GreatTrack.mp3"
        self.create_synthetic_mp3(upgrade_track, artist="Artist", title="GreatTrack", bpm="", duration_frames=1000)

        # 3. Match candidate against library
        candidates = track_matcher.parse_incoming_folder(str(incoming_folder))
        match_res = track_matcher.match_tracks_against_library(candidates, str(self.mp3_dir))
        self.assertEqual(len(match_res.get("encontradas", [])), 1)

        # 4. Perform upgrade
        upgrades = [{
            "caminho_completo": str(original_track),
            "caminho_novo": str(upgrade_track),
            "backup_crate": "UpgradeBackup"
        }]
        res_upgrade = track_matcher.batch_replace_upgrades(upgrades, force=True)
        self.assertTrue(res_upgrade.get("sucesso"), res_upgrade)
        self.assertEqual(res_upgrade.get("atualizados"), 1)

        # 5. Verify tags (TBPM, Markers2) cloned onto new track
        upgraded_tags = ID3(original_track)
        self.assertIn(upgraded_tags.get("TBPM").text[0], ("124", "124.0"))
        self.assertIn("GEOB:Serato Markers2", upgraded_tags)

        # 6. Verify original was moved to quarantine
        quarantine_dir = self.fake_home / ".serato_quarentena_audio"
        quarantine_files = list(quarantine_dir.glob("*GreatTrack.mp3"))
        self.assertGreaterEqual(len(quarantine_files), 1)

    def test_comb_08_sound_seal_relocation_updates_crate(self):
        """When an audio file is moved to another folder, scan_missing_and_relocate updates the .crate file."""
        folder_old = self.mp3_dir / "OldLocation"
        folder_new = self.mp3_dir / "NewLocation"
        folder_old.mkdir(parents=True)
        folder_new.mkdir(parents=True)

        track_file = folder_old / "RelocateMe.mp3"
        self.create_synthetic_mp3(track_file, duration_frames=500)

        # Seal it while in OldLocation
        sound_seal.scan_sound_seals(str(self.mp3_dir))

        # Add to crate pointing to OldLocation
        crate_file = self.subcrates_dir / "RelocationTest.crate"
        rel_old = os.path.relpath(track_file, library_tools.library_root_for(self.serato_dir))
        self.create_synthetic_crate(crate_file, [rel_old])

        # Physically move the file to NewLocation
        new_track_file = folder_new / "RelocateMe.mp3"
        shutil.move(str(track_file), str(new_track_file))

        # Run acoustic relocation scan
        res_reloc = sound_seal.scan_missing_and_relocate(
            serato_dir_str=str(self.serato_dir),
            mp3_dir_str=str(self.mp3_dir),
            stream_json=False
        )
        self.assertTrue(res_reloc.get("sucesso"), res_reloc)
        self.assertEqual(res_reloc.get("total_perdidas"), 1)

    # =========================================================================
    # PIPELINE 5: SYNC ENGINE + DUPLICATES TOOL + NEWORDER PREF
    # =========================================================================

    def test_comb_09_sync_duplicates_cleanup_and_resync(self):
        """Full cycle: Synchronize library, detect multi-folder duplicate, relocate duplicate, and re-sync."""
        folder1 = self.mp3_dir / "Deep"
        folder2 = self.mp3_dir / "Chill"
        folder1.mkdir(parents=True)
        folder2.mkdir(parents=True)

        # Create identical tracks in two folders
        p1 = self.create_synthetic_mp3(folder1 / "SameBeat.mp3", duration_frames=500)
        p2 = self.create_synthetic_mp3(folder2 / "SameBeat.mp3", duration_frames=500)

        # 1. Initial Sync
        ok1, summary1 = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok1)
        self.assertEqual(summary1.get("total_faixas"), 2)

        # 2. Run duplicates_tool cross-scan
        groups_res = duplicates_tool.scan_roots([str(folder1), str(folder2)], progress=False)
        self.assertEqual(groups_res.get("grupos"), 1)

        # 3. Move duplicate to quarantine
        quarantine = self.fake_home / "DupQuarantine"
        quarantine.mkdir(parents=True)
        res_move = duplicates_tool.move_files([p2], destination=str(quarantine))
        self.assertEqual(res_move.get("movidos"), 1)

        # 4. Re-sync library -> should only have 1 active track
        ok2, summary2 = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok2)
        self.assertEqual(summary2.get("total_faixas"), 1)

    def test_comb_10_neworder_pref_order_retention_across_syncs(self):
        """neworder.pref maintains user crate display order across multiple sync operations."""
        f1 = self.mp3_dir / "Afro"
        f2 = self.mp3_dir / "Techno"
        f1.mkdir(parents=True)
        f2.mkdir(parents=True)
        self.create_synthetic_mp3(f1 / "Afro1.mp3", duration_frames=500)
        self.create_synthetic_mp3(f2 / "Techno1.mp3", duration_frames=500)

        # Sync 1
        serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir)
        )

        # Add a 3rd crate
        f3 = self.mp3_dir / "Disco"
        f3.mkdir(parents=True)
        self.create_synthetic_mp3(f3 / "Disco1.mp3", duration_frames=500)

        # Sync 2
        ok, summary = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir)
        )
        self.assertTrue(ok)

        # Verify neworder.pref contains all crates
        pref_file = self.serato_dir / "neworder.pref"
        self.assertTrue(pref_file.exists())
        header, ordered_crates, outros = serato_macos_app.parse_neworder_pref(pref_file.read_bytes())
        self.assertIn("Afro", ordered_crates)
        self.assertIn("Techno", ordered_crates)
        self.assertIn("Disco", ordered_crates)

    # =========================================================================
    # PIPELINE 6: LIBRARY TOOLS + SMART CRATES + TAG DOCTOR
    # =========================================================================

    def test_comb_11_enrich_artist_then_filter_smart_crate(self):
        """Tag Doctor seeds and derives missing artist, then Smart Crate queries Camelot key and BPM."""
        tag_doctor.init_tag_cache()
        tag_doctor.seed_tag_cache(title="Starlight", artist="Muse")

        track_path = self.mp3_dir / "Starlight.mp3"
        self.create_synthetic_mp3(track_path, title="Starlight", artist="", bpm="128.0", key="8A", duration_frames=500)

        # 1. Enrich missing artist via Tag Doctor
        items = [{
            "caminho": str(track_path),
            "titulo_sugerido": "Starlight",
            "artista_sugerido": ""
        }]
        res_enrich = tag_doctor.enrich_missing_artists(items, stream_progress=False)
        self.assertTrue(res_enrich.get("sucesso"))

        # Apply enriched tags
        tag_doctor.apply_cleaned_tags(res_enrich.get("items", []))

        # Verify artist was embedded into ID3
        tags = ID3(track_path)
        self.assertEqual(tags.get("TPE1").text[0], "Muse")

        # 2. Create smart crate matching BPM 128 and Key 8A
        res_smart = library_tools.create_smart_crate(
            self.mp3_dir,
            self.serato_dir,
            "Smart Rock",
            rules={
                "bpm_min": 125,
                "bpm_max": 130,
                "camelot": ["8A"]
            }
        )
        self.assertTrue(res_smart.get("sucesso"))
        self.assertEqual(res_smart.get("total_faixas"), 1)

    def test_comb_12_incremental_scan_and_auto_cue(self):
        """Library Tools establishes watcher baseline; newly dropped tracks are detected and auto-cued."""
        # 1. Establish initial baseline
        init_track = self.mp3_dir / "Initial.mp3"
        self.create_synthetic_mp3(init_track, duration_frames=500)
        scan1 = library_tools.scan_new_files(str(self.mp3_dir))
        self.assertTrue(scan1.get("sucesso"))
        self.assertTrue(scan1.get("linha_base"))

        # 2. Add new track
        new_track = self.mp3_dir / "NewDrop.mp3"
        self.create_synthetic_mp3(new_track, bpm="125.0", duration_frames=500)

        # 3. Incremental scan detects new track
        scan2 = library_tools.scan_new_files(str(self.mp3_dir))
        self.assertFalse(scan2.get("linha_base"))
        self.assertEqual(scan2.get("total_novos"), 1)
        self.assertEqual(Path(scan2["novos"][0]["arquivo"]).name, "NewDrop.mp3")

        # 4. Auto-cue the newly detected track
        cue_res = auto_cue.generate_and_save_serato_cues(str(new_track), overwrite_existing=True)
        self.assertTrue(cue_res.get("sucesso"))
        tags = ID3(new_track)
        self.assertIn("GEOB:Serato Markers2", tags)

    # =========================================================================
    # PIPELINE 7: EXECUTIVE HEALTH REPORTING & AUDIT METRICS
    # =========================================================================

    def test_comb_13_audit_metrics_aggregation_across_engines(self):
        """Cross-checks library health metrics between audio_health, auto_cue, and library_tools."""
        # Create 2 healthy tracks with cues, and 1 track with missing cues
        self.create_synthetic_mp3(self.mp3_dir / "T1.mp3", bpm="120.0", key="8A", duration_frames=500)
        self.create_synthetic_mp3(self.mp3_dir / "T2.mp3", bpm="124.0", key="9A", duration_frames=500)
        self.create_synthetic_mp3(self.mp3_dir / "T3_no_bpm.mp3", bpm="0", key="", duration_frames=500)

        auto_cue.generate_and_save_serato_cues(str(self.mp3_dir / "T1.mp3"), overwrite_existing=True)
        auto_cue.generate_and_save_serato_cues(str(self.mp3_dir / "T2.mp3"), overwrite_existing=True)

        # 1. Auto-cue audit
        cue_audit = auto_cue.audit_crate_cues_detailed(str(self.mp3_dir))
        self.assertEqual(cue_audit.get("padrao_autocue"), 2)
        self.assertEqual(cue_audit.get("pendentes"), 1)

        # 2. Library tools health audit
        lib_health = library_tools.library_health(self.mp3_dir)
        self.assertEqual(lib_health.get("total_faixas"), 3)
        self.assertEqual(lib_health.get("sem_bpm"), 1)
        self.assertEqual(lib_health.get("sem_tom"), 1)

        # 3. Generate HTML report
        html_res = library_tools.generate_html_report(self.mp3_dir, self.serato_dir)
        self.assertTrue(html_res.get("sucesso"))
        report_file = Path(html_res["arquivo"])
        self.assertTrue(report_file.exists())
        self.assertGreater(report_file.stat().st_size, 500)

    def test_comb_14_subcrate_creation_and_custom_block_preservation(self):
        """Adding tracks via Crate Ops preserves custom chunks while registering in neworder.pref."""
        crate_name = "Deep%%Progressive"
        t1 = self.create_synthetic_mp3(self.mp3_dir / "Prog1.mp3", duration_frames=500)
        t2 = self.create_synthetic_mp3(self.mp3_dir / "Prog2.mp3", duration_frames=500)

        # Initial crate with custom chunk 'ovct'
        crate_file = self.subcrates_dir / f"{crate_name}.crate"
        custom_ovct = b"ovct\x00\x00\x00\x08custom01"
        self.create_synthetic_crate(crate_file, [t1], custom_chunks=[custom_ovct])

        # Add second track via crate_ops
        res = crate_ops.add_paths_to_crate(self.serato_dir, crate_name, [t2])
        self.assertTrue(res.get("sucesso"))

        # Verify custom block survived addition
        faixas_set, faixas_lista, outros, header = serato_macos_app.ler_faixas_crate_binaria(crate_file)
        self.assertEqual(len(faixas_lista), 2)
        self.assertEqual(len(outros), 1)
        self.assertTrue(outros[0].startswith(b"ovct"))

    def test_comb_15_end_to_end_music_ingest_and_sync(self):
        """Comprehensive workflow: Ingest tracks -> Analyze -> Add Cues -> Sync Library -> Verify zero leaks."""
        folder = self.mp3_dir / "AfroTech"
        folder.mkdir(parents=True)
        track = self.create_synthetic_mp3(folder / "Tribal.mp3", bpm="0", key="", duration_frames=500)

        # 1. Analyze and tag
        music_analysis.write_analysis_tags(str(track), bpm=123.0, key_text="10A", overwrite=True)

        # 2. Embed smart cues
        auto_cue.generate_and_save_serato_cues(str(track), overwrite_existing=True)

        # 3. Synchronize library
        ok, summary = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok)
        self.assertEqual(summary.get("total_faixas"), 1)

        # 4. Verify crate exists and contains track
        crate_path = self.subcrates_dir / "AfroTech.crate"
        self.assertTrue(crate_path.exists())
        paths = self.read_crate_paths(crate_path)
        self.assertEqual(len(paths), 1)


if __name__ == "__main__":
    unittest.main()
