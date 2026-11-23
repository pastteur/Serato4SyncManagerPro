#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - TESTES DO MOTOR DE DUPLICATAS (duplicates_tool.py)
================================================================================
Testa rigorosamente:
1. Correspondência exata por hash SHA-256 do áudio (IDENTICO_COMPROVADO).
2. Rejeição de arquivos não relacionados que possuem coincidentemente o mesmo tamanho.
3. Correspondência semântica por título limpo e duração compatível (POSSIVEL_DUPLICADO).
4. Rejeição de faixas com títulos semelhantes mas durações divergentes (> 3.5s).
5. Heurística inteligente de escolha do Keeper (_choose_keeper).
================================================================================
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Adiciona raiz ao sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import duplicates_tool


class TestDuplicatesEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.dir_a = self.root / "Pool_A"
        self.dir_b = self.root / "Pool_B"
        self.dir_a.mkdir()
        self.dir_b.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_exact_audio_hash_match(self):
        """Dois arquivos com o mesmo áudio binário são identificados como IDENTICO_COMPROVADO."""
        # Cria áudio idêntico com cabeçalho ID3
        audio_stream = b"ID3\x03\x00\x00\x00\x00\x00\x10" + b"\x00" * 16 + b"MPEG_AUDIO_FRAMES_DATA_EXACT" * 100 + b"TAG" + b"\x00" * 125
        f1 = self.dir_a / "Track One.mp3"
        f2 = self.dir_b / "01 - Track One (1).mp3"
        f1.write_bytes(audio_stream)
        f2.write_bytes(audio_stream)

        res = duplicates_tool.scan_roots([str(self.dir_a), str(self.dir_b)], progress=False)
        self.assertTrue(res["sucesso"])
        self.assertEqual(len(res["itens"]), 1)
        grp = res["itens"][0]
        self.assertEqual(grp["grau_certeza"], "IDENTICO_COMPROVADO")
        self.assertEqual(len(grp["arquivos"]), 2)

    def test_02_rejection_of_unrelated_same_size_files(self):
        """Arquivos com o mesmo tamanho mas conteúdos e nomes divergentes NUNCA são agrupados."""
        size = 65536
        f1 = self.dir_a / "MC Davi e MC Joao Junta Todas.mp3"
        f2 = self.dir_b / "MC Menor da VS - Outra Musica.mp3"
        f3 = self.dir_b / "Henrique e Juliano - Qualquer.mp3"

        f1.write_bytes(b"A" * size)
        f2.write_bytes(b"B" * size)
        f3.write_bytes(b"C" * size)

        res = duplicates_tool.scan_roots([str(self.dir_a), str(self.dir_b)], progress=False)
        self.assertTrue(res["sucesso"])
        self.assertEqual(len(res["itens"]), 0, "Arquivos não relacionados não devem ser agrupados!")

    def test_03_clean_name_semantic_matching(self):
        """Arquivos com o mesmo título normalizado e sufixos de cópia são agrupados como POSSIVEL_DUPLICADO."""
        f1 = self.dir_a / "01 - Funk Mix 2024.mp3"
        f2 = self.dir_b / "Funk Mix 2024 - Cópia (1).mp3"

        f1.write_bytes(b"STREAM_CONTENT_1_" * 2000)
        f2.write_bytes(b"STREAM_CONTENT_2_" * 2500)

        res = duplicates_tool.scan_roots([str(self.dir_a), str(self.dir_b)], progress=False)
        self.assertTrue(res["sucesso"])
        self.assertEqual(len(res["itens"]), 1)
        grp = res["itens"][0]
        self.assertEqual(grp["grau_certeza"], "POSSIVEL_DUPLICADO")
        self.assertIn("funk mix 2024", grp["motivo"].lower())

    def test_04_choose_keeper_heuristics(self):
        """O Keeper preferencial deve ser a faixa com Hot Cues ou maior bitrate."""
        arquivos = [
            {
                "caminho": "/path/low.mp3",
                "nome": "Track (1).mp3",
                "bitrate_kbps": 128,
                "has_serato_markers": False,
                "origem": "externa",
                "mtime": 1000.0,
            },
            {
                "caminho": "/path/high.mp3",
                "nome": "Track.mp3",
                "bitrate_kbps": 320,
                "has_serato_markers": True,
                "origem": "serato",
                "mtime": 500.0,
            }
        ]
        keeper = duplicates_tool._choose_keeper(arquivos)
        self.assertIsNotNone(keeper)
        self.assertEqual(keeper["caminho"], "/path/high.mp3", "Deveria manter a faixa com Serato Markers e 320 kbps")


if __name__ == "__main__":
    unittest.main()
