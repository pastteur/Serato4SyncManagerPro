#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes das funções novas: análise de BPM/tom, journal de desfazer,
referências de crate, M3U, crates inteligentes, saúde e novas faixas.
Todos os estados gravam em pasta temporária (nada toca ~/).
"""
import os
import sys
import json
import math
import wave
import shutil
import struct
import random
import tempfile
import unittest
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import music_analysis
import journal
import library_tools
from track_matcher import export_matched_to_serato_crate

try:
    from mutagen.id3 import ID3, TBPM, TKEY
except ImportError:
    ID3 = None

FFMPEG = music_analysis.get_ffmpeg_bin()


def _write_wav_clicks(path, bpm=120.0, seconds=40, sr=44100):
    rnd = random.Random(7)
    n = sr * seconds
    buf = [rnd.uniform(-0.02, 0.02) for _ in range(n)]
    period = int(sr * 60.0 / bpm)
    for k in range(0, n, period):
        for j in range(300):
            if k + j < n:
                buf[k + j] += math.sin(2 * math.pi * 900 * j / sr) * math.exp(-j / 60.0) * 0.9
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b''.join(struct.pack('<h', int(max(-1, min(1, s)) * 20000)) for s in buf))


def _write_wav_chord(path, freqs, seconds=40, sr=44100):
    samples = [sum(math.sin(2 * math.pi * f * i / sr) for f in freqs) / len(freqs) for i in range(sr * seconds)]
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b''.join(struct.pack('<h', int(s * 20000)) for s in samples))


def _make_mp3(path, seconds=60, freq=440):
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=%d:duration=%d" % (freq, seconds),
                    "-b:a", "192k", "-y", str(path)], check=True)


@unittest.skipIf(FFMPEG is None or ID3 is None, "ffmpeg ou mutagen indisponível")
class TestMusicAnalysis(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="analysis_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bpm_click_track_is_accurate(self):
        wav = self.tmp / "click120.wav"
        _write_wav_clicks(wav, bpm=120.0)
        res = music_analysis.analyze_file(str(wav))
        self.assertTrue(res["sucesso"], res)
        self.assertLessEqual(abs(res["bpm"] - 120.0), 1.0, res)
        self.assertGreater(res["bpm_confianca"], 0.5)

    def test_key_c_major_chord(self):
        wav = self.tmp / "cmaj.wav"
        _write_wav_chord(wav, [261.63, 329.63, 392.00])
        res = music_analysis.analyze_file(str(wav))
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["tom"], "C major")
        self.assertEqual(res["camelot"], "8B")

    def test_key_a_minor_chord(self):
        wav = self.tmp / "amin.wav"
        _write_wav_chord(wav, [220.0, 261.63, 329.63])
        res = music_analysis.analyze_file(str(wav))
        self.assertEqual(res["tom"], "A minor")
        self.assertEqual(res["camelot"], "8A")


@unittest.skipIf(FFMPEG is None or ID3 is None, "ffmpeg ou mutagen indisponível")
class TestJournalUndo(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="journal_test_"))
        self._orig_journal = journal.JOURNAL_PATH
        journal.JOURNAL_PATH = self.tmp / "journal.sqlite"

    def tearDown(self):
        journal.JOURNAL_PATH = self._orig_journal
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _audio_tail(self, path):
        _, size = journal.read_leading_id3(str(path))
        with open(path, 'rb') as f:
            f.seek(size)
            return f.read()

    def test_write_tags_then_undo_restores_exact_state(self):
        mp3 = self.tmp / "faixa.mp3"
        _make_mp3(mp3)
        tail_before = self._audio_tail(mp3)
        block_before, _ = journal.read_leading_id3(str(mp3))

        res = music_analysis.write_analysis_tags(str(mp3), bpm=124, key_text="8A")
        self.assertTrue(res["sucesso"], res)
        self.assertTrue(res["gravado"])
        self.assertEqual(str(ID3(str(mp3))["TBPM"]), "124")
        self.assertEqual(self._audio_tail(mp3), tail_before, "áudio não pode mudar ao gravar tags")

        desfeito = journal.undo_operation()
        self.assertTrue(desfeito["sucesso"], desfeito)
        self.assertEqual(self._audio_tail(mp3), tail_before, "áudio deve permanecer idêntico após undo")
        block_after, _ = journal.read_leading_id3(str(mp3))
        self.assertEqual(block_after, block_before)
        self.assertNotIn("TBPM", ID3(str(mp3)))

    def test_undo_without_previous_id3_removes_tag_block(self):
        mp3 = self.tmp / "sem_tag.mp3"
        _make_mp3(mp3)
        # remove qualquer ID3 para simular arquivo sem tags
        _, size = journal.read_leading_id3(str(mp3))
        with open(mp3, 'rb') as f:
            f.seek(size)
            audio = f.read()
        mp3.write_bytes(audio)
        tail = self._audio_tail(mp3)

        self.assertTrue(music_analysis.write_analysis_tags(str(mp3), bpm=100)["gravado"])
        self.assertTrue(journal.undo_operation()["sucesso"])
        self.assertEqual(mp3.read_bytes(), tail)

    def test_list_operations_reports_active_and_undone(self):
        mp3 = self.tmp / "lista.mp3"
        _make_mp3(mp3)
        music_analysis.write_analysis_tags(str(mp3), bpm=90)
        ops = journal.list_operations()
        self.assertEqual(ops["total"], 1)
        self.assertFalse(ops["items"][0]["desfeita"])
        journal.undo_operation()
        self.assertTrue(journal.list_operations()["items"][0]["desfeita"])


@unittest.skipIf(FFMPEG is None or ID3 is None, "ffmpeg ou mutagen indisponível")
class TestLibraryTools(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="library_test_"))
        self.root = self.tmp / "Home"
        self.mp3_dir = self.root / "Music" / "MP3"
        self.serato = self.root / "_Serato_"
        (self.serato / "Subcrates").mkdir(parents=True)
        self.mp3_dir.mkdir(parents=True)
        self._orig = (library_tools.library_root_for, library_tools.SMART_RULES_PATH,
                      library_tools.WATCH_STATE_PATH, library_tools.EXPORTS_DIR, journal.JOURNAL_PATH)
        library_tools.library_root_for = lambda _s: self.root
        library_tools.SMART_RULES_PATH = self.tmp / "smart.json"
        library_tools.WATCH_STATE_PATH = self.tmp / "watch.json"
        library_tools.EXPORTS_DIR = self.tmp / "exports"
        journal.JOURNAL_PATH = self.tmp / "journal.sqlite"

    def tearDown(self):
        (library_tools.library_root_for, library_tools.SMART_RULES_PATH,
         library_tools.WATCH_STATE_PATH, library_tools.EXPORTS_DIR, journal.JOURNAL_PATH) = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _track(self, name, bpm=None, key=None, freq=440):
        p = self.mp3_dir / name
        _make_mp3(p, seconds=60, freq=freq)
        if bpm is not None or key is not None:
            tags = ID3(str(p))
            if bpm is not None:
                tags.add(TBPM(encoding=3, text=str(bpm)))
            if key is not None:
                tags.add(TKEY(encoding=3, text=key))
            tags.save(str(p), v2_version=3)
        return p

    def test_crate_reference_check_finds_missing_tracks(self):
        ok = self._track("ok.mp3")
        ausente = self.mp3_dir / "sumiu.mp3"
        export_matched_to_serato_crate("Teste", [
            {"caminho_rel": str(ok.relative_to(self.root))},
            {"caminho_rel": str(ausente.relative_to(self.root))},
        ], str(self.serato))
        res = library_tools.check_crate_references(self.serato)
        self.assertEqual(res["referencias_quebradas"], 1)
        self.assertEqual(res["crates"][0]["faltando"], 1)

    def test_m3u_export_then_import_keeps_existing_tracks_only(self):
        a = self._track("a.mp3")
        b = self._track("b.mp3")
        export_matched_to_serato_crate("Origem", [
            {"caminho_rel": str(a.relative_to(self.root))},
            {"caminho_rel": str(b.relative_to(self.root))},
        ], str(self.serato))
        exp = library_tools.export_crate_m3u(self.serato, "Origem.crate")
        self.assertTrue(exp["sucesso"], exp)
        self.assertEqual(exp["total"], 2)

        m3u = Path(exp["arquivo"])
        m3u.write_text(m3u.read_text(encoding="utf-8") + "/tmp/fora_da_biblioteca.mp3\n", encoding="utf-8")
        imp = library_tools.import_m3u_as_crate(self.serato, str(m3u), "Importada")
        self.assertTrue(imp["sucesso"], imp)
        self.assertEqual(imp["total_faixas"], 2)
        self.assertEqual(imp["ignoradas"], 1)

    def test_smart_crate_filters_by_bpm_key_and_saves_rule(self):
        self._track("c1.mp3", bpm=121, key="8B")
        self._track("c2.mp3", bpm=121, key="8A")
        self._track("c3.mp3", bpm=140, key="8B")
        self._track("c4.mp3", bpm=122, key="C major")
        regras = {"bpm_min": 118, "bpm_max": 124, "camelot": ["8B"]}
        dry = library_tools.create_smart_crate(self.mp3_dir, self.serato, "Dança", regras, dry_run=True)
        self.assertEqual(dry["total"], 2, dry)  # c1 e c4 ("C major" = 8B)

        real = library_tools.create_smart_crate(self.mp3_dir, self.serato, "Dança", regras)
        self.assertTrue(real["sucesso"], real)
        self.assertEqual(real["total_faixas"], 2)
        self.assertEqual(library_tools.list_smart_crates()["items"][0]["nome"], "Dança")

    def test_health_counts_missing_metadata(self):
        self._track("com.mp3", bpm=120, key="8A")
        self._track("sem.mp3")
        res = library_tools.library_health(self.mp3_dir)
        self.assertEqual(res["total_faixas"], 2)
        self.assertEqual(res["sem_bpm"], 1)
        self.assertEqual(res["sem_tom"], 1)

    def test_scan_new_files_baseline_then_detects_new(self):
        self._track("antigo.mp3")
        base = library_tools.scan_new_files(self.mp3_dir)
        self.assertTrue(base["linha_base"])
        self._track("novo.mp3")
        depois = library_tools.scan_new_files(self.mp3_dir)
        self.assertFalse(depois["linha_base"])
        self.assertEqual(depois["total_novos"], 1)
        self.assertEqual(depois["novos"][0]["nome"], "novo.mp3")


class TestKeyNameConversion(unittest.TestCase):

    def test_musical_names_map_to_camelot(self):
        self.assertEqual(library_tools._normalize_key_to_camelot("C major"), "8B")
        self.assertEqual(library_tools._normalize_key_to_camelot("A minor"), "8A")
        self.assertEqual(library_tools._normalize_key_to_camelot("11b"), "11B")
        self.assertEqual(library_tools._normalize_key_to_camelot("H#"), "")


if __name__ == "__main__":
    unittest.main()
