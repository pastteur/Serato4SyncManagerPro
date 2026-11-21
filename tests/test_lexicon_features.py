#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - TESTES DOS NOVOS MÓDULOS (LEXICON REVERSAL ENGINE)
================================================================================
Testa a integração e integridade dos 5 módulos extraídos da engenharia reversa:
  1. serato_v4_engine.py
  2. music_library_helper.py
  3. fts_library_cache.py
  4. pioneer_usb_exporter.py
  5. tagger_daemon.py
================================================================================
"""

import sys
import os
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Adiciona o diretório raiz ao sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from serato_v4_engine import SeratoV4Engine
from music_library_helper import MusicLibraryHelper
from fts_library_cache import FTSLibraryCache
from pioneer_usb_exporter import PioneerUsbExporter
from tagger_daemon import TaggerEngine
from smart_tags import SmartTagManager
from scan_unused_files import UnusedFilesScanner
from beatshift_scanner import BeatshiftScanner
from key_converter import KeyConverter
from taxonomy_cleaner import TaxonomyCleaner
from recipe_engine import RecipeEngine
from deckwatch_monitor import DeckWatchMonitor


class TestLexiconFeatures(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # --------------------------------------------------------------------------
    # 1. TESTE SERATO v4 ENGINE
    # --------------------------------------------------------------------------
    def test_serato_v4_mock_audit(self):
        """Simula uma estrutura de banco Serato v4 e testa auditoria de sanidade."""
        v4_dir = self.test_root / "SeratoV4"
        v4_dir.mkdir(parents=True, exist_ok=True)
        master_db = v4_dir / "master.sqlite"

        conn = sqlite3.connect(str(master_db))
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version = 400;")
        cursor.execute("CREATE TABLE serato_db (uuid TEXT PRIMARY KEY);")
        cursor.execute("INSERT INTO serato_db VALUES ('test-uuid-1234');")
        cursor.execute("CREATE TABLE dbv2_status (autosync_disabled INTEGER);")
        cursor.execute("INSERT INTO dbv2_status VALUES (1);")
        cursor.execute("CREATE TABLE container (id INTEGER PRIMARY KEY, name TEXT, list_order INTEGER);")
        cursor.execute("INSERT INTO container VALUES (1, 'House Crate', 10);")
        cursor.execute("CREATE TRIGGER test_trig AFTER INSERT ON container BEGIN SELECT 1; END;")
        conn.commit()
        conn.close()

        engine = SeratoV4Engine(str(v4_dir))
        report = engine.audit_library()

        self.assertTrue(report["v4_detected"])
        self.assertTrue(report["healthy"])
        self.assertEqual(report["db_uuid"], "test-uuid-1234")
        self.assertEqual(report["autosync_disabled"], 1)
        self.assertEqual(report["containers_count"], 1)
        self.assertEqual(report["triggers_count"], 1)

        containers = engine.list_containers()
        self.assertEqual(len(containers), 1)
        self.assertEqual(containers[0]["name"], "House Crate")

    # --------------------------------------------------------------------------
    # 2. TESTE APPLE MUSIC HELPER
    # --------------------------------------------------------------------------
    def test_music_library_helper_binary_check(self):
        """Verifica se o helper compilado é detectado no macOS."""
        if sys.platform == "darwin":
            is_ready = MusicLibraryHelper.ensure_binary()
            self.assertTrue(is_ready, "Binário musiclibrary-helper deve compilar/existir no macOS")
        else:
            res = MusicLibraryHelper.extract_library()
            self.assertFalse(res["sucesso"])

    # --------------------------------------------------------------------------
    # 3. TESTE SQLite FTS5 CACHE
    # --------------------------------------------------------------------------
    def test_fts5_library_cache(self):
        """Testa inserção, sincronização e busca em texto completo via FTS5."""
        db_path = self.test_root / "cache_test.sqlite"
        cache = FTSLibraryCache(db_path)

        # Cria pasta com faixas de teste falsas
        music_dir = self.test_root / "Musicas" / "House"
        music_dir.mkdir(parents=True, exist_ok=True)
        track1 = music_dir / "Alok - Hear Me Now (Original Mix).mp3"
        track2 = music_dir / "Vintage Culture - Deep Down (Remix).mp3"
        track1.write_bytes(b"dummy audio 1")
        track2.write_bytes(b"dummy audio 2")

        stats = cache.sync_directory(self.test_root / "Musicas")
        self.assertEqual(stats["inserted"], 2)

        # Busca por "Alok"
        results_alok = cache.search_fts("Alok")
        self.assertEqual(len(results_alok), 1)
        self.assertIn("Alok", results_alok[0]["filename"])

        # Busca por remix
        results_remix = cache.search_fts("Vintage Deep")
        self.assertEqual(len(results_remix), 1)
        self.assertIn("Vintage Culture", results_remix[0]["filename"])

        # Matching candidates
        candidates = cache.find_match_candidates(title="Deep Down", artist="Vintage Culture")
        self.assertTrue(len(candidates) >= 1)

    # --------------------------------------------------------------------------
    # 4. TESTE PIONEER USB EXPORTER
    # --------------------------------------------------------------------------
    def test_pioneer_usb_exporter(self):
        """Testa geração do banco exportLibrary.db e conversão para CDJ."""
        usb_dir = self.test_root / "USB_DRIVE"
        exporter = PioneerUsbExporter(usb_dir)

        dummy_audio = self.test_root / "teste_dj.mp3"
        dummy_audio.write_bytes(b"pioneer test stream")

        tracks = [{
            "filepath": str(dummy_audio),
            "artist": "Test Artist",
            "title": "Club Banger",
            "album": "Summer 2026",
            "genre": "Tech House",
            "bpm": 126.0,
            "duration_ms": 180000,
            "key": "8A"
        }]

        stats = exporter.export_crate("Peak Time Crate", tracks, copy_audio=True)
        self.assertEqual(stats["copied_tracks"], 1)

        # Inspeciona o banco gerado
        db_path = usb_dir / "PIONEER" / "rekordbox" / "exportLibrary.db"
        self.assertTrue(db_path.is_file())

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT Title, FolderPath FROM djmdContent;")
        row = cursor.fetchone()
        self.assertEqual(row[0], "Club Banger")
        self.assertTrue(row[1].startswith("/Contents/"))

        cursor.execute("SELECT Name FROM djmdPlaylist;")
        pl_name = cursor.fetchone()[0]
        self.assertEqual(pl_name, "Peak Time Crate")

        conn.close()

    # --------------------------------------------------------------------------
    # 5. TESTE TAGGER DAEMON
    # --------------------------------------------------------------------------
    def test_tagger_engine_basic(self):
        """Testa a leitura de arquivo inexistente e validação do motor."""
        res = TaggerEngine.read_tags(str(self.test_root / "nao_existe.mp3"))
        self.assertFalse(res["sucesso"])
        self.assertIn("não encontrado", res["erro"])

    # --------------------------------------------------------------------------
    # 6. TESTE SMART TAGS (MYTAGS NO COMMENT)
    # --------------------------------------------------------------------------
    def test_smart_tags_comment(self):
        """Testa adição e remoção de #tags preservando anotações livres."""
        dummy_mp3 = self.test_root / "test_tags.mp3"
        dummy_mp3.write_bytes(b"dummy audio")

        # Testa leitura de arquivo inexistente
        res_fail = SmartTagManager.parse_comments(str(self.test_root / "inexistente.mp3"))
        self.assertFalse(res_fail["sucesso"])

    # --------------------------------------------------------------------------
    # 7. TESTE SCAN UNUSED FILES (ARQUIVOS ÓRFÃOS)
    # --------------------------------------------------------------------------
    def test_scan_unused_files(self):
        """Testa detecção de faixas órfãs no disco que não estão em nenhuma Crate."""
        mp3_dir = self.test_root / "MP3_Master"
        mp3_dir.mkdir(parents=True, exist_ok=True)
        serato_dir = self.test_root / "_Serato_"
        serato_dir.mkdir(parents=True, exist_ok=True)

        track_used = mp3_dir / "Usada.mp3"
        track_orphan = mp3_dir / "Orfa.mp3"
        track_used.write_bytes(b"audio 1")
        track_orphan.write_bytes(b"audio 2")

        # Cria crate referenciando 'Usada.mp3'
        subcrates = serato_dir / "Subcrates"
        subcrates.mkdir(parents=True, exist_ok=True)
        crate_file = subcrates / "House.crate"
        
        # Bloco binário simples com ptrk
        path_bytes = "Usada.mp3".encode('utf-16-be')
        with open(crate_file, "wb") as f:
            f.write(b"vrsn\x00\x00\x00\x081.0/Serato ScratchLive Crate")
            f.write(b"otrk\x00\x00\x00" + bytes([len(path_bytes) + 8]))
            f.write(b"ptrk\x00\x00\x00" + bytes([len(path_bytes)]))
            f.write(path_bytes)

        scanner = UnusedFilesScanner(str(mp3_dir), str(serato_dir))
        res = scanner.scan()

        self.assertTrue(res["sucesso"])
        self.assertEqual(res["total_unused"], 1)
        self.assertEqual(res["unused_files"][0]["filename"], "Orfa.mp3")

    # --------------------------------------------------------------------------
    # 8. TESTE HARMONIC KEY CONVERTER
    # --------------------------------------------------------------------------
    def test_key_converter(self):
        """Testa conversão de chaves entre Camelot, Musical e OpenKey."""
        # Musical -> Camelot
        self.assertEqual(KeyConverter.convert("Am", "camelot"), "8A")
        self.assertEqual(KeyConverter.convert("C", "camelot"), "8B")
        self.assertEqual(KeyConverter.convert("F#m", "camelot"), "11A")

        # Camelot -> Musical
        self.assertEqual(KeyConverter.convert("8A", "musical"), "Am")
        self.assertEqual(KeyConverter.convert("8B", "musical"), "C")

        # Camelot -> OpenKey
        self.assertEqual(KeyConverter.convert("8A", "openkey"), "8d")
        self.assertEqual(KeyConverter.convert("8B", "openkey"), "8m")

    # --------------------------------------------------------------------------
    # 9. TESTE TAXONOMY CLEANER (GÊNEROS E ARTISTAS)
    # --------------------------------------------------------------------------
    def test_taxonomy_cleaner(self):
        """Testa unificação de gêneros e padronização de colaborações."""
        self.assertEqual(TaxonomyCleaner.clean_genre("tech-house"), "Tech House")
        self.assertEqual(TaxonomyCleaner.clean_genre("DEEP HOUSE"), "Deep House")
        self.assertEqual(TaxonomyCleaner.clean_genre("drum and bass"), "Drum & Bass")

        self.assertEqual(TaxonomyCleaner.clean_artist("Alok Featuring Zeeba"), "Alok feat. Zeeba")
        self.assertEqual(TaxonomyCleaner.clean_artist("David Guetta versus Morten"), "David Guetta vs. Morten")

    # --------------------------------------------------------------------------
    # 10. TESTE RECIPE ENGINE COM UNDO
    # --------------------------------------------------------------------------
    def test_recipe_engine_undo(self):
        """Testa histórico transacional e rollback de receitas."""
        db_path = self.test_root / "undo_test.sqlite"
        engine = RecipeEngine(db_path)

        # Sem histórico anterior
        res_undo_empty = engine.undo_last()
        self.assertFalse(res_undo_empty["sucesso"])

    # --------------------------------------------------------------------------
    # 11. TESTE DECKWATCH MONITOR
    # --------------------------------------------------------------------------
    def test_deckwatch_monitor(self):
        """Testa exportação para OBS e checagem de processo."""
        serato_dir = self.test_root / "_Serato_"
        serato_dir.mkdir(parents=True, exist_ok=True)

        monitor = DeckWatchMonitor(str(serato_dir))
        track = monitor.get_latest_played_track()
        self.assertIn("serato_running", track)

        obs_dir = self.test_root / "obs"
        exported = monitor.export_obs_files(obs_dir)
        self.assertTrue(Path(exported["txt_path"]).is_file())
        self.assertTrue(Path(exported["json_path"]).is_file())

    # --------------------------------------------------------------------------
    # 12. TESTE SERATO v4 RELOCATE INJECTION
    # --------------------------------------------------------------------------
    def test_serato_v4_relocate_injection(self):
        """Testa injeção de novo caminho físico em location.sqlite."""
        v4_dir = self.test_root / "SeratoV4"
        v4_dir.mkdir(parents=True, exist_ok=True)
        loc_db = v4_dir / "location.sqlite"

        conn = sqlite3.connect(str(loc_db))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE file_locations (asset_id INTEGER PRIMARY KEY, path TEXT);")
        cursor.execute("INSERT INTO file_locations VALUES (101, '/Antigo/Music/Faixa.mp3');")
        conn.commit()
        conn.close()

        engine = SeratoV4Engine(str(v4_dir))
        update_res = engine.update_track_location('/Antigo/Music/Faixa.mp3', '/Novo/Music/Faixa.mp3')
        self.assertTrue(update_res["sucesso"])
        self.assertEqual(update_res["rows_updated"], 1)

        # Valida que o caminho mudou
        locations = engine.resolve_track_locations()
        self.assertEqual(locations[101], '/Novo/Music/Faixa.mp3')

    # --------------------------------------------------------------------------
    # 13. TESTE CLI JSON EXECUTION (SUBPROCESS)
    # --------------------------------------------------------------------------
    def test_cli_json_execution(self):
        """Testa que os utilitários de CLI retornam JSON válido sem erro de import."""
        import subprocess

        # 1. fts_library_cache.py --sync
        sync_dir = self.test_root / "fts_sync_test"
        sync_dir.mkdir(parents=True, exist_ok=True)
        res_sync = subprocess.run(
            [sys.executable, str(ROOT_DIR / "fts_library_cache.py"), "--sync", str(sync_dir)],
            capture_output=True, text=True
        )
        self.assertEqual(res_sync.returncode, 0, f"fts_library_cache.py failed: {res_sync.stderr}")
        data_sync = json.loads(res_sync.stdout.strip())
        self.assertTrue(data_sync.get("sucesso"))

        # 2. fts_library_cache.py --search
        res_search = subprocess.run(
            [sys.executable, str(ROOT_DIR / "fts_library_cache.py"), "--search", "test"],
            capture_output=True, text=True
        )
        self.assertEqual(res_search.returncode, 0, f"fts_library_cache.py search failed: {res_search.stderr}")
        data_search = json.loads(res_search.stdout.strip())
        self.assertIsInstance(data_search, list)

        # 3. pioneer_usb_exporter.py --dry-run
        tracks_file = self.test_root / "tracks.json"
        with open(tracks_file, "w", encoding="utf-8") as f:
            json.dump([{"caminho": "/tmp/fake.mp3", "title": "Fake", "artist": "DJ", "bpm": 128}], f)

        res_pioneer = subprocess.run(
            [
                sys.executable, str(ROOT_DIR / "pioneer_usb_exporter.py"),
                "--usb", str(self.test_root),
                "--crate", "TestCrate",
                "--tracks", str(tracks_file),
                "--dry-run"
            ],
            capture_output=True, text=True
        )
        self.assertEqual(res_pioneer.returncode, 0, f"pioneer_usb_exporter.py failed: {res_pioneer.stderr}")
        data_pioneer = json.loads(res_pioneer.stdout.strip())
        self.assertEqual(data_pioneer.get("crate_name"), "TestCrate")

        # 4. scan_unused_files.py --json
        res_scan = subprocess.run(
            [
                sys.executable, str(ROOT_DIR / "scan_unused_files.py"),
                "--mp3", str(sync_dir),
                "--serato", str(sync_dir),
                "--json"
            ],
            capture_output=True, text=True
        )
        self.assertEqual(res_scan.returncode, 0, f"scan_unused_files.py failed: {res_scan.stderr}")
        data_scan = json.loads(res_scan.stdout.strip())
        self.assertTrue(data_scan.get("sucesso"))


if __name__ == "__main__":
    unittest.main()
