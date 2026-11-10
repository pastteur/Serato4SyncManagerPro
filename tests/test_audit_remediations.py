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

        # Executa remoção de faixas perdidas
        res = sound_seal.remove_lost_tracks_from_crates(
            str(self.serato_dir),
            str(self.mp3_dir)
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
            str(self.mp3_dir)
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
            str(self.mp3_dir)
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
    # H2 — auto_cue.py: Silencedetect com -v info e eliminação de fallback cego
    # =========================================================================

    def test_h2_silencedetect_captures_initial_silence_with_v_info(self):
        """H2: ffmpeg com -v info detecta corretamente silêncio inicial e transiente."""
        # Simula saída real do ffmpeg silencedetect emitida em stderr no nível info
        fake_stderr = (
            "[silencedetect @ 0x123] silence_start: 0\n"
            "[silencedetect @ 0x123] silence_end: 1.45 | silence_duration: 1.45\n"
        )
        mock_proc = MagicMock(returncode=0, stderr=fake_stderr)

        with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
             patch("subprocess.run", return_value=mock_proc):
            res = auto_cue.detect_audio_transients("/fake/track.mp3", duration_sec=100.0)

        self.assertTrue(res["has_transient"])
        self.assertTrue(res["confiavel"])
        self.assertEqual(res["first_beat_ms"], 1450)

    def test_h2_continuous_silence_reports_no_transient_without_blind_fallback(self):
        """H2: Arquivo em silêncio contínuo reporta has_transient=False em vez de 100ms cego."""
        fake_stderr = "[silencedetect @ 0x123] silence_start: 0\n" # sem silence_end nos 15s
        mock_proc = MagicMock(returncode=0, stderr=fake_stderr)

        with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
             patch("subprocess.run", return_value=mock_proc):
            res = auto_cue.detect_audio_transients("/fake/track.mp3", duration_sec=100.0)

        self.assertFalse(res["has_transient"])
        self.assertFalse(res["confiavel"])
        self.assertEqual(res["first_beat_ms"], 500)

    def test_h2_audio_without_initial_silence(self):
        """H2: Áudio que inicia imediatamente sem silêncio inicial detecta transiente no início."""
        fake_stderr = "[silencedetect @ 0x123] silence_start: 8.5\n" # silêncio só no meio
        mock_proc = MagicMock(returncode=0, stderr=fake_stderr)

        with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
             patch("subprocess.run", return_value=mock_proc):
            res = auto_cue.detect_audio_transients("/fake/track.mp3", duration_sec=100.0)

        self.assertTrue(res["has_transient"])
        self.assertTrue(res["confiavel"])
        self.assertEqual(res["first_beat_ms"], 100)

    def test_h2_invalid_audio_returns_unreliable(self):
        """H2: Arquivo inválido ou falha de ffmpeg reporta has_transient=False."""
        mock_proc = MagicMock(returncode=1, stderr="Invalid data found when processing input\n")

        with patch("auto_cue.get_ffmpeg_bin", return_value="/fake/ffmpeg"), \
             patch("subprocess.run", return_value=mock_proc):
            res = auto_cue.detect_audio_transients("/fake/corrupt.mp3", duration_sec=100.0)

        self.assertFalse(res["has_transient"])
        self.assertFalse(res["confiavel"])

    # =========================================================================
    # H4 — auto_cue.py: Restore de cues e bloqueio se backup falhar
    # =========================================================================

    def test_h4_backup_failure_completely_aborts_cue_modification(self):
        """H4: Se o backup falhar, nenhuma modificação de cues é realizada."""
        track = self._create_synthetic_mp3(self.mp3_dir / "BackupFailTrack.mp3")
        orig_bytes = track.read_bytes()

        # Injeta falha no banco de backup
        with patch("auto_cue.backup_track_cues", return_value=False):
            res = auto_cue.generate_and_save_serato_cues(str(track), overwrite_existing=True)

        self.assertFalse(res["sucesso"])
        self.assertIn("backup", res["erro"].lower())
        self.assertEqual(track.read_bytes(), orig_bytes)

    def test_h4_track_without_tags_backs_up_and_restores_clean_state(self):
        """H4: Faixa sem tags prévias salva estado vazio e restore apaga os cues adicionados."""
        track = self.mp3_dir / "NoTagTrack.mp3"
        frame = b'\xff\xfb\x90\x00' + b'\x00' * 413
        track.write_bytes(frame * 450)

        # Gera cues
        res = auto_cue.generate_and_save_serato_cues(str(track), overwrite_existing=True)
        self.assertTrue(res["sucesso"])

        from mutagen.id3 import ID3
        id3_after = ID3(str(track))
        self.assertIn("GEOB:Serato Markers2", id3_after)

        # Restaura cues
        res_rest = auto_cue.restore_track_cues(str(track))
        self.assertTrue(res_rest["sucesso"])

        id3_restored = ID3(str(track))
        self.assertNotIn("GEOB:Serato Markers2", id3_restored)

    def test_h4_custom_dj_cues_are_preserved_and_restored(self):
        """H4: Cues manuais e personalizados de DJ são preservados e restaurados fielmente."""
        track = self._create_synthetic_mp3(self.mp3_dir / "CustomCueTrack.mp3")

        # Insere marcador manual customizado
        custom_blob = b"\x01\x01CUSTOM_DJ_MARKERS2_DATA"
        from mutagen.id3 import ID3, GEOB
        id3 = ID3(str(track))
        id3.add(GEOB(encoding=0, mime="application/octet-stream", desc="Serato Markers2", data=custom_blob))
        id3.save(str(track), v2_version=3)

        # Sobrescreve com flag forçada
        res = auto_cue.generate_and_save_serato_cues(str(track), overwrite_existing=True)
        self.assertTrue(res["sucesso"])

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


if __name__ == "__main__":
    unittest.main()
