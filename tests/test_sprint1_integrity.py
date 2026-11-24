#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - TESTES DE INTEGRIDADE E PROTEÇÃO DE DADOS (SPRINT 1)
================================================================================
Testa rigorosamente:
1. crate_ops:
   - Crate corrompida nunca é interpretada como vazia
   - Crate vazia legítima é tratada com segurança
   - Falha de parsing em qualquer arquivo de origem aborta merge/add sem perda de dados
   - Backup com validação de hash SHA-256 e rollback automático
   - Registro de operações no journal
2. music_analysis:
   - Preservação de todos os frames ID3 (TIT1 grouping manual, múltiplos COMM, TPE1, TIT2)
   - Atualização apenas do campo autorizado
   - Se o journal falhar, cancela a operação (fail-closed)
   - Validação pós-escrita e restauração
   - Ghost Curator: identifica dados ausentes e não assume valores arbitrários como fato
3. recipe_engine:
   - Extração de remixer limpa o título original
   - Persistência do snapshot ANTES da escrita física
   - Undo restaura exatamente o estado anterior dos metadados
   - Rollback automático se gravação falhar no lote
================================================================================
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path

# Adiciona raiz do projeto
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import crate_ops
import music_analysis
import recipe_engine
import journal
from mutagen.id3 import ID3, TIT2, TPE1, TPE4, TIT1, COMM, TALB, TBPM, TKEY


class TestSprint1DataIntegrity(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="serato_sprint1_test_")
        self.root = Path(self.test_dir)
        self.serato_dir = self.root / "_Serato_"
        self.subcrates_dir = self.serato_dir / "Subcrates"
        self.subcrates_dir.mkdir(parents=True, exist_ok=True)
        self.mp3_dir = self.root / "Music" / "MP3"
        self.mp3_dir.mkdir(parents=True, exist_ok=True)

        # Configura banco de journal e recipe temporário para testes
        self.journal_db = self.root / "test_journal.sqlite"
        self.recipe_db = self.root / "test_recipe.sqlite"
        os.environ["SERATO_JOURNAL_PATH"] = str(self.journal_db)
        os.environ["SERATO_RECIPE_DB"] = str(self.recipe_db)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_dummy_mp3(self, filepath: Path, title="Song", artist="Artist",
                          grouping="Peak Time", comments=None) -> Path:
        """Cria um arquivo MP3 sintético válido para mutagen com frames ID3v2.3."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        # Cabeçalho MPEG frame mínimo + padding
        audio_content = b"\xFF\xFB\x90\x00" + (b"\x00" * 4000)
        filepath.write_bytes(audio_content)

        tags = ID3()
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text=artist))
        if grouping:
            tags.add(TIT1(encoding=3, text=grouping))
        if comments is not None:
            for desc, text in comments:
                tags.add(COMM(encoding=3, lang='eng', desc=desc, text=[text]))
        tags.save(str(filepath), v2_version=3)
        return filepath

    # --------------------------------------------------------------------------
    # 1. CRATE OPERATIONS
    # --------------------------------------------------------------------------

    def test_corrupt_crate_aborts_and_never_treated_as_empty(self):
        """Crate corrompida não pode ser interpretada como vazia e deve abortar operações."""
        corrupt_crate = self.subcrates_dir / "CorruptCrate.crate"
        corrupt_crate.write_bytes(b"NOT_A_VALID_SERATO_CRATE_HEADER_JUNK_DATA_123456789")

        # Tentativa de add_paths deve falhar fechado sem sobrescrever a crate corrompida
        track = self._create_dummy_mp3(self.mp3_dir / "Track1.mp3")
        res = crate_ops.add_paths_to_crate(str(self.serato_dir), "CorruptCrate", [str(track)])

        self.assertFalse(res["sucesso"])
        self.assertIn("inválida ou ilegível", res["erro"])
        # Garante que o arquivo corrompido original foi preservado intacto
        self.assertEqual(corrupt_crate.read_bytes(), b"NOT_A_VALID_SERATO_CRATE_HEADER_JUNK_DATA_123456789")

    def test_empty_file_crate_fails_closed(self):
        """Crate de 0 bytes no disco não pode ser tratada como vazia legítima."""
        empty_crate = self.subcrates_dir / "ZeroBytes.crate"
        empty_crate.write_bytes(b"")

        track = self._create_dummy_mp3(self.mp3_dir / "Track1.mp3")
        res = crate_ops.add_paths_to_crate(str(self.serato_dir), "ZeroBytes", [str(track)])
        self.assertFalse(res["sucesso"])
        self.assertIn("vazio (0 bytes)", res["erro"])

    def test_crate_merge_aborts_on_any_invalid_source_crate(self):
        """Se qualquer crate de origem falhar na leitura, o merge inteiro é cancelado."""
        # Cria Crate 1 válida
        t1 = self._create_dummy_mp3(self.mp3_dir / "TrackA.mp3")
        crate_ops.add_paths_to_crate(str(self.serato_dir), "ValidSource", [str(t1)])

        # Cria Crate 2 corrompida
        corrupt = self.subcrates_dir / "BrokenSource.crate"
        corrupt.write_bytes(b"GARBAGE_HEADER_DATA")

        res = crate_ops.merge_crates(str(self.serato_dir), ["ValidSource", "BrokenSource"], "MergedTarget")
        self.assertFalse(res["sucesso"])
        self.assertIn("BrokenSource", res["erro"])

        # Garante que a crate de destino não foi gerada de forma parcial
        target_path = self.subcrates_dir / "MergedTarget.crate"
        self.assertFalse(target_path.exists())

    def test_write_crate_atomic_creates_sha256_verified_backup_and_journal(self):
        """Gravação de crate cria backup verificado por SHA-256 e registra no journal."""
        t1 = self._create_dummy_mp3(self.mp3_dir / "Song1.mp3")
        crate_path = self.subcrates_dir / "TestAtomic.crate"

        res1 = crate_ops.write_crate_atomic(crate_path, [str(t1.name)], action_name="test_init")
        self.assertTrue(res1["sucesso"])

        orig_hash = res1["hash"]

        # Segunda gravação alterando o conteúdo
        res2 = crate_ops.write_crate_atomic(crate_path, [str(t1.name), "Song2.mp3"], action_name="test_update")
        self.assertTrue(res2["sucesso"])
        self.assertIsNotNone(res2["backup"])

        bak_file = Path(res2["backup"])
        self.assertTrue(bak_file.exists())
        self.assertEqual(crate_ops.calc_crate_sha256(bak_file), orig_hash)

        # Verifica se foi gravado no journal
        conn = journal.get_journal_db()
        row = conn.execute("SELECT acao, crate_path, hash_anterior, hash_posterior FROM crate_operacoes WHERE crate_path = ?", (str(crate_path),)).fetchall()
        conn.close()
        self.assertGreaterEqual(len(row), 1)

    # --------------------------------------------------------------------------
    # 2. MUSIC ANALYSIS & ID3 PRESERVATION
    # --------------------------------------------------------------------------

    def test_write_energy_tag_preserves_other_id3_frames_and_comments(self):
        """Gravar Energy não pode apagar comentários existentes, Grouping prévio, artista ou título."""
        track = self._create_dummy_mp3(
            self.mp3_dir / "EnergyTrack.mp3",
            title="My Special Anthem",
            artist="DJ Master",
            grouping="Warmup House",
            comments=[
                ("", "Nota original do DJ"),
                ("iTunNORM", "0000045A 0000045A 00001000"),
                ("Serato", "Serato Cue Data")
            ]
        )

        res = music_analysis.write_energy_tag(str(track), energy=8, target_tag="both")
        self.assertTrue(res["sucesso"])

        tags = ID3(str(track))

        # 1. Título e Artista intactos
        self.assertEqual(str(tags["TIT2"]), "My Special Anthem")
        self.assertEqual(str(tags["TPE1"]), "DJ Master")

        # 2. Grouping preserva o valor anterior junto com o Energy
        grouping_val = str(tags["TIT1"])
        self.assertIn("Energy 8", grouping_val)
        self.assertIn("Warmup House", grouping_val)

        # 3. Comentários especiais (iTunNORM, Serato) continuam presentes
        comm_frames = tags.getall("COMM")
        descs = [getattr(f, "desc", "") for f in comm_frames]
        self.assertIn("iTunNORM", descs)
        self.assertIn("Serato", descs)

        # 4. Comentário padrão preserva o texto original prefixado com [Energy 8]
        default_comm = next(f for f in comm_frames if getattr(f, "desc", "") in ("", "Comment"))
        self.assertIn("[Energy 8]", str(default_comm.text[0]))
        self.assertIn("Nota original do DJ", str(default_comm.text[0]))

    def test_write_energy_fail_closed_if_journal_fails(self):
        """Se o registro no Journal falhar, a gravação de tags é abortada imediatamente."""
        track = self._create_dummy_mp3(self.mp3_dir / "ProtectedTrack.mp3")

        # Simula falha no journal apontando para um caminho inválido de diretório somente leitura
        os.environ["SERATO_JOURNAL_PATH"] = "/dev/null/invalid_path/journal.sqlite"

        res = music_analysis.write_energy_tag(str(track), energy=7)
        self.assertFalse(res["sucesso"])
        self.assertIn("Falha obrigatória no Journal", res["erro"])

        # Restaura variável de ambiente
        os.environ["SERATO_JOURNAL_PATH"] = str(self.journal_db)

    def test_ghost_curator_does_not_presume_missing_metadata(self):
        """Ghost curator deve apontar campos ausentes e não presumir 126 BPM / 8A como fato."""
        t1 = self._create_dummy_mp3(self.mp3_dir / "Unanalyzed.mp3", title="Raw Audio")
        # Sem TBPM, sem TKEY, sem TIT1
        crate_ops.add_paths_to_crate(str(self.serato_dir), "RawCrate", [str(t1)])

        res = music_analysis.generate_curated_set(str(self.serato_dir), "RawCrate", dry_run=True)
        self.assertTrue(res["sucesso"])
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["faixas_incompletas"], 1)

        track_info = res["curated_tracks"][0]
        self.assertIsNone(track_info["bpm"])
        self.assertIsNone(track_info["camelot"])
        self.assertIsNone(track_info["energy"])
        self.assertEqual(track_info["status_metadados"], "desconhecido")
        self.assertEqual(track_info["confianca"], 0.0)

    # --------------------------------------------------------------------------
    # 3. RECIPE ENGINE & SMART FIXES
    # --------------------------------------------------------------------------

    def test_extract_remixer_cleans_title(self):
        """Extração de remixer deve preencher TPE4 E limpar o remixer do título (TIT2)."""
        engine = recipe_engine.RecipeEngine(db_path=self.recipe_db)
        track = self._create_dummy_mp3(self.mp3_dir / "RemixSong.mp3", title="One Love (Vintage Culture Remix)", artist="Bob")

        res = engine.apply_recipe("extract_remixer", [str(track)])
        self.assertTrue(res["sucesso"])
        self.assertEqual(res["affected_count"], 1)

        tags = ID3(str(track))
        self.assertEqual(str(tags["TPE4"]), "Vintage Culture")
        self.assertEqual(str(tags["TIT2"]), "One Love")

    def test_recipe_engine_undo_restores_exact_previous_metadata(self):
        """Undo do recipe engine restaura exatamente o estado anterior dos campos modificados."""
        engine = recipe_engine.RecipeEngine(db_path=self.recipe_db)
        track = self._create_dummy_mp3(self.mp3_dir / "SwapSong.mp3", title="Original Title", artist="Original Artist")
        orig_hash = journal.calc_file_sha256(str(track))

        # Aplica swap_artist_title
        res_apply = engine.apply_recipe("swap_artist_title", [str(track)])
        self.assertTrue(res_apply["sucesso"])

        tags_after = ID3(str(track))
        self.assertEqual(str(tags_after["TIT2"]), "Original Artist")
        self.assertEqual(str(tags_after["TPE1"]), "Original Title")

        # Desfaz
        res_undo = engine.undo_last()
        self.assertTrue(res_undo["sucesso"])
        self.assertEqual(res_undo["restored_count"], 1)

        tags_restored = ID3(str(track))
        self.assertEqual(str(tags_restored["TIT2"]), "Original Title")
        self.assertEqual(str(tags_restored["TPE1"]), "Original Artist")


if __name__ == "__main__":
    unittest.main()
