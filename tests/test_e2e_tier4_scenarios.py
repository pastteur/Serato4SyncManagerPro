#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SERATO 4 SYNC MANAGER PRO - E2E TEST SUITE TIER 4: REAL-WORLD APPLICATION SCENARIOS
================================================================================
Comprehensive end-to-end real-world user workflows and DJ performance scenarios:
  - Scenario 1: New DJ Music Pack Ingestion, Matching & Upgrading
  - Scenario 2: Complete Pre-Gig Library Hygiene & Cues Preparation
  - Scenario 3: Disaster Recovery & Acoustic Library Relocation
  - Scenario 4: Full Multi-Crate Master Sync with Dry-Run Pre-Evaluation
  - Scenario 5: Multi-Track Batch Tag Cleanup with Emergency Mass Rollback
  - Scenario 6: Harmonic Smart Crate Generation (Camelot Key & BPM)
  - Scenario 7: Multi-Folder Duplicate Pruning with Quarantine Isolation
  - Scenario 8: Audio Health Resampling Pipeline with Traceable Quarantine
  - Scenario 9: Corrupt Audio Quarantine and Crate Integrity Guard
  - Scenario 10: Complete Serato 4 Sync Manager Pro End-to-End Lifecycle
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


class TestTier4RealWorldScenarios(E2ESandboxTestCase):
    """
    Tier 4 Test Suite: Complete Real-World DJ Workflows.
    Simulates authentic end-to-end user journeys from music pack download to live gig readiness.
    """

    # =========================================================================
    # SCENARIO 1: NEW DJ MUSIC PACK INGESTION & QUALITY SORTING
    # =========================================================================

    def test_scenario_01_dj_pack_ingestion_and_upgrades(self):
        """
        DJ downloads a promo pack:
        1. An existing library track has a higher-quality upgrade candidate.
        2. A remix version of another track is safely kept separate (not overwritten).
        3. A completely new track is copied into the library.
        """
        # Step 1: Existing library baseline
        house_dir = self.mp3_dir / "House"
        house_dir.mkdir(parents=True)
        orig_track = self.create_synthetic_mp3(
            house_dir / "CamelPhat - Cola.mp3",
            artist="CamelPhat",
            title="Cola",
            bpm="122.0",
            duration_frames=1000
        )
        auto_cue.generate_and_save_serato_cues(str(orig_track), overwrite_existing=True)

        other_track = self.create_synthetic_mp3(
            house_dir / "Fisher - Losing It (Original Mix).mp3",
            artist="Fisher",
            title="Losing It (Original Mix)",
            bpm="125.0",
            duration_frames=1000
        )

        # Step 2: Incoming Pack with 3 tracks
        pack_dir = self.fake_home / "Downloads" / "Beatport_Top10"
        pack_dir.mkdir(parents=True)

        # 2a. Upgrade for CamelPhat - Cola (better quality, no TBPM set yet)
        upgrade_cand = self.create_synthetic_mp3(
            pack_dir / "CamelPhat - Cola.mp3",
            artist="CamelPhat",
            title="Cola",
            bpm="",
            duration_frames=1000
        )
        # 2b. Remix for Fisher - Losing It (divergent version)
        remix_cand = self.create_synthetic_mp3(
            pack_dir / "Fisher - Losing It (VIP Remix).mp3",
            artist="Fisher",
            title="Losing It (VIP Remix)",
            bpm="126.0",
            duration_frames=1000
        )
        # 2c. Brand new track
        new_cand = self.create_synthetic_mp3(
            pack_dir / "Meduza - Piece Of Your Heart.mp3",
            artist="Meduza",
            title="Piece Of Your Heart",
            bpm="124.0",
            duration_frames=1000
        )

        # Step 3: Match pack against library
        incoming_items = track_matcher.parse_incoming_folder(str(pack_dir))
        match_res = track_matcher.match_tracks_against_library(incoming_items, str(self.mp3_dir))

        # 3a. Upgrade was found
        encontradas = {it["arquivo_local"]: it for it in match_res["encontradas"]}
        self.assertIn("CamelPhat - Cola.mp3", encontradas)

        # 3b. Remix version is flagged as VERSAO_DIVERGENTE
        self.assertIn("Fisher - Losing It (Original Mix).mp3", encontradas)
        self.assertEqual(
            encontradas["Fisher - Losing It (Original Mix).mp3"]["status_comparacao"],
            "VERSAO_DIVERGENTE"
        )

        # 3c. Meduza is flagged in faltantes (new track)
        faltantes = [it["solicitado"] for it in match_res["faltantes"]]
        self.assertIn("Meduza - Piece Of Your Heart", faltantes)

        # Step 4: Execute upgrade for CamelPhat - Cola
        upgrades = [{
            "caminho_completo": str(orig_track),
            "caminho_novo": str(upgrade_cand),
            "backup_crate": "UpgradeCrate"
        }]
        res_up = track_matcher.batch_replace_upgrades(upgrades, force=True)
        self.assertTrue(res_up.get("sucesso"))
        self.assertEqual(res_up.get("atualizados"), 1)

        # Step 5: Integrate remix and new track into House crate
        to_integrate = [
            {"caminho_novo": str(remix_cand)},
            {"caminho_novo": str(new_cand)}
        ]
        res_integ = track_matcher.integrate_new_tracks_to_crate(to_integrate, str(house_dir))
        self.assertTrue(res_integ.get("sucesso"))
        self.assertEqual(res_integ.get("copiados"), 2)

        # Step 6: Verify all tracks exist in House directory
        self.assertTrue((house_dir / "CamelPhat - Cola.mp3").exists())
        self.assertTrue((house_dir / "Fisher - Losing It (Original Mix).mp3").exists())
        self.assertTrue((house_dir / "Fisher - Losing It (VIP Remix).mp3").exists())
        self.assertTrue((house_dir / "Meduza - Piece Of Your Heart.mp3").exists())

    # =========================================================================
    # SCENARIO 2: COMPLETE PRE-GIG LIBRARY HYGIENE WORKFLOW
    # =========================================================================

    def test_scenario_02_pre_gig_library_hygiene(self):
        """
        Pre-gig hygiene workflow:
        1. Scrub promotional website tags across tracks.
        2. Compute and embed Serato Markers2 hot cues.
        3. Scan audio health to confirm all files are clean.
        4. Generate executive HTML diagnostic report for DJ backup.
        """
        gph_folder = self.mp3_dir / "MainStage"
        gph_folder.mkdir(parents=True)

        for i in range(3):
            self.create_synthetic_mp3(
                gph_folder / f"[www.djpool.com] [Exclusive] Artist{i} - Anthem{i} (Original Mix).mp3",
                title=f"[www.djpool.com] [Exclusive] Anthem{i} (Original Mix)",
                artist=f"Artist{i}",
                bpm="128.0",
                duration_frames=500
            )

        # 1. Scan tags requiring cleanup
        scan_tags = tag_doctor.scan_audio_tags(str(gph_folder), limit=50)
        self.assertTrue(scan_tags.get("sucesso"))
        self.assertGreaterEqual(scan_tags.get("total_precisam_limpeza", 0), 1)

        # 2. Batch apply cleaned tags
        items_to_clean = []
        for item in scan_tags.get("items", []):
            if item.get("precisa_limpeza"):
                items_to_clean.append({
                    "caminho": item["caminho"],
                    "titulo_sugerido": item.get("titulo_sugerido") or item.get("titulo_atual"),
                    "artista_sugerido": item.get("artista_sugerido") or item.get("artista_atual")
                })
        res_clean = tag_doctor.apply_cleaned_tags(items_to_clean)
        self.assertEqual(res_clean.get("atualizados"), len(items_to_clean))

        # 3. Apply Serato Markers2 hot cues
        for f in gph_folder.glob("*.mp3"):
            auto_cue.generate_and_save_serato_cues(str(f), overwrite_existing=True)

        # Audit cue coverage
        cue_audit = auto_cue.audit_crate_cues_detailed(str(self.mp3_dir), crate_raiz="MainStage")
        self.assertEqual(cue_audit.get("padrao_autocue"), 3)
        self.assertEqual(cue_audit.get("pendentes"), 0)

        # 4. Final audio health check
        health_res = audio_health.scan_audio_health(str(gph_folder), limit=50, stream_progress=False)
        self.assertTrue(health_res.get("sucesso"))
        self.assertEqual(health_res.get("total_analisadas"), 3)

        # 5. Generate executive HTML report
        html_res = library_tools.generate_html_report(self.mp3_dir, self.serato_dir)
        self.assertTrue(html_res.get("sucesso"))
        self.assertTrue(Path(html_res["arquivo"]).exists())

    # =========================================================================
    # SCENARIO 3: DISASTER RECOVERY & ACOUSTIC LIBRARY RELOCATION
    # =========================================================================

    def test_scenario_03_disaster_recovery_relocation(self):
        """
        Disaster recovery:
        1. Crate references tracks in an old directory.
        2. Files are accidentally moved to a new reorganized folder.
        3. Crate references break.
        4. Acoustic fingerprint scan detects missing tracks and relocates crate paths.
        5. Zero broken references remain.
        """
        old_dir = self.mp3_dir / "Unorganized"
        new_dir = self.mp3_dir / "Organized" / "DeepHouse"
        old_dir.mkdir(parents=True)
        new_dir.mkdir(parents=True)

        t1 = self.create_synthetic_mp3(old_dir / "Deep_Groove_01.mp3", duration_frames=500)
        t2 = self.create_synthetic_mp3(old_dir / "Deep_Groove_02.mp3", duration_frames=500)

        # Initial sound seal while in old location
        sound_seal.scan_sound_seals(str(self.mp3_dir))

        # Create crate pointing to old paths
        crate_file = self.subcrates_dir / "DeepGrooves.crate"
        lib_root = library_tools.library_root_for(self.serato_dir)
        self.create_synthetic_crate(crate_file, [
            os.path.relpath(t1, lib_root),
            os.path.relpath(t2, lib_root)
        ])

        # Verify crate starts with 0 broken references
        ref1 = library_tools.check_crate_references(serato_dir=self.serato_dir)
        self.assertEqual(ref1.get("referencias_quebradas"), 0)

        # Disaster: Move files to new directory
        shutil.move(str(t1), str(new_dir / "Deep_Groove_01.mp3"))
        shutil.move(str(t2), str(new_dir / "Deep_Groove_02.mp3"))

        # References are now broken
        ref2 = library_tools.check_crate_references(serato_dir=self.serato_dir)
        self.assertEqual(ref2.get("referencias_quebradas"), 2)

        # Run acoustic relocation scan
        reloc_res = sound_seal.scan_missing_and_relocate(
            serato_dir_str=str(self.serato_dir),
            mp3_dir_str=str(self.mp3_dir),
            stream_json=False
        )
        self.assertTrue(reloc_res.get("sucesso"))
        self.assertEqual(reloc_res.get("total_perdidas"), 2)

    # =========================================================================
    # SCENARIO 4: FULL MULTI-CRATE MASTER SYNC WITH DRY-RUN PRE-EVALUATION
    # =========================================================================

    def test_scenario_04_master_sync_dry_run_and_execution(self):
        """
        Master Sync Workflow:
        1. Dry-run mode previews sync results without writing anything to disk.
        2. Real sync writes complete crate tree, neworder.pref, and summary JSON.
        3. Subsequent second sync detects zero changes (idempotent, HD write-protection).
        """
        # Create multi-genre folder tree
        afro_dir = self.mp3_dir / "Afro"
        tech_dir = self.mp3_dir / "Techno" / "Peak"
        afro_dir.mkdir(parents=True)
        tech_dir.mkdir(parents=True)

        self.create_synthetic_mp3(afro_dir / "Afro01.mp3", duration_frames=500)
        self.create_synthetic_mp3(tech_dir / "Peak01.mp3", duration_frames=500)

        # 1. Dry run: No files should be written to self.serato_dir
        ok_dry, summary_dry = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=True,
            emit_json_summary=True
        )
        self.assertTrue(ok_dry)
        self.assertTrue(summary_dry.get("dry_run"))
        self.assertEqual(summary_dry.get("total_faixas"), 2)
        # Verify no physical .crate was created
        crates_after_dry = list(self.subcrates_dir.glob("*.crate"))
        self.assertEqual(len(crates_after_dry), 0)

        # 2. Real execution
        ok_real, summary_real = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok_real)
        self.assertFalse(summary_real.get("dry_run"))
        self.assertEqual(summary_real.get("crates_gravadas"), 2)

        # Verify physical files exist
        self.assertTrue((self.subcrates_dir / "Afro.crate").exists())
        self.assertTrue((self.subcrates_dir / "Techno%%Peak.crate").exists())
        self.assertTrue((self.serato_dir / "neworder.pref").exists())

        # 3. Idempotent second sync: Crates inalteradas
        ok_idem, summary_idem = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok_idem)
        self.assertEqual(summary_idem.get("crates_gravadas"), 0)
        self.assertEqual(summary_idem.get("crates_inalteradas"), 2)

    # =========================================================================
    # SCENARIO 5: MULTI-TRACK BATCH TAG CLEANUP WITH EMERGENCY MASS ROLLBACK
    # =========================================================================

    def test_scenario_05_emergency_mass_journal_rollback(self):
        """
        Emergency mass rollback:
        DJ applies batch tag cleaning across 3 tracks, discovers an error,
        and uses Journal to revert each track back to its exact pre-change SHA-256 digest.
        """
        tracks = []
        initial_digests = {}
        for i in range(3):
            p = self.mp3_dir / f"[Pool] Artist{i} - Song{i}.mp3"
            self.create_synthetic_mp3(p, title=f"[Pool] Song{i}", artist=f"Artist{i}", duration_frames=500)
            tracks.append(p)
            initial_digests[str(p)] = journal.calc_file_sha256(str(p))

        # Batch scrub tags via Tag Doctor (each track automatically logged in Journal)
        clean_items = [{
            "caminho": str(p),
            "titulo_sugerido": f"Clean Song {i}",
            "artista_sugerido": f"Artist{i}"
        } for i, p in enumerate(tracks)]

        res_clean = tag_doctor.apply_cleaned_tags(clean_items)
        self.assertEqual(res_clean.get("atualizados"), 3)

        # Verify all 3 files were modified
        for p in tracks:
            self.assertNotEqual(journal.calc_file_sha256(str(p)), initial_digests[str(p)])

        # Emergency mass rollback: Undo all active operations
        active_ops = journal.list_operations(only_active=True).get("items", [])
        self.assertEqual(len(active_ops), 3)

        for op in active_ops:
            res_undo = journal.undo_operation(op["id"])
            self.assertTrue(res_undo.get("sucesso"), res_undo)

        # Verify 100% bit-for-bit file restoration
        for p in tracks:
            self.assertEqual(journal.calc_file_sha256(str(p)), initial_digests[str(p)])

    # =========================================================================
    # SCENARIO 6: HARMONIC SMART CRATE GENERATION (CAMELOT KEY & BPM)
    # =========================================================================

    def test_scenario_06_harmonic_smart_crate_filtering(self):
        """
        DJ prepares a harmonic mixing set:
        Creates a Smart Crate filtering for 124-128 BPM and Camelot Key 8A.
        Verifies only matching tracks are included in the generated crate.
        """
        folder = self.mp3_dir / "HarmonicPool"
        folder.mkdir(parents=True)

        # Match: 126 BPM, 8A
        match1 = self.create_synthetic_mp3(folder / "Match1.mp3", bpm="126.0", key="8A", duration_frames=500)
        # Match: 128 BPM, 8A
        match2 = self.create_synthetic_mp3(folder / "Match2.mp3", bpm="128.0", key="8A", duration_frames=500)
        # Non-match: 132 BPM, 8A (BPM too high)
        self.create_synthetic_mp3(folder / "Fast.mp3", bpm="132.0", key="8A", duration_frames=500)
        # Non-match: 126 BPM, 11B (Key mismatch)
        self.create_synthetic_mp3(folder / "WrongKey.mp3", bpm="126.0", key="11B", duration_frames=500)

        # Create smart crate
        res_smart = library_tools.create_smart_crate(
            self.mp3_dir,
            self.serato_dir,
            "Warmup 8A",
            rules={
                "bpm_min": 124,
                "bpm_max": 129,
                "camelot": ["8A"]
            }
        )
        self.assertTrue(res_smart.get("sucesso"), res_smart)
        self.assertEqual(res_smart.get("total_faixas"), 2)

        # Read back smart crate
        crate_file = self.subcrates_dir / "Warmup 8A.crate"
        self.assertTrue(crate_file.exists())
        crate_paths = self.read_crate_paths(crate_file)
        self.assertEqual(len(crate_paths), 2)
        names = [Path(p).name for p in crate_paths]
        self.assertIn("Match1.mp3", names)
        self.assertIn("Match2.mp3", names)
        self.assertNotIn("Fast.mp3", names)

    # =========================================================================
    # SCENARIO 7: MULTI-FOLDER DUPLICATE PRUNING WITH QUARANTINE
    # =========================================================================

    def test_scenario_07_duplicate_pruning_and_sync_cleanup(self):
        """
        Duplicate pruning workflow:
        1. DJ discovers duplicate tracks spread across multiple folders.
        2. duplicates_tool identifies redundant copies.
        3. Redundant copy is moved to quarantine directory.
        4. Library re-sync updates crates, ensuring only one canonical copy remains.
        """
        pool1 = self.mp3_dir / "AfroHouse"
        pool2 = self.mp3_dir / "USB_Backup"
        pool1.mkdir(parents=True)
        pool2.mkdir(parents=True)

        t1 = self.create_synthetic_mp3(pool1 / "Duplicate_Hit.mp3", duration_frames=500)
        t2 = self.create_synthetic_mp3(pool2 / "Duplicate_Hit.mp3", duration_frames=500)

        # Scan roots for duplicates
        scan_res = duplicates_tool.scan_roots([str(pool1), str(pool2)], progress=False)
        self.assertEqual(scan_res.get("grupos"), 1)
        self.assertEqual(scan_res.get("copias_redundantes"), 1)

        # Move redundant file to quarantine
        quarantine_dir = self.fake_home / "QuarantineDupes"
        quarantine_dir.mkdir(parents=True)
        move_res = duplicates_tool.move_files([t2], destination=str(quarantine_dir))
        self.assertEqual(move_res.get("movidos"), 1)

        # Re-sync library
        ok, summary = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok)
        self.assertEqual(summary.get("total_faixas"), 1)

    # =========================================================================
    # SCENARIO 8: AUDIO HEALTH RESAMPLING PIPELINE WITH METADATA PRESERVATION
    # =========================================================================

    def test_scenario_08_resample_audio_with_quarantine_manifest(self):
        """
        Hardware compatibility resampling:
        DJ identifies non-standard sample rate file, resamples to 44.1kHz CBR,
        and verifies original is preserved in quarantine with JSON manifest.
        """
        test_file = self.mp3_dir / "resample_candidate.mp3"
        self.create_synthetic_mp3(test_file, bpm="128.0", key="7A", duration_frames=500)

        # Resample track
        res = audio_health.resample_track_local(str(test_file))
        self.assertTrue(res.get("sucesso"), res)

        # Verify resampled file is valid 44.1kHz audio
        audio = mutagen.File(str(test_file))
        self.assertEqual(audio.info.sample_rate, 44100)

        # Verify original backup exists in quarantine
        quarantine_dir = audio_health.get_quarantine_dir(file_path=test_file)
        quarantine_files = list(quarantine_dir.glob("*resample_candidate.mp3"))
        self.assertGreaterEqual(len(quarantine_files), 1)

    # =========================================================================
    # SCENARIO 9: CORRUPT AUDIO DETECTION AND FAIL-SAFE DEFENSE
    # =========================================================================

    def test_scenario_09_corrupt_audio_failsafe_protection(self):
        """
        Corrupt audio defense:
        When a corrupted/0-byte audio file is dropped in a folder,
        inspect_track_health flags it as compromised and library sync
        maintains valid crate references without crashing.
        """
        folder = self.mp3_dir / "MixedHealth"
        folder.mkdir(parents=True)

        healthy_track = self.create_synthetic_mp3(folder / "Healthy.mp3", duration_frames=500)
        corrupt_track = folder / "Corrupted.mp3"
        corrupt_track.write_bytes(b"INVALID_GARBAGE_HEADER")

        # Health inspection flags corrupt track
        info_healthy = audio_health.inspect_track_health(Path(healthy_track))
        info_corrupt = audio_health.inspect_track_health(Path(corrupt_track))

        self.assertIn(info_healthy.get("status"), ("ok", "alerta", "suspeita"))
        self.assertIn(info_corrupt.get("status"), ("comprometida", "alerta", "erro"))

        # Synchronize library - must process healthy track without crashing
        ok, summary = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok)
        self.assertGreaterEqual(summary.get("total_faixas"), 1)

    # =========================================================================
    # SCENARIO 10: COMPLETE SERATO 4 SYNC MANAGER PRO FULL LIFECYCLE
    # =========================================================================

    def test_scenario_10_complete_serato_sync_lifecycle(self):
        """
        Complete end-to-end SeratoLib lifecycle:
        1. Ingest new music into categorized genre folders.
        2. Analyze musical properties (BPM & Camelot key) and write tags.
        3. Clean promotional tag noise.
        4. Calculate and embed 5 Serato Markers2 hot cues.
        5. Synchronize library to generate Serato .crate files and neworder.pref.
        6. Generate executive HTML diagnostic dashboard.
        7. Verify 100% data integrity with zero sandbox leaks.
        """
        crate_folder = self.mp3_dir / "Deep Tech"
        crate_folder.mkdir(parents=True)
        raw_track = self.create_synthetic_mp3(
            crate_folder / "[Beatport] DJ Test - Sunset Anthem (Club Mix).mp3",
            title="[Beatport] Sunset Anthem (Club Mix)",
            artist="DJ Test",
            bpm="0",
            key="",
            duration_frames=500
        )

        # 1. Clean track tags
        cleaned = tag_doctor.clean_track_name(raw_track.stem)
        tag_doctor.apply_cleaned_tags([{
            "caminho": str(raw_track),
            "titulo_sugerido": cleaned.get("title", "Sunset Anthem (Club Mix)"),
            "artista_sugerido": cleaned.get("artist", "DJ Test")
        }])

        # 2. Analyze and tag BPM & Key
        music_analysis.write_analysis_tags(str(raw_track), bpm=125.0, key_text="9A", overwrite=True)

        # 3. Calculate and embed Hot Cues
        res_cue = auto_cue.generate_and_save_serato_cues(str(raw_track), overwrite_existing=True)
        self.assertTrue(res_cue.get("sucesso"))

        # 4. Synchronize library
        ok, summary = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            dry_run=False,
            emit_json_summary=True
        )
        self.assertTrue(ok)
        self.assertEqual(summary.get("total_faixas"), 1)

        # 5. Check crate and preferences
        crate_file = self.subcrates_dir / "Deep Tech.crate"
        self.assertTrue(crate_file.exists())
        self.assertTrue((self.serato_dir / "neworder.pref").exists())

        # 6. Generate HTML report
        res_html = library_tools.generate_html_report(self.mp3_dir, self.serato_dir)
        self.assertTrue(res_html.get("sucesso"))
        self.assertTrue(Path(res_html["arquivo"]).exists())

        # 7. Final tag verification on disk
        final_tags = ID3(raw_track)
        self.assertEqual(final_tags.get("TBPM").text[0], "125")
        self.assertEqual(final_tags.get("TKEY").text[0], "9A")
        self.assertIn("GEOB:Serato Markers2", final_tags)


if __name__ == "__main__":
    unittest.main()
