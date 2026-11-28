#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
TESTES DE REGRESSÃO E COMPROVAÇÃO DE AUDITORIA (test_audit_remediations.py)
================================================================================
Cobre rigorosamente todos os achados críticos e altos do Relatório Final de Auditoria:
  - C1: sound_seal.py (Volume montado, limite 20%, backup, atomicidade)
  - C2: tag_doctor.py (Escrita atômica em temp, validação, integridade do original, sucesso: False)
  - C3/H3/M2: crate_ops.py (Backup verificado, gravação temporária, validação estrutural)
  - H1: journal.py (Undo ordenado, verificação de hash, bloqueio fora de ordem)
  - H2/H4: auto_cue.py (Silencedetect com -v info, backup verificado antes de modificação)
  - L2: Travessia de diretório com '../'
================================================================================
"""

import os
import sys
import json
import shutil
import tempfile
import struct
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import sound_seal
import tag_doctor
import crate_ops
import journal
import auto_cue
import audio_health
from serato_macos_app import criar_tag_tlv, parse_crate_binary


class TestAuditRemediations(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="remediation_test_")
        self.root_path = Path(self.test_dir)
        self.mp3_dir = self.root_path / "Music" / "MP3"
        self.serato_dir = self.root_path / "_Serato_"
        self.subcrates_dir = self.serato_dir / "Subcrates"

        self.mp3_dir.mkdir(parents=True, exist_ok=True)
        self.serato_dir.mkdir(parents=True, exist_ok=True)
        self.subcrates_dir.mkdir(parents=True, exist_ok=True)

        # Redireciona bancos para ambiente temporário isolado
        self._orig_journal = journal.JOURNAL_PATH
        journal.JOURNAL_PATH = self.root_path / "test_journal.sqlite"

        self._orig_cue_backup_db = auto_cue.BACKUP_DB_PATH
        auto_cue.BACKUP_DB_PATH = self.root_path / "test_cues_backup.sqlite"

        self._orig_sound_seal_db = sound_seal.DB_PATH
        sound_seal.DB_PATH = self.root_path / "test_sound_seals.sqlite"

    def tearDown(self):
        journal.JOURNAL_PATH = self._orig_journal
        auto_cue.BACKUP_DB_PATH = self._orig_cue_backup_db
        sound_seal.DB_PATH = self._orig_sound_seal_db
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_synthetic_mp3(self, path: Path, title: str = "Test Title", artist: str = "Test Artist") -> Path:
        """Cria MP3 sintético válido com ID3v2.3 e frames MPEG sincronizados para mutagen."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tag_data = f"TIT2\x00\x00\x00{chr(len(title)+1)}\x00\x00\x03{title}".encode('latin1')
        tag_data += f"TPE1\x00\x00\x00{chr(len(artist)+1)}\x00\x00\x03{artist}".encode('latin1')
        tag_len = len(tag_data)
        synch_len = bytes([
            (tag_len >> 21) & 0x7F,
            (tag_len >> 14) & 0x7F,
            (tag_len >> 7) & 0x7F,
            tag_len & 0x7F
        ])
        header = b'ID3\x03\x00\x00' + synch_len + tag_data
        # MPEG 1 Layer 3, 128 kbps, 44100 Hz, frame size = 417 bytes
        frame = b'\xff\xfb\x90\x00' + b'\x00' * 413
        path.write_bytes(header + frame * 450)
        return path

    def _create_synthetic_crate(self, crate_file: Path, track_rel_paths: list) -> Path:
        """Gera binário oficial de .crate do Serato com lista de faixas."""
        content = bytearray(b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000')
        for rel in track_rel_paths:
            ptrk = criar_tag_tlv('ptrk', rel)
            otrk = b'otrk' + struct.pack('>I', len(ptrk)) + ptrk
            content.extend(otrk)
        crate_file.write_bytes(bytes(content))
        return crate_file

    # =========================================================================
    # C1 — sound_seal.py: Remoção de faixas sem verificar volume montado
    # =========================================================================

    def test_c1_unmounted_volume_tracks_are_never_removed(self):
        """C1: Faixas cujo volume externo está desconectado NUNCA são removidas."""
        crate_file = self.subcrates_dir / "TestCrate.crate"
        # 1 faixa em volume desconectado, 1 faixa local que existe
        local_track = self.mp3_dir / "Existing.mp3"
        self._create_synthetic_mp3(local_track)

        tracks = [
            "Volumes/NaoMontado/Music/a1.mp3",
            f"Music/MP3/{local_track.name}"
        ]
        self._create_synthetic_crate(crate_file, tracks)

        # Executa remoção global explícita de faixas perdidas
        res = sound_seal.remove_lost_tracks_from_crates(
            str(self.serato_dir),
            str(self.mp3_dir),
            allow_global_cleanup=True,
        )

        self.assertTrue(res["sucesso"])
        self.assertEqual(res["total_removidas"], 0, "Nenhuma faixa de volume desconectado deve ser removida")

        # Comprova que a crate continua com as 2 faixas intactas
        _, remaining, _, _ = parse_crate_binary(crate_file.read_bytes())
        self.assertEqual(len(remaining), 2)
        self.assertIn("Volumes/NaoMontado/Music/a1.mp3", remaining)

    def test_c1_mounted_volume_missing_file_is_removed_safely(self):
        """C1: Se o volume está montado e o arquivo inexiste, remove com backup e atomicidade."""
        crate_file = self.subcrates_dir / "MountedCrate.crate"

        # Cria 5 faixas existentes e 1 ausente no disco local (1/6 = 16.6% <= 20% teto)
        existing_tracks = []
        for i in range(5):
            t = self.mp3_dir / f"Track_{i}.mp3"
            self._create_synthetic_mp3(t)
            existing_tracks.append(f"Music/MP3/Track_{i}.mp3")

        all_tracks = existing_tracks + ["Music/MP3/MissingTrack.mp3"]
        self._create_synthetic_crate(crate_file, all_tracks)

        res = sound_seal.remove_lost_tracks_from_crates(
            str(self.serato_dir),
            str(self.mp3_dir),
            allow_global_cleanup=True,
        )

        self.assertTrue(res["sucesso"])
        self.assertEqual(res["total_removidas"], 1)

        # Comprova criação do backup verificado .bak
        bak_file = crate_file.with_suffix('.crate.bak')
        self.assertTrue(bak_file.exists())
        self.assertEqual(len(parse_crate_binary(bak_file.read_bytes())[1]), 6)

        # Comprova que a crate atualizada tem exatamente 5 faixas (a ausente foi removida)
        _, remaining, _, _ = parse_crate_binary(crate_file.read_bytes())
        self.assertEqual(len(remaining), 5)
        self.assertNotIn("Music/MP3/MissingTrack.mp3", remaining)

    def test_c1_high_percentage_missing_tracks_triggers_safety_block(self):
        """C1: Percentual elevado de faixas ausentes (> 20%) bloqueia remoção por segurança."""
        crate_file = self.subcrates_dir / "DangerCrate.crate"
        # 1 existente, 2 ausentes (2/3 = 66.6% > 20%)
        t = self.mp3_dir / "Safe.mp3"
        self._create_synthetic_mp3(t)

        tracks = [
            f"Music/MP3/{t.name}",
            "Music/MP3/Missing1.mp3",
            "Music/MP3/Missing2.mp3"
        ]
        self._create_synthetic_crate(crate_file, tracks)

        res = sound_seal.remove_lost_tracks_from_crates(
            str(self.serato_dir),
            str(self.mp3_dir),
            allow_global_cleanup=True,
        )

        self.assertTrue(res["sucesso"])
        self.assertEqual(res["total_removidas"], 0)

        # Comprova que foi bloqueado por segurança
        affected = res["crates_afetadas"]
        self.assertEqual(len(affected), 1)
        self.assertTrue(affected[0].get("bloqueado_seguranca"))
        self.assertIn("excede o teto de segurança", affected[0]["motivo"])

        # Crate física intacta
        _, remaining, _, _ = parse_crate_binary(crate_file.read_bytes())
        self.assertEqual(len(remaining), 3)

    def test_c1_database_v2_unmounted_and_percentage_protection(self):
        """C1: database V2 respeita checagem de volume montado e teto percentual."""
        db_file = self.serato_dir / "database V2"
        # Cria cabeçalho dummy de 72 bytes + 2 blocos de faixas
        header = b"vrsn\x00\x00\x00\x081.0/Database" + b"\x00" * 52
        pfil1 = criar_tag_tlv('pfil', 'Volumes/NaoMontado/Music/song1.mp3')
        block1 = b'otrk' + struct.pack('>I', len(pfil1)) + pfil1
        pfil2 = criar_tag_tlv('pfil', 'Music/MP3/MissingLocal.mp3')
        block2 = b'otrk' + struct.pack('>I', len(pfil2)) + pfil2

        db_file.write_bytes(header + block1 + block2)

        # 1/2 ausente localmente = 50% > 20% teto: remoção deve ser bloqueada
        removed = sound_seal.remove_from_database_v2(db_file, mp3_base=self.mp3_dir)
        self.assertEqual(removed, 0)
        self.assertTrue(db_file.exists())

    # =========================================================================
    # C2 — tag_doctor.py: Escrita parcial com sucesso falso
    # =========================================================================

    def test_c2_io_failure_during_save_preserves_original_and_returns_failure(self):
        """C2: Falha durante audio.save não corrompe o arquivo e retorna sucesso: False."""
        track = self._create_synthetic_mp3(self.mp3_dir / "RobustTrack.mp3")
        orig_bytes = track.read_bytes()
        orig_hash = journal.calc_file_sha256(str(track))

        from mutagen.mp3 import MP3

        # Injeta erro OSError no save do mutagen
        real_save = MP3.save
        def failing_save(*args, **kwargs):
            raise OSError("Simulated Disk Full / I/O Error during ID3 save")

        items = [{
            "caminho": str(track),
            "titulo_sugerido": "New Title",
            "artista_sugerido": "New Artist"
        }]

        with patch.object(MP3, "save", side_effect=failing_save):
            res = tag_doctor.apply_cleaned_tags(items, stream_progress=False)

        # Retorno DEVE ser sucesso: False
        self.assertFalse(res["sucesso"], "sucesso deve ser False quando ocorrer erro de gravação")
        self.assertEqual(res["atualizados"], 0)
        self.assertGreater(len(res["erros"]), 0)

        # Arquivo original DEVE estar 100% íntegro e idêntico byte a byte
        self.assertTrue(track.exists())
        self.assertEqual(track.read_bytes(), orig_bytes)
        self.assertEqual(journal.calc_file_sha256(str(track)), orig_hash)

        # Arquivo permanece perfeitamente legível pelo mutagen
        audio_check = MP3(str(track))
        self.assertIsNotNone(audio_check)

    def test_c2_validation_failure_aborts_without_modifying_original(self):
        """C2: Se a validação pós-escrita falhar, o original não é substituído."""
        track = self._create_synthetic_mp3(self.mp3_dir / "ValidationTrack.mp3")
        orig_bytes = track.read_bytes()

        items = [{"caminho": str(track), "titulo_sugerido": "Valid Title"}]

        # Simula mutagen retornando None ao reabrir o arquivo temporário
        real_mutagen_file = tag_doctor.mutagen.File
        call_count = 0
        def mocked_mutagen_file(filename, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if ".tmp_tag_" in filename and call_count > 1:
                return None # Simula arquivo corrompido pós-escrita
            return real_mutagen_file(filename, *args, **kwargs)

        with patch("tag_doctor.mutagen.File", side_effect=mocked_mutagen_file):
            res = tag_doctor.apply_cleaned_tags(items, stream_progress=False)

        self.assertFalse(res["sucesso"])
        self.assertEqual(track.read_bytes(), orig_bytes)

    # =========================================================================
    # C3 / H3 / M2 — crate_ops.py: Backup verificável e escrita temporária atômica
    # =========================================================================

    def test_c3_backup_failure_aborts_without_modifying_crate(self):
        """C3: Falha na criação do backup impede qualquer alteração na crate."""
        crate_file = self.subcrates_dir / "BackupTest.crate"
        t1 = self.mp3_dir / "Track1.mp3"
        self._create_synthetic_mp3(t1)
        self._create_synthetic_crate(crate_file, [f"Music/MP3/{t1.name}"])
        orig_bytes = crate_file.read_bytes()

        t2 = self.mp3_dir / "Track2.mp3"
        self._create_synthetic_mp3(t2)

        # Injeta falha em shutil.copy2
        with patch("shutil.copy2", side_effect=PermissionError("Permission Denied on .bak")):
            res = crate_ops.add_paths_to_crate(
                str(self.serato_dir),
                "BackupTest",
                [str(t2)]
            )

        self.assertFalse(res["sucesso"])
        self.assertIn("backup", res["erro"].lower())
        self.assertEqual(crate_file.read_bytes(), orig_bytes)

    def test_c3_structural_validation_failure_preserves_original(self):
        """C3/H3: Se o temporário falhar na validação estrutural, a crate original permanece intocada."""
        crate_file = self.subcrates_dir / "StructTest.crate"
        t1 = self.mp3_dir / "Track1.mp3"
        self._create_synthetic_mp3(t1)
        self._create_synthetic_crate(crate_file, [f"Music/MP3/{t1.name}"])
        orig_bytes = crate_file.read_bytes()

        t2 = self.mp3_dir / "Track2.mp3"
        self._create_synthetic_mp3(t2)

        # Simula parser retornando divergência de contagem
        real_parse = crate_ops.parse_crate_binary
        def corrupted_parse(data):
            hdr, tracks, otrk, outros = real_parse(data)
            return hdr, [], otrk, outros # Simula 0 faixas detectadas

        with patch("crate_ops.parse_crate_binary", side_effect=corrupted_parse):
            res = crate_ops.add_paths_to_crate(
                str(self.serato_dir),
                "StructTest",
                [str(t2)]
            )

        self.assertFalse(res["sucesso"])
        self.assertEqual(crate_file.read_bytes(), orig_bytes)

    def test_m2_overwrite_traceability(self):
        """M2: Regravação de crate existente relata sobrescrita e caminho do backup."""
        crate_file = self.subcrates_dir / "TraceTest.crate"
        t1 = self.mp3_dir / "Track1.mp3"
        self._create_synthetic_mp3(t1)
        self._create_synthetic_crate(crate_file, [f"Music/MP3/{t1.name}"])

        t2 = self.mp3_dir / "Track2.mp3"
        self._create_synthetic_mp3(t2)

        res = crate_ops.add_paths_to_crate(
            str(self.serato_dir),
            "TraceTest",
            [str(t2)]
        )

        self.assertTrue(res["sucesso"])
        self.assertTrue(res["sobrescrita"])
        self.assertIsNotNone(res["backup"])
        self.assertTrue(Path(res["backup"]).exists())

    # =========================================================================
    # H1 — journal.py: Undo apaga a alteração mais nova
    # =========================================================================

    def test_h1_undo_normal(self):
        """H1: Undo normal restaura com precisão o estado anterior."""
        mp3 = self._create_synthetic_mp3(self.mp3_dir / "UndoFaixa.mp3", title="Original Title")
        orig_hash = journal.calc_file_sha256(str(mp3))

        # Aplica alteração via tag_doctor
        items = [{"caminho": str(mp3), "titulo_sugerido": "Modified Title"}]
        res = tag_doctor.apply_cleaned_tags(items, stream_progress=False)
        self.assertTrue(res["sucesso"])
        self.assertNotEqual(journal.calc_file_sha256(str(mp3)), orig_hash)

        # Executa Undo
        undo_res = journal.undo_operation()
        self.assertTrue(undo_res["sucesso"])
        self.assertEqual(journal.calc_file_sha256(str(mp3)), orig_hash)

    def test_h1_undo_refused_if_file_externally_modified(self):
        """H1: Undo é recusado se o arquivo foi modificado externamente após a operação."""
        mp3 = self._create_synthetic_mp3(self.mp3_dir / "ExtModified.mp3", title="Original")
        items = [{"caminho": str(mp3), "titulo_sugerido": "First Mod"}]
        tag_doctor.apply_cleaned_tags(items, stream_progress=False)

        # Modificação externa simulada (ex: outro app ou DJ alterou o arquivo)
        with open(mp3, "ab") as f:
            f.write(b"EXTERNAL_MODIFICATION_BYTES")

        undo_res = journal.undo_operation()
        self.assertFalse(undo_res["sucesso"])
        self.assertIn("modificado externamente", undo_res["erro"])

    def test_h1_successive_operations_and_out_of_order_refusal(self):
        """H1: Duas operações sucessivas no mesmo arquivo; undo fora de ordem é bloqueado."""
        mp3 = self._create_synthetic_mp3(self.mp3_dir / "Successive.mp3", title="State 0")
        h0 = journal.calc_file_sha256(str(mp3))

        # Operação 1
        tag_doctor.apply_cleaned_tags([{"caminho": str(mp3), "titulo_sugerido": "State 1"}], stream_progress=False)
        h1 = journal.calc_file_sha256(str(mp3))
        ops = journal.list_operations()["items"]
        op1_id = ops[0]["id"]

        # Operação 2
        tag_doctor.apply_cleaned_tags([{"caminho": str(mp3), "titulo_sugerido": "State 2"}], stream_progress=False)
        h2 = journal.calc_file_sha256(str(mp3))
        ops = journal.list_operations()["items"]
        op2_id = ops[0]["id"]

        self.assertNotEqual(op1_id, op2_id)

        # Tentativa de desfazer Operação 1 diretamente (fora de ordem enquanto op 2 está ativa)
        out_of_order_res = journal.undo_operation(op_id=op1_id)
        self.assertFalse(out_of_order_res["sucesso"])
        self.assertIn("fora de ordem", out_of_order_res["erro"])
        # Garante que State 2 NÃO foi sobrescrito
        self.assertEqual(journal.calc_file_sha256(str(mp3)), h2)

        # Desfaz na ordem correta: primeiro Op 2
        undo2 = journal.undo_operation(op_id=op2_id)
        self.assertTrue(undo2["sucesso"])
        self.assertEqual(journal.calc_file_sha256(str(mp3)), h1)

        # Depois desfaz Op 1
        undo1 = journal.undo_operation(op_id=op1_id)
        self.assertTrue(undo1["sucesso"])
        self.assertEqual(journal.calc_file_sha256(str(mp3)), h0)

    # =========================================================================
    # H2 — auto_cue.py: Detecção real de transientes/onsets e confiança
    # =========================================================================

    def _pcm_bytes_from_frames(self, frame_amplitudes):
        """Gera PCM s16le a 10kHz (100 amostras = 10 ms por quadro)."""
        import struct
        buf = bytearray()
        for amp in frame_amplitudes:
            sample = max(-32767, min(32767, int(amp)))
            buf.extend(struct.pack("<h", sample) * 100)
        return bytes(buf)

    def test_h2_silencedetect_captures_initial_silence_with_v_info(self):
        """H2: Detecta silêncio inicial seguido de onset real e reporta confiavel=True."""
        # 145 quadros (1450 ms) em silêncio + ataque forte (amp 12000)
        pcm = self._pcm_bytes_from_frames([0] * 145 + [12000] * 55)
        mock_proc = MagicMock(returncode=0, stdout=pcm, stderr=b"")

        track = self._create_synthetic_mp3(self.mp3_dir / "onset_1450.mp3")
        with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
             patch("subprocess.run", return_value=mock_proc):
            res = auto_cue.detect_audio_transients(str(track), duration_sec=100.0)

        self.assertTrue(res["has_transient"])
        self.assertTrue(res["confiavel"])
        self.assertEqual(res["first_beat_ms"], 1450)
        self.assertEqual(res["silence_end_ms"], 1450)

    def test_h2_continuous_silence_reports_no_transient_without_blind_fallback(self):
        """H2: Arquivo em silêncio contínuo reporta has_transient=False, confiavel=False e first_beat_ms=None."""
        pcm = self._pcm_bytes_from_frames([0] * 300)
        mock_proc = MagicMock(returncode=0, stdout=pcm, stderr=b"")

        track = self._create_synthetic_mp3(self.mp3_dir / "silent.mp3")
        with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
             patch("subprocess.run", return_value=mock_proc):
            res = auto_cue.detect_audio_transients(str(track), duration_sec=100.0)

        self.assertFalse(res["has_transient"])
        self.assertFalse(res["confiavel"])
        self.assertIsNone(res["first_beat_ms"])

    def test_h2_audio_without_initial_silence(self):
        """H2: Áudio com ataque forte imediato no quadro 0 detecta transiente confiável."""
        pcm = self._pcm_bytes_from_frames([12000] * 200)
        mock_proc = MagicMock(returncode=0, stdout=pcm, stderr=b"")

        track = self._create_synthetic_mp3(self.mp3_dir / "immediate.mp3")
        with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
             patch("subprocess.run", return_value=mock_proc):
            res = auto_cue.detect_audio_transients(str(track), duration_sec=100.0)

        self.assertTrue(res["has_transient"])
        self.assertTrue(res["confiavel"])
        self.assertEqual(res["first_beat_ms"], 100)

    def test_h2_invalid_audio_returns_unreliable(self):
        """H2: Arquivo inválido ou falha de ffmpeg reporta has_transient=False e confiavel=False."""
        mock_proc = MagicMock(returncode=1, stdout=b"", stderr=b"Invalid data found when processing input\n")

        track = self._create_synthetic_mp3(self.mp3_dir / "corrupt.mp3")
        with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
             patch("subprocess.run", return_value=mock_proc):
            res = auto_cue.detect_audio_transients(str(track), duration_sec=100.0)

        self.assertFalse(res["has_transient"])
        self.assertFalse(res["confiavel"])
        self.assertIsNone(res["first_beat_ms"])

    # =========================================================================
    # H4 — auto_cue.py: Restore de cues e bloqueio se backup falhar
    # =========================================================================

    def test_h4_backup_failure_completely_aborts_cue_modification(self):
        """H4: Se o backup falhar, nenhuma modificação de cues é realizada."""
        track = self._create_synthetic_mp3(self.mp3_dir / "BackupFailTrack.mp3")
        orig_bytes = track.read_bytes()

        # Injeta falha no banco de backup (com transiente confiável)
        reliable = {"first_beat_ms": 500, "has_transient": True, "confiavel": True, "confianca": 0.9, "motivo": "onset_detectado"}
        with patch("auto_cue.detect_audio_transients", return_value=reliable), \
             patch("auto_cue.backup_track_cues", return_value=False):
            res = auto_cue.generate_and_save_serato_cues(str(track), overwrite_existing=True)

        self.assertFalse(res["sucesso"])
        self.assertIn("backup", res["erro"].lower())
        self.assertEqual(track.read_bytes(), orig_bytes)

    def test_h4_track_without_tags_backs_up_and_restores_clean_state(self):
        """H4: Faixa sem tags prévias salva estado vazio e restore apaga os cues adicionados."""
        from tests.fixtures.acoustic_fixtures import AcousticFixtureGenerator
        track = self.mp3_dir / "NoTagTrack.mp3"
        AcousticFixtureGenerator.generate_transient_audio(track, silence_sec=0.2, audio_sec=12.0)
        # Garante remoção de quaisquer tags ID3 geradas pelo muxer
        from mutagen.id3 import ID3, ID3NoHeaderError
        try:
            ID3(str(track)).delete(str(track))
        except ID3NoHeaderError:
            pass

        # Gera cues
        res = auto_cue.generate_and_save_serato_cues(str(track), overwrite_existing=True)
        self.assertTrue(res["sucesso"], res)

        id3_after = ID3(str(track))
        self.assertIn("GEOB:Serato Markers2", id3_after)

        # Restaura cues
        res_rest = auto_cue.restore_track_cues(str(track))
        self.assertTrue(res_rest["sucesso"])

        id3_restored = ID3(str(track))
        self.assertNotIn("GEOB:Serato Markers2", id3_restored)

    def test_h4_custom_dj_cues_are_preserved_and_restored(self):
        """H4: Cues manuais e personalizados de DJ são preservados e restaurados fielmente."""
        from tests.fixtures.acoustic_fixtures import AcousticFixtureGenerator
        track = self.mp3_dir / "CustomCueTrack.mp3"
        AcousticFixtureGenerator.create_tagged_transient_mp3(track, title="CustomCueTrack", duration_sec=13.0)

        # Insere marcador manual customizado
        custom_blob = b"\x01\x01CUSTOM_DJ_MARKERS2_DATA"
        from mutagen.id3 import ID3, GEOB
        id3 = ID3(str(track))
        id3.add(GEOB(encoding=0, mime="application/octet-stream", desc="Serato Markers2", data=custom_blob))
        id3.save(str(track), v2_version=3)

        # Sobrescreve com flag forçada
        res = auto_cue.generate_and_save_serato_cues(str(track), overwrite_existing=True)
        self.assertTrue(res["sucesso"], res)

        # Restaura e comprova integridade byte a byte do marcador customizado
        res_rest = auto_cue.restore_track_cues(str(track))
        self.assertTrue(res_rest["sucesso"])

        id3_rest = ID3(str(track))
        self.assertEqual(id3_rest["GEOB:Serato Markers2"].data, custom_blob)

    # =========================================================================
    # L2 — Impedir renomeações com '../' inseguro
    # =========================================================================

    def test_l2_relink_with_dot_dot_traversal_is_blocked(self):
        """L2: sound_seal.relink_track bloqueia caminhos com '../'."""
        src_track = self._create_synthetic_mp3(self.mp3_dir / "SourceTrack.mp3")
        res = sound_seal.relink_track(
            str(self.mp3_dir),
            "../../etc/malicious.mp3",
            str(src_track)
        )
        self.assertFalse(res["sucesso"])
        self.assertIn("Caminho inseguro", res["erro"])

    def test_l2_rename_audio_track_traversal_is_blocked(self):
        """L2: audio_health.rename_audio_track bloqueia '../' no nome de destino."""
        track = self._create_synthetic_mp3(self.mp3_dir / "TrackToRename.mp3")
        res = audio_health.rename_audio_track(str(track), "../../Escaped.mp3")
        self.assertFalse(res["sucesso"])
        self.assertIn("travessia de diretório", res["erro"])

    def test_l2_tag_doctor_rename_traversal_is_ignored(self):
        """L2: tag_doctor.apply_cleaned_tags ignora sugestão maliciosa com '../'."""
        track = self._create_synthetic_mp3(self.mp3_dir / "DocTrack.mp3")
        items = [{
            "caminho": str(track),
            "titulo_sugerido": "Clean Title",
            "arquivo_sugerido": "../../evil_escape.mp3"
        }]
        res = tag_doctor.apply_cleaned_tags(items, rename_files_on_disk=True, stream_progress=False)
        # O arquivo original não deve ter sido movido para fora da pasta
        self.assertTrue(track.exists())
        self.assertFalse((self.root_path / "evil_escape.mp3").exists())

    # =========================================================================
    # QA-04: Rollback físico se record_operation_after falhar + Undo bloqueado sem hash_post
    # =========================================================================

    def test_qa04_safe_save_tags_rolls_back_when_journal_after_fails(self):
        track = self._create_synthetic_mp3(self.mp3_dir / "RollbackAfterFail.mp3", title="OrigTitle")
        orig_bytes = track.read_bytes()

        with patch("journal.record_operation_after", side_effect=RuntimeError("Simulated Journal After Failure")):
            with self.assertRaises(IOError):
                tag_doctor.safe_save_tags(
                    track,
                    lambda audio: audio.tags.__setitem__("TIT2", tag_doctor.TIT2(encoding=3, text="NewTitle")),
                )

        # Arquivo restaurado integralmente ao estado original byte-a-byte
        self.assertEqual(track.read_bytes(), orig_bytes)

    def test_qa04_undo_refused_when_hash_posterior_missing(self):
        track = self._create_synthetic_mp3(self.mp3_dir / "NoPostHash.mp3", title="OrigTitle")
        op_id = journal.record_id3_before_change(str(track), action="manual_test")
        from mutagen.id3 import ID3, TIT2
        audio = ID3(str(track))
        audio["TIT2"] = TIT2(encoding=3, text="ChangedTitle")
        audio.save(str(track), v2_version=3)
        # Não chama record_operation_after -> hash_posterior permanece NULL/ausente

        res = journal.undo_operation(op_id)
        self.assertFalse(res["sucesso"])
        self.assertIn("hash posterior ausente", res["erro"])


if __name__ == "__main__":
    unittest.main()
