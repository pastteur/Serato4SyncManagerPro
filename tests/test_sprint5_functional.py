#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 5 SYNC MANAGER PRO - TESTES SPRINT 5 (CORREÇÕES FUNCIONAIS)
================================================================================
Validação automatizada das correções funcionais de:
1. Pioneer USB Exporter (Quick Hash, detecção confiável de desatualizados, cópia atômica)
2. SQLite FTS5 Cache (Purga de resultados fantasma / ghost entries, rebuild)
3. Duplicates Engine (Keeper weighting com Sound Seal e Serato Markers)
================================================================================
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pioneer_usb_exporter
import fts_library_cache
import duplicates_tool


class TestSprint5Functional(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_pioneer_quick_hash_and_up_to_date(self):
        """Verifica integridade do quick hash e detecção de arquivos desatualizados."""
        src_file = self.root / "track1.mp3"
        dest_file = self.root / "copy1.mp3"

        # Arquivo de 2MB
        content = b"AUDIO_SAMPLE_DATA_CHUNK_" * (2 * 1024 * 1024 // 24)
        src_file.write_bytes(content)

        # Destino ainda não existe
        self.assertFalse(pioneer_usb_exporter.is_copy_up_to_date(src_file, dest_file))

        # Cria destino com mesmo tamanho mas bytes centrais alterados
        tampered = bytearray(content)
        tampered[len(tampered) // 2] ^= 0xFF
        dest_file.write_bytes(tampered)

        # Tamanho é idêntico, mas conteúdo é diferente -> NÃO deve considerar up to date!
        self.assertEqual(src_file.stat().st_size, dest_file.stat().st_size)
        self.assertFalse(pioneer_usb_exporter.is_copy_up_to_date(src_file, dest_file))

        # Agora grava cópia exata
        dest_file.write_bytes(content)
        self.assertTrue(pioneer_usb_exporter.is_copy_up_to_date(src_file, dest_file))

    def test_02_pioneer_export_crate_atomic_and_skip(self):
        """Exporta crate para USB simulado com verificação atômica e pulo de arquivos inalterados."""
        usb_dir = self.root / "USB_DRIVE"
        tracks_dir = self.root / "Music"
        tracks_dir.mkdir()

        t1 = tracks_dir / "Song_A.mp3"
        t1.write_bytes(b"SERATO_AUDIO_A_" * 5000)

        tracks = [
            {
                "filepath": str(t1),
                "artist": "Test Artist",
                "album": "Test Album",
                "title": "Song A",
                "genre": "House",
                "bpm": 126.0,
                "key": "8A",
                "duration_ms": 180000
            }
        ]

        exporter = pioneer_usb_exporter.PioneerUsbExporter(usb_dir)
        # Primeira exportação: deve copiar o arquivo
        res1 = exporter.export_crate("Favorites", tracks, copy_audio=True, dry_run=False)
        self.assertTrue(res1["sucesso"])
        self.assertEqual(res1["copied_tracks"], 1)
        self.assertEqual(res1["skipped_up_to_date"], 0)
        self.assertTrue((usb_dir / "PIONEER" / "rekordbox" / "exportLibrary.db").is_file())

        # Segunda exportação: deve detectar como up to date e pular cópia
        res2 = exporter.export_crate("Favorites", tracks, copy_audio=True, dry_run=False)
        self.assertTrue(res2["sucesso"])
        self.assertEqual(res2["copied_tracks"], 0)
        self.assertEqual(res2["skipped_up_to_date"], 1)

    def test_03_fts_cache_ghost_result_purging(self):
        """Ao deletar arquivo do disco, search_fts não retorna o resultado e limpa o banco."""
        db_path = self.root / "fts_test.sqlite"
        cache = fts_library_cache.FTSLibraryCache(db_path=db_path)

        audio_dir = self.root / "AudioFiles"
        audio_dir.mkdir()
        track_p = audio_dir / "Vintage Culture - Deep Down.mp3"
        track_p.write_bytes(b"DUMMY_MP3_STREAM" * 100)

        # Sincroniza diretório
        stats = cache.sync_directory(audio_dir)
        self.assertEqual(stats["inserted"], 1)

        # Busca deve encontrar o arquivo
        found = cache.search_fts("Vintage Culture", limit=10)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["filename"], track_p.name)

        # Deleta fisicamente o arquivo do disco
        track_p.unlink()

        # Busca subsequente DEVE purgar a entrada fantasma e retornar vazio
        found_after = cache.search_fts("Vintage Culture", limit=10)
        self.assertEqual(len(found_after), 0)

    def test_04_fts_cache_rebuild_database(self):
        """Verifica se o método rebuild_database recria os índices e triggers FTS5."""
        db_path = self.root / "fts_rebuild_test.sqlite"
        cache = fts_library_cache.FTSLibraryCache(db_path=db_path)
        ok = cache.rebuild_database()
        self.assertTrue(ok)

    def test_05_choose_keeper_prioritizes_sound_seal_and_serato(self):
        """Verifica que _choose_keeper prioriza faixas com Sound Seal acústico e Serato Markers."""
        candidatos = [
            {
                "caminho": "/pool/copy.mp3",
                "nome": "Hit (1).mp3",
                "bitrate_kbps": 320,
                "sound_seal": "",
                "has_serato_markers": False,
                "origem": "externa",
                "bpm": "",
                "key": "",
                "mtime": 1000.0
            },
            {
                "caminho": "/pool/master.mp3",
                "nome": "Hit.mp3",
                "bitrate_kbps": 320,
                "sound_seal": "SEAL_SHA256_VERIFIED_ACOUSTIC_778899",
                "has_serato_markers": True,
                "origem": "serato",
                "bpm": "128",
                "key": "11B",
                "mtime": 500.0
            }
        ]
        escolhido = duplicates_tool._choose_keeper(candidatos)
        self.assertIsNotNone(escolhido)
        self.assertEqual(escolhido["caminho"], "/pool/master.mp3")


if __name__ == "__main__":
    unittest.main()
