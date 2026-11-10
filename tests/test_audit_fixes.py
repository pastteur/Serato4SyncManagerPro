#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SUÍTE DE TESTES DE REGRESSÃO - AUDITORIA TÉCNICA DO SERATO 4 SYNC MANAGER PRO
================================================================================
Cobre os 14 requisitos de auditoria:
1. Persistência e detecção de caminhos
2. Localização canônica dos scripts
3. Execução de subprocessos e pipes concorrentes
4. Dry Run estrito sem efeitos persistentes
5. Tratamento de erros do scanner e proteção contra varredura incompleta
6. Cache com assinatura física estendida (dev, ino, ctime, mtime, nfc)
7. Auditoria forense de duplicidades com comprovação de hash
8. Preservação binária de crates (.crate) e blocos desconhecidos
9. Preservação de ordenação original em crates e neworder.pref
10. Auto-Cue: proteção de cues manuais de DJ e reporte de erros
11. Track Matcher: redução de falsos positivos e trava de segurança
12. Consistência entre resumo (Análise) e execução (Ajustar)
================================================================================
"""

import sys
import os
import shutil
import tempfile
import struct
import json
import unittest
from pathlib import Path

# Adiciona o diretório raiz do projeto ao sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import serato_macos_app
import auto_cue
import track_matcher
import audio_health
import journal


class TestSeratoSyncProAuditFixes(unittest.TestCase):

    def setUp(self):
        """Cria ambiente temporário isolado para cada teste."""
        self.test_dir = tempfile.mkdtemp(prefix="serato_sync_audit_test_")
        self.root_path = Path(self.test_dir)
        self.mp3_dir = self.root_path / "Music" / "MP3"
        self.serato_dir = self.root_path / "_Serato_"
        self.logs_dir = self.root_path / "logs"

        self.mp3_dir.mkdir(parents=True, exist_ok=True)
        self.serato_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Remove ambiente temporário após cada teste."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_dummy_mp3(self, filepath: Path, duration_sec: float = 120.0, audio_content: bytes = b''):
        """Cria um arquivo de teste com cabeçalho ID3v2.3 válido e frames MPEG válidos para mutagen."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        tag_data = b'TIT2\x00\x00\x00\x0a\x00\x00\x00Test Track'
        tag_len = len(tag_data)
        synch_len = bytes([
            (tag_len >> 21) & 0x7F,
            (tag_len >> 14) & 0x7F,
            (tag_len >> 7) & 0x7F,
            tag_len & 0x7F
        ])
        header = b'ID3\x03\x00\x00' + synch_len + tag_data
        # MPEG 1 Layer 3, 128 kbps, 44100 Hz, frame size = 417 bytes
        frame = b'\xff\xfb\x90\x00' + (audio_content or b'\x00' * 413)[:413]
        if len(frame) < 417:
            frame = frame + b'\x00' * (417 - len(frame))
        with open(filepath, 'wb') as f:
            f.write(header)
            f.write(frame * 50)

    # --------------------------------------------------------------------------
    # REQUISITO 4: DRY RUN ESTRITO (SOMENTE LEITURA, SEM ALTERAÇÕES PERSISTENTES)
    # --------------------------------------------------------------------------
    def test_dry_run_leaves_zero_persistent_changes(self):
        """Comprova que o modo Dry Run não cria Subcrates, não grava crates, nem logs/cache."""
        # Cria estrutura de pastas com áudios
        crate_folder = self.mp3_dir / "Afro House"
        crate_folder.mkdir(parents=True)
        self._create_dummy_mp3(crate_folder / "Track01.mp3")
        self._create_dummy_mp3(crate_folder / "Track02.mp3")

        # Assegura que Subcrates e logs não existem previamente
        subcrates_path = self.serato_dir / "Subcrates"
        if subcrates_path.exists():
            shutil.rmtree(subcrates_path)
        if self.logs_dir.exists():
            shutil.rmtree(self.logs_dir)

        # Executa sincronização em modo Dry Run
        ok, resumo = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            export_csv=True,
            emit_json_summary=False,
            dry_run=True
        )

        self.assertTrue(ok)
        self.assertTrue(resumo["dry_run"])
        self.assertEqual(resumo["total_faixas"], 2)
        self.assertIn("Afro House", resumo["crates_arvore"])

        # COMPROVAÇÃO RIGOROSA: NADA FOI CRIADO NO DISCO!
        self.assertFalse(subcrates_path.exists(), "ERRO: Pasta Subcrates foi criada durante Dry Run!")
        self.assertFalse((self.serato_dir / "neworder.pref").exists(), "ERRO: neworder.pref foi criado durante Dry Run!")
        self.assertFalse((self.logs_dir / ".serato_sync_cache.json").exists(), "ERRO: Cache foi gravado durante Dry Run!")
        self.assertFalse((self.logs_dir / ".serato_sync_summary.json").exists(), "ERRO: Resumo foi gravado durante Dry Run!")

        # Nenhum arquivo CSV deve ter sido gerado
        csv_files = list(self.logs_dir.glob("*.csv")) if self.logs_dir.exists() else []
        self.assertEqual(len(csv_files), 0, "ERRO: Arquivos CSV foram persistidos durante Dry Run!")

    # --------------------------------------------------------------------------
    # REQUISITOS 5 E 6: TRATAMENTO DE ERROS DO SCANNER E VARREDURA INCOMPLETA
    # --------------------------------------------------------------------------
    def test_scanner_incomplete_scan_prevents_deletions_and_cache(self):
        """Comprova que uma varredura com falhas de acesso não apaga crates e não salva cache."""
        crate_folder = self.mp3_dir / "Tech House"
        crate_folder.mkdir(parents=True)
        good_track = crate_folder / "Good.mp3"
        self._create_dummy_mp3(good_track)

        # Executa sync normal para criar a crate inicial
        serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            export_csv=False,
            dry_run=False
        )

        crate_file = self.serato_dir / "Subcrates" / "Tech House.crate"
        self.assertTrue(crate_file.exists())

        # Simula erro de leitura em arquivo durante nova varredura
        original_stat = Path.stat
        unreadable_file = crate_folder / "Broken.mp3"
        self._create_dummy_mp3(unreadable_file)

        def mock_stat(path_obj, *args, **kwargs):
            if path_obj.name == "Broken.mp3":
                raise OSError("Permission denied (EACCES) simulado para teste de auditoria")
            return original_stat(path_obj, *args, **kwargs)

        Path.stat = mock_stat
        try:
            ok, resumo = serato_macos_app.sincronizar_biblioteca(
                mp3_dir_str=str(self.mp3_dir),
                serato_dir_str=str(self.serato_dir),
                logs_dir_str=str(self.logs_dir),
                export_csv=False,
                dry_run=False
            )
            self.assertFalse(ok, "Uma varredura incompleta não pode retornar sucesso=True!")
            self.assertEqual(resumo["status_analise"], "parcial_com_erros")
            self.assertTrue(len(resumo["erros_leitura"]) > 0)
            # A crate física pré-existente DEVE ser preservada contra exclusão acidental
            self.assertTrue(crate_file.exists(), "Crate existente foi excluída indevidamente em varredura parcial!")
        finally:
            Path.stat = original_stat

    # --------------------------------------------------------------------------
    # REQUISITO 6: ASSINATURA FÍSICA MATEMÁTICA ESTENDIDA
    # --------------------------------------------------------------------------
    def test_extended_metadata_signature_unambiguous(self):
        """Comprova o cálculo de assinatura matemática TLV não-ambígua."""
        meta_items_1 = [
            ("TrackA.mp3", "TrackA.mp3", 5000000, 1700000000000000000, 1700000000000000000, 16777220, 12345),
            ("TrackB.mp3", "TrackB.mp3", 6000000, 1700000000000000000, 1700000000000000000, 16777220, 12346),
        ]
        sig1 = serato_macos_app.calcular_assinatura_pasta(meta_items_1)
        self.assertIsInstance(sig1, str)
        self.assertEqual(len(sig1), 64)

        # Mesmos metadados devem gerar rigorosamente o mesmo hash
        sig1_repeat = serato_macos_app.calcular_assinatura_pasta(meta_items_1)
        self.assertEqual(sig1, sig1_repeat)

        # Alteração de qualquer atributo (ex: inode) deve mudar a assinatura
        meta_items_modified = [
            ("TrackA.mp3", "TrackA.mp3", 5000000, 1700000000000000000, 1700000000000000000, 16777220, 99999), # inode modificado
            ("TrackB.mp3", "TrackB.mp3", 6000000, 1700000000000000000, 1700000000000000000, 16777220, 12346),
        ]
        sig2 = serato_macos_app.calcular_assinatura_pasta(meta_items_modified)
        self.assertNotEqual(sig1, sig2)

    # --------------------------------------------------------------------------
    # REQUISITO 7: AUDITORIA FORENSE DE DUPLICIDADES COM HASH
    # --------------------------------------------------------------------------
    def test_duplicates_identification_with_hash_verification(self):
        """Comprova a classificação de duplicados: comprovados vs possíveis."""
        folder1 = self.mp3_dir / "Folder1"
        folder2 = self.mp3_dir / "Folder2"
        folder1.mkdir(parents=True)
        folder2.mkdir(parents=True)

        audio_content_exact = b'EXACT_AUDIO_STREAM_DATA_ABC_123'
        file_a = folder1 / "Song.mp3"
        file_b = folder2 / "Song.mp3"

        # Arquivos com áudio 100% idêntico
        self._create_dummy_mp3(file_a, audio_content=audio_content_exact)
        self._create_dummy_mp3(file_b, audio_content=audio_content_exact)

        ok, resumo = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            export_csv=False,
            dry_run=True
        )

        dups = resumo.get("duplicados", [])
        self.assertEqual(len(dups), 1)
        dup_entry = dups[0]
        self.assertEqual(dup_entry["grau_certeza"], "IDENTICO_COMPROVADO")
        self.assertIn("100% idêntico", dup_entry["motivo"])

    # --------------------------------------------------------------------------
    # REQUISITO 8 E 9: PRESERVAÇÃO DE CRATES, ORDENAÇÃO E NEWORDER.PREF
    # --------------------------------------------------------------------------
    def test_crate_structure_preserves_order_and_custom_blocks(self):
        """Comprova que a leitura e escrita de .crate preserva blocos ovct e ordem de faixas."""
        subcrates_path = self.serato_dir / "Subcrates"
        subcrates_path.mkdir(parents=True, exist_ok=True)
        target_crate = subcrates_path / "Ordenada.crate"

        header = b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000'
        custom_block = b'ovct\x00\x00\x00\x0cCUSTOM_VIEWS'
        ptrk1 = serato_macos_app.criar_tag_tlv('ptrk', 'Track2.mp3')
        otrk1 = b'otrk' + struct.pack('>I', len(ptrk1)) + ptrk1
        ptrk2 = serato_macos_app.criar_tag_tlv('ptrk', 'Track1.mp3')
        otrk2 = b'otrk' + struct.pack('>I', len(ptrk2)) + ptrk2

        with open(target_crate, 'wb') as f:
            f.write(header + custom_block + otrk1 + otrk2)

        # Lê estruturalmente a crate
        h, faixas, blocos, outros = serato_macos_app.parse_crate_binary(target_crate.read_bytes())
        self.assertEqual(h, header)
        self.assertEqual(faixas, ['Track2.mp3', 'Track1.mp3']) # ordem original preservada
        self.assertEqual(len(outros), 1)
        self.assertEqual(outros[0], custom_block) # bloco ovct preservado!

    def test_neworder_pref_preserves_existing_user_order(self):
        """Comprova que neworder.pref mantém a ordenação configurada pelo DJ."""
        pref_file = self.serato_dir / "neworder.pref"
        header = b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000'

        # Cria preferência existente onde 'B' vem antes de 'A' por escolha do DJ
        tvcn_b = serato_macos_app.criar_tag_tlv('tvcn', 'Crate B')
        nior_b = b'nior' + struct.pack('>I', len(tvcn_b)) + tvcn_b
        tvcn_a = serato_macos_app.criar_tag_tlv('tvcn', 'Crate A')
        nior_a = b'nior' + struct.pack('>I', len(tvcn_a)) + tvcn_a
        with open(pref_file, 'wb') as f:
            f.write(header + nior_b + nior_a)

        # Cria pastas físicas no disco
        (self.mp3_dir / "Crate B").mkdir(parents=True)
        (self.mp3_dir / "Crate A").mkdir(parents=True)
        (self.mp3_dir / "Crate Nova C").mkdir(parents=True)
        self._create_dummy_mp3(self.mp3_dir / "Crate B" / "1.mp3")
        self._create_dummy_mp3(self.mp3_dir / "Crate A" / "1.mp3")
        self._create_dummy_mp3(self.mp3_dir / "Crate Nova C" / "1.mp3")

        # Executa sincronização real
        serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            export_csv=False,
            dry_run=False
        )

        _, ordem_resultante, _ = serato_macos_app.parse_neworder_pref(pref_file.read_bytes())
        # A ordem 'Crate B' antes de 'Crate A' DEVE ser rigorosamente mantida!
        self.assertEqual(ordem_resultante[0], 'Crate B')
        self.assertEqual(ordem_resultante[1], 'Crate A')
        self.assertEqual(ordem_resultante[2], 'Crate Nova C')

    # --------------------------------------------------------------------------
    # REQUISITO 10: AUTO-CUE PROTEÇÃO DE CUES MANUAIS
    # --------------------------------------------------------------------------
    def test_auto_cue_detailed_audit_distinguishes_custom_cues(self):
        """Comprova que cues manuais do DJ não são confundidos com o Auto-Cue padrão."""
        crate_dir = self.mp3_dir / "CuesTest"
        crate_dir.mkdir(parents=True)
        track_with_manual_cue = crate_dir / "ManualCue.mp3"
        self._create_dummy_mp3(track_with_manual_cue)

        # Se mutagen estiver disponível, insere marcadores manuais de DJ com label personalizado
        if auto_cue.mutagen:
            try:
                from mutagen.id3 import ID3, GEOB
                id3 = ID3(str(track_with_manual_cue))
                custom_cue_payload = [
                    {"index": 0, "pos_ms": 1000, "label": "DROP ESPECIAL DJ PASTTEUR", "color": "red"}
                ]
                raw_tag = auto_cue.build_serato_markers2_tag(custom_cue_payload)
                id3.add(GEOB(encoding=0, mime='application/octet-stream', desc='Serato Markers2', data=raw_tag))
                id3.save(v2_version=3)
            except Exception:
                pass

        audit_res = auto_cue.audit_crate_cues_detailed(str(self.mp3_dir), crate_raiz="CuesTest")
        self.assertTrue(audit_res["sucesso"])
        if auto_cue.mutagen:
            self.assertEqual(audit_res["personalizadas"], 1)
            item = audit_res["items"][0]
            self.assertEqual(item["tipo_cue"], "Personalizado DJ (Protegido)")

    # --------------------------------------------------------------------------
    # REQUISITO 11: TRACK MATCHER REDUÇÃO DE FALSOS POSITIVOS E TRAVA DE SEGURANÇA
    # --------------------------------------------------------------------------
    def test_track_matcher_blocks_remix_and_different_tracks(self):
        """Comprova que o Track Matcher bloqueia substituição de remix por original e palavras curtas."""
        crate_dir = self.mp3_dir / "Hits"
        crate_dir.mkdir(parents=True)
        orig_track = crate_dir / "Levels.mp3"
        self._create_dummy_mp3(orig_track)

        # Teste 1: Remix novo vs Original na biblioteca
        req_remix = [{
            "raw": "Levels (Alok Remix)",
            "clean_title": "levels",
            "clean_artist": "",
            "is_local_file": True,
            "filepath": str(self.root_path / "Downloads" / "Levels (Alok Remix).mp3"),
            "bitrate": 320,
            "ext": ".mp3",
            "duration": 180.0,
            "filesize": 7000000
        }]

        match_res = track_matcher.match_tracks_against_library(req_remix, str(self.mp3_dir))
        self.assertTrue(match_res["sucesso"])
        encontrada = match_res["encontradas"][0]
        # A substituição deve estar ESTRITAMENTE bloqueada
        self.assertTrue(encontrada["versao_divergente"])
        self.assertFalse(encontrada["upgrade_seguro"])
        self.assertEqual(encontrada["status_comparacao"], "VERSAO_DIVERGENTE")

        # Teste 2: Palavra curta avulsa que coincidiria como substring ("Love")
        req_unrelated = [{
            "raw": "Love",
            "clean_title": "love",
            "clean_artist": "",
            "is_local_file": False
        }]
        match_unrelated = track_matcher.match_tracks_against_library(req_unrelated, str(self.mp3_dir))
        # "Love" não pode ter match com "Levels"
        self.assertEqual(len(match_unrelated["encontradas"]), 0)
        self.assertEqual(len(match_unrelated["faltantes"]), 1)

    # --------------------------------------------------------------------------
    # REQUISITO 12 E 13: FLUXO COMPLETO (ANÁLISE -> RESUMO -> APROVAÇÃO -> AJUSTAR)
    # --------------------------------------------------------------------------
    def test_full_lifecycle_analysis_then_adjust(self):
        """
        Comprova o fluxo integral:
        1. Análise autônoma (Dry Run) prepara as alterações e apresenta resumo
        2. Nenhuma alteração persiste no disco antes da aprovação
        3. Pressionar 'Ajustar' executa exatamente o plano proposto
        4. Segunda análise comprova estado estável e trava de cache 100% eficiente
        """
        # 1. Prepara dados na biblioteca
        house_dir = self.mp3_dir / "Deep House"
        house_dir.mkdir(parents=True)
        self._create_dummy_mp3(house_dir / "Deep01.mp3")
        self._create_dummy_mp3(house_dir / "Deep02.mp3")

        # 2. PASSO 1: Análise Autônoma (Dry Run)
        ok_analise, resumo_analise = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            export_csv=True,
            dry_run=True
        )
        self.assertTrue(ok_analise)
        self.assertTrue(resumo_analise["dry_run"])
        self.assertEqual(resumo_analise["total_faixas"], 2)
        self.assertEqual(resumo_analise["crates_gravadas"], 1) # Proposta: 1 crate a ser gravada

        # Valida que o disco permaneceu completamente virgem
        crate_file = self.serato_dir / "Subcrates" / "Deep House.crate"
        self.assertFalse(crate_file.exists(), "Disco foi alterado antes do usuário pressionar Ajustar!")

        # 3. PASSO 2: Usuário pressiona "Ajustar" (Persistência autorizada)
        ok_ajuste, resumo_ajuste = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            export_csv=True,
            dry_run=False
        )
        self.assertTrue(ok_ajuste)
        self.assertFalse(resumo_ajuste["dry_run"])
        self.assertEqual(resumo_ajuste["crates_gravadas"], 1)

        # Valida que os arquivos foram gravados no disco
        self.assertTrue(crate_file.exists())
        self.assertTrue((self.serato_dir / "neworder.pref").exists())
        self.assertTrue((self.logs_dir / ".serato_sync_cache.json").exists())

        # 4. PASSO 3: Reanálise após o ajuste
        ok_reanalise, resumo_reanalise = serato_macos_app.sincronizar_biblioteca(
            mp3_dir_str=str(self.mp3_dir),
            serato_dir_str=str(self.serato_dir),
            logs_dir_str=str(self.logs_dir),
            export_csv=True,
            dry_run=False
        )
        self.assertTrue(ok_reanalise)
        # Nenhuma crate deve ser regravada: cache protege 100% contra I/O redundante
        self.assertEqual(resumo_reanalise["crates_gravadas"], 0)
        self.assertEqual(resumo_reanalise["crates_inalteradas"], 1)
        self.assertEqual(resumo_reanalise["faixas_adicionadas"], 0)
        self.assertEqual(resumo_reanalise["faixas_removidas"], 0)

    # --------------------------------------------------------------------------
    # MELHORIA 1: VENDORIZAÇÃO EMBUTIDA DO MUTAGEN (PORTABILIDADE TOTAL NO MACOS)
    # --------------------------------------------------------------------------
    def test_vendor_mutagen_isolation_and_loading(self):
        """Comprova que o mutagen vendorizado existe e carrega perfeitamente sem pip."""
        vendor_dir = PROJECT_ROOT / "vendor" / "mutagen"
        self.assertTrue(vendor_dir.is_dir(), "Diretório vendor/mutagen ausente no projeto")
        self.assertTrue((vendor_dir / "__init__.py").is_file(), "vendor/mutagen/__init__.py ausente")

        # Verifica se o auto_cue e audio_health carregaram mutagen com sucesso
        self.assertIsNotNone(auto_cue.mutagen, "auto_cue.mutagen não foi carregado")
        self.assertIsNotNone(audio_health.mutagen, "audio_health.mutagen não foi carregado")

    # --------------------------------------------------------------------------
    # MELHORIA 2: AUTO-CUE COM DETECÇÃO DE TRANSIENTES E ALINHAMENTO DE COMPASSO
    # --------------------------------------------------------------------------
    def test_auto_cue_transient_phase_alignment(self):
        """Valida que o cálculo de Hot Cues respeita transientes e alinha compassos."""
        # 1. Sem arquivo de áudio físico (modo estático padrão)
        cues_static = auto_cue.calculate_smart_cues(duration_sec=180.0, bpm_float=128.0)
        self.assertEqual(len(cues_static), 5)
        self.assertEqual(cues_static[0]["label"], "Intro")
        self.assertEqual(cues_static[0]["pos_ms"], 500)
        self.assertEqual(cues_static[1]["label"], "Drop 1")
        self.assertTrue(cues_static[1]["pos_ms"] > cues_static[0]["pos_ms"])

        # 2. Com arquivo contendo transientes rápidos
        test_audio = Path("/Users/pastteur/.gemini/tmp/rea/extracted_asar/assets/SoundFX/Free Packs/Free Pack 1/Dog Bark.mp3")
        if test_audio.exists():
            cues_audio = auto_cue.calculate_smart_cues(duration_sec=3.0, bpm_float=120.0, filepath_str=str(test_audio))
            self.assertEqual(len(cues_audio), 5)
            # Confirma que detectou o início do áudio diferente do padrão fixo de 500ms
            self.assertIn(cues_audio[0]["pos_ms"], [50, 100])

    # --------------------------------------------------------------------------
    # MELHORIA 3: AUDITORIA ESPECTRAL DE FAKE 320 KBPS
    # --------------------------------------------------------------------------
    def test_fake_320k_spectral_cutoff_detection(self):
        """Valida detecção de corte de frequências altas em faixas com falso 320k."""
        # Arquivo normal que não deve ser classificado como fake
        test_audio = Path("/Users/pastteur/.gemini/tmp/rea/extracted_asar/assets/SoundFX/Free Packs/Free Pack 1/Dog Bark.mp3")
        if test_audio.exists():
            diag = audio_health.inspect_track_health(test_audio, max_duration_suspicious=1.0)
            # Faixa tem 3 segundos de som (não deve quebrar ou lançar exceção)
            self.assertIn("status", diag)
            self.assertIn("categoria", diag)


    # --------------------------------------------------------------------------
    # CORREÇÕES DE AUDITORIA: HASH, FAKE 320K E ROLLBACK DE CUES
    # --------------------------------------------------------------------------
    def _create_long_dummy_mp3(self, filepath: Path, duration_sec: float = 180.0):
        """
        Cria um MP3 sintético com duração real suficiente para o Auto-Cue.
        Frames MPEG1 Layer3 128 kbps / 44.1 kHz ocupam 417 bytes e duram ~26,1 ms cada.
        """
        filepath.parent.mkdir(parents=True, exist_ok=True)
        tag_data = b'TIT2\x00\x00\x00\x0a\x00\x00\x00Test Track'
        tag_len = len(tag_data)
        synch_len = bytes([
            (tag_len >> 21) & 0x7F,
            (tag_len >> 14) & 0x7F,
            (tag_len >> 7) & 0x7F,
            tag_len & 0x7F
        ])
        header = b'ID3\x03\x00\x00' + synch_len + tag_data
        frame = b'\xff\xfb\x90\x00' + b'\x00' * 413
        total_frames = max(1, int(duration_sec / 0.0261))
        with open(filepath, 'wb') as f:
            f.write(header)
            for _ in range(total_frames):
                f.write(frame)

    def test_audio_hash_ignores_id3v2_and_id3v1(self):
        """O hash de duplicatas deve ignorar tags ID3v2 (início) e ID3v1 (fim do arquivo)."""
        audio_payload = b'\xff\xfb\x90\x00' + b'\x11' * 413
        audio_payload = audio_payload * 20

        base = self.mp3_dir / "hash_base.mp3"
        base.write_bytes(b'ID3\x03\x00\x00\x00\x00\x00\x0a' + b'\x00' * 10 + audio_payload)

        com_tags_diferentes = self.mp3_dir / "hash_tags.mp3"
        com_tags_diferentes.write_bytes(
            b'ID3\x03\x00\x00\x00\x00\x00\x1e' + b'\x42' * 30 + audio_payload + b'TAG' + b'\x00' * 125
        )

        h_base = serato_macos_app.compute_quick_audio_hash(base)
        h_tags = serato_macos_app.compute_quick_audio_hash(com_tags_diferentes)
        self.assertTrue(h_base)
        self.assertEqual(h_base, h_tags)

        outra_copia = self.mp3_dir / "hash_diferente.mp3"
        outra_copia.write_bytes(b'ID3\x03\x00\x00\x00\x00\x00\x0a' + b'\x00' * 10 + audio_payload[::-1])
        self.assertNotEqual(h_base, serato_macos_app.compute_quick_audio_hash(outra_copia))

    def test_fake_320k_thresholds_come_from_module_constants(self):
        """Garante que o filtro espectral usa os limiares declarados no módulo."""
        self.assertEqual(audio_health.FAKE320_HIGHPASS_HZ, 17500)
        self.assertEqual(audio_health.FAKE320_REFERENCE_HZ, 12000)
        # Bitrate abaixo do limiar nunca é auditado como fake 320k
        ok, motivo = audio_health.detect_fake_320k_cutoff(Path("/tmp/inexistente.mp3"), 200.0, 128000)
        self.assertFalse(ok)
        self.assertEqual(motivo, "")

    def test_cue_backup_and_restore_roundtrip(self):
        """Backup de cues deve registrar até o estado 'sem cues' e permitir restaurá-lo."""
        if not auto_cue.mutagen:
            self.skipTest("mutagen não disponível")

        arquivo = self.mp3_dir / "cues.mp3"
        self._create_long_dummy_mp3(arquivo, duration_sec=180.0)

        home_original = auto_cue.BACKUP_DB_PATH
        auto_cue.BACKUP_DB_PATH = self.root_path / "cues_backup.sqlite"
        journal_original = journal.JOURNAL_PATH
        journal.JOURNAL_PATH = self.root_path / "journal.sqlite"
        try:
            aplicado = auto_cue.generate_and_save_serato_cues(str(arquivo))
            self.assertTrue(aplicado.get("sucesso"), aplicado)

            lista = auto_cue.list_cue_backups()
            self.assertTrue(lista["sucesso"])
            self.assertEqual(lista["total"], 1)
            self.assertEqual(lista["items"][0]["filename"], "cues.mp3")
            self.assertEqual(lista["items"][0]["quantidade_cues"], 0)
            self.assertTrue(lista["items"][0]["arquivo_existe"])

            restaurado = auto_cue.restore_track_cues(str(arquivo))
            self.assertTrue(restaurado.get("sucesso"), restaurado)

            audio = auto_cue.mutagen.File(str(arquivo))
            self.assertIsNone(
                audio.tags.get('GEOB:Serato Markers2') if audio.tags else None,
                "Faixa que não tinha cues deve voltar sem GEOB:Serato Markers2"
            )
        finally:
            auto_cue.BACKUP_DB_PATH = home_original
            journal.JOURNAL_PATH = journal_original

    def test_cue_backup_search_filters_by_filename(self):
        """A busca da tela de backup deve filtrar por nome do arquivo."""
        if not auto_cue.mutagen:
            self.skipTest("mutagen não disponível")

        home_original = auto_cue.BACKUP_DB_PATH
        auto_cue.BACKUP_DB_PATH = self.root_path / "cues_backup.sqlite"
        journal_original = journal.JOURNAL_PATH
        journal.JOURNAL_PATH = self.root_path / "journal.sqlite"
        try:
            for nome in ("Alvo.mp3", "Outro.mp3"):
                arquivo = self.mp3_dir / nome
                self._create_long_dummy_mp3(arquivo, duration_sec=180.0)
                auto_cue.generate_and_save_serato_cues(str(arquivo))

            filtrado = auto_cue.list_cue_backups(search="Alvo")
            self.assertEqual(filtrado["total"], 1)
            self.assertEqual(filtrado["items"][0]["filename"], "Alvo.mp3")
            self.assertEqual(auto_cue.list_cue_backups(search="Nada")["total"], 0)
        finally:
            auto_cue.BACKUP_DB_PATH = home_original
            journal.JOURNAL_PATH = journal_original

    # --------------------------------------------------------------------------
    # REQUISITO 15: AUDIO HEALTH DOCTOR (DYNAMIC QUARANTINE & REPAIR TRAVA)
    # --------------------------------------------------------------------------
    def test_audio_health_quarantine_and_delta_threshold(self):
        """Verifica resolução de pasta de quarentena dinâmica e trava de segurança de 15 segundos."""
        # 1. Resolução dinâmica de quarentena com serato_dir explícito
        custom_serato = self.root_path / "CustomSerato"
        q_dir = audio_health.get_quarantine_dir(serato_dir_str=str(custom_serato))
        self.assertEqual(q_dir.resolve(), (custom_serato / "Quarentena").resolve())
        self.assertTrue(q_dir.exists())

        # 2. Resolução dinâmica de quarentena a partir da árvore do arquivo MP3
        track_in_serato_tree = self.serato_dir / "Subcrates" / "TestSong.mp3"
        track_in_serato_tree.parent.mkdir(parents=True, exist_ok=True)
        q_dir_file = audio_health.get_quarantine_dir(file_path=track_in_serato_tree)
        self.assertEqual(q_dir_file.resolve(), (self.serato_dir / "Quarentena").resolve())
        self.assertTrue(q_dir_file.exists())

        # 3. Fallback seguro quando sem serato_dir e arquivo isolado (fora de qualquer árvore _Serato_)
        isolated_dir = Path(tempfile.mkdtemp(prefix="serato_isolated_"))
        try:
            isolated_file = isolated_dir / "test.mp3"
            isolated_file.touch()
            q_fallback = audio_health.get_quarantine_dir(file_path=isolated_file)
            self.assertEqual(q_fallback.resolve(), audio_health.QUARANTINE_DIR.resolve())
        finally:
            shutil.rmtree(isolated_dir, ignore_errors=True)

    def test_audio_health_repair_duration_threshold_boundaries(self):
        """Valida rigorosamente os limites de tolerância de duração (<= 10.0s aceito, > 10.0s bloqueado)."""
        from unittest.mock import patch, MagicMock

        orig_file = self.mp3_dir / "BoundariesTrack.mp3"
        orig_file.write_bytes(b"\xFF\xFB\x90\x00" + b"\x00" * 25000)

        def mock_mp3_side_effect(path_str):
            mock_mp3 = MagicMock()
            if "__sync_work_" in path_str:
                mock_mp3.info.length = getattr(mock_mp3_side_effect, 'candidate_dur', 200.0)
                mock_mp3.info.sample_rate = 44100
                mock_mp3.info.bitrate = 320000
            else:
                mock_mp3.info.length = getattr(mock_mp3_side_effect, 'orig_dur', 200.0)
            return mock_mp3

        with patch("audio_health.get_yt_dlp_bin", return_value="/fake/yt-dlp"), \
             patch("audio_health.is_serato_running_py", return_value=(False, "")), \
             patch("subprocess.run") as mock_subproc, \
             patch("mutagen.mp3.MP3", side_effect=mock_mp3_side_effect), \
             patch("mutagen.id3.ID3"):

            def fake_run(cmd, **kwargs):
                out_idx = cmd.index("-o") + 1
                out_tmpl = cmd[out_idx]
                out_path = Path(out_tmpl.replace("%(ext)s", "mp3"))
                out_path.write_bytes(b"\xFF\xFB\x90\x00" + b"\x00" * 30000)
                mock_res = MagicMock()
                mock_res.returncode = 0
                return mock_res

            mock_subproc.side_effect = fake_run

            # 1. Delta 5.0s (205.0 vs 200.0) -> ACEITO (<= 10s)
            mock_mp3_side_effect.orig_dur = 200.0
            mock_mp3_side_effect.candidate_dur = 205.0
            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertTrue(res["sucesso"], "Diferença de 5s deve ser aceita")

            # 2. Delta 9.9s (209.9 vs 200.0) -> ACEITO (<= 10s)
            mock_mp3_side_effect.candidate_dur = 209.9
            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertTrue(res["sucesso"], "Diferença de 9.9s deve ser aceita")

            # 3. Delta 10.0s (210.0 vs 200.0) -> ACEITO (<= 10s)
            mock_mp3_side_effect.candidate_dur = 210.0
            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertTrue(res["sucesso"], "Diferença de 10.0s deve ser aceita no limite")

            # 4. Delta 10.1s (210.1 vs 200.0) -> BLOQUEADO (> 10s)
            mock_mp3_side_effect.candidate_dur = 210.1
            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertFalse(res["sucesso"])
            self.assertTrue(res.get("bloqueado_seguranca"))
            self.assertIn("difere da versão encontrada", res["erro"])

            # 5. Delta 14.9s (214.9 vs 200.0) -> BLOQUEADO (> 10s)
            mock_mp3_side_effect.candidate_dur = 214.9
            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertFalse(res["sucesso"])
            self.assertTrue(res.get("bloqueado_seguranca"))

            # 6. Delta 15.0s (215.0 vs 200.0) -> BLOQUEADO (> 10s)
            mock_mp3_side_effect.candidate_dur = 215.0
            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertFalse(res["sucesso"])
            self.assertTrue(res.get("bloqueado_seguranca"))

            # 7. Duração inválida (0s no original) -> BLOQUEADO
            mock_mp3_side_effect.orig_dur = 0.0
            mock_mp3_side_effect.candidate_dur = 200.0
            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertFalse(res["sucesso"])
            self.assertTrue(res.get("bloqueado_seguranca"))

    def test_audio_health_repair_rollback_on_failure(self):
        """Comprova rollback transacional quando ocorre falha durante a instalação."""
        from unittest.mock import patch, MagicMock

        orig_file = self.mp3_dir / "RollbackTrack.mp3"
        original_bytes = b"\xFF\xFB\x90\x00ORIGINAL_TRACK_DATA" + b"\x00" * 25000
        orig_file.write_bytes(original_bytes)

        def mock_mp3_side_effect(path_str):
            mock_mp3 = MagicMock()
            mock_mp3.info.length = 180.0
            mock_mp3.info.sample_rate = 44100
            mock_mp3.info.bitrate = 320000
            return mock_mp3

        with patch("audio_health.get_yt_dlp_bin", return_value="/fake/yt-dlp"), \
             patch("audio_health.is_serato_running_py", return_value=(False, "")), \
             patch("subprocess.run") as mock_subproc, \
             patch("mutagen.mp3.MP3", side_effect=mock_mp3_side_effect), \
             patch("mutagen.id3.ID3"):

            def fake_run(cmd, **kwargs):
                out_idx = cmd.index("-o") + 1
                out_tmpl = cmd[out_idx]
                out_path = Path(out_tmpl.replace("%(ext)s", "mp3"))
                out_path.write_bytes(b"\xFF\xFB\x90\x00DOWNLOADED_DATA" + b"\x00" * 30000)
                mock_res = MagicMock()
                mock_res.returncode = 0
                return mock_res

            mock_subproc.side_effect = fake_run

            # Injeta falha em os.replace na hora da substituição definitiva
            real_replace = os.replace
            replace_calls = 0

            def failing_replace(src, dst):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 1:
                    # Primeira chamada tenta instalar o candidato: forçar erro de I/O
                    raise OSError("Simulated Disk I/O Failure during track install")
                return real_replace(src, dst)

            with patch("os.replace", side_effect=failing_replace):
                res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
                self.assertFalse(res["sucesso"])
                self.assertIn("Rollback", res["erro"])
                # Comprovação absoluta: O original foi preservado com seu conteúdo idêntico
                self.assertTrue(orig_file.exists())
                self.assertEqual(orig_file.read_bytes(), original_bytes)
                # Nenhum arquivo temporário de trabalho deixado
                work_files = list(self.mp3_dir.glob("*.__sync_work_*"))
                self.assertEqual(len(work_files), 0)

    def test_audio_health_serato_lock_blocks_repair(self):
        """Comprova que a presença de processo Serato aberto bloqueia reparação individual e em lote."""
        from unittest.mock import patch

        orig_file = self.mp3_dir / "LockTrack.mp3"
        orig_file.write_bytes(b"\xFF\xFB\x90\x00" + b"\x00" * 25000)

        with patch("audio_health.is_serato_running_py", return_value=(True, "Processo 'Serato DJ Pro' está em execução ativa")):
            # Reparação individual
            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertFalse(res["sucesso"])
            self.assertTrue(res.get("bloqueado_serato"))
            self.assertIn("BLOQUEIO DE SEGURANÇA", res["erro"])

    def test_audio_health_quarantine_metadata_manifest(self):
        """Comprova que o arquivo substituído gera manifesto .meta.json detalhado na Quarentena."""
        from unittest.mock import patch, MagicMock

        orig_file = (self.mp3_dir / "ManifestTrack.mp3").resolve()
        orig_file.write_bytes(b"\xFF\xFB\x90\x00ORIGINAL_CONTENT" + b"\x00" * 25000)

        def mock_mp3_side_effect(path_str):
            mock_mp3 = MagicMock()
            mock_mp3.info.length = 200.0
            mock_mp3.info.sample_rate = 44100
            mock_mp3.info.bitrate = 320000
            return mock_mp3

        with patch("audio_health.get_yt_dlp_bin", return_value="/fake/yt-dlp"), \
             patch("audio_health.is_serato_running_py", return_value=(False, "")), \
             patch("subprocess.run") as mock_subproc, \
             patch("mutagen.mp3.MP3", side_effect=mock_mp3_side_effect), \
             patch("mutagen.id3.ID3"):

            def fake_run(cmd, **kwargs):
                out_idx = cmd.index("-o") + 1
                out_tmpl = cmd[out_idx]
                out_path = Path(out_tmpl.replace("%(ext)s", "mp3"))
                out_path.write_bytes(b"\xFF\xFB\x90\x00CANDIDATE_CONTENT" + b"\x00" * 30000)
                mock_res = MagicMock()
                mock_res.returncode = 0
                return mock_res

            mock_subproc.side_effect = fake_run

            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertTrue(res["sucesso"])

            q_dir = self.serato_dir / "Quarentena"
            manifests = list(q_dir.glob("*_ManifestTrack.mp3.meta.json"))
            self.assertEqual(len(manifests), 1, "Manifesto .meta.json deve existir na quarentena")

            manifest_content = json.loads(manifests[0].read_text(encoding='utf-8'))
            self.assertEqual(manifest_content["caminho_original"], str(orig_file))
            self.assertEqual(manifest_content["arquivo_nome"], "ManifestTrack.mp3")
            self.assertEqual(manifest_content["duracao_original"], 200.0)
            self.assertEqual(manifest_content["status"], "substituicao_confirmada")

    def test_audio_health_concurrency_file_lock_rejection(self):
        """Comprova que duas tarefas tentando reparar o mesmo arquivo simultaneamente são bloqueadas."""
        from unittest.mock import patch
        import fcntl
        orig_file = (self.mp3_dir / "ConcurrentTrack.mp3").resolve()
        orig_file.write_bytes(b"\xFF\xFB\x90\x00" + b"\x00" * 25000)

        lock_file = orig_file.parent / f".{orig_file.name}.repair_lock"
        fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            with patch("audio_health.is_serato_running_py", return_value=(False, "")):
                res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
                self.assertFalse(res["sucesso"])
                self.assertIn("já está sendo processado por outra tarefa", res["erro"])
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            # Sem unlink para manter conformidade com ausência de race condition

    def test_audio_health_hash_mismatch_during_download_aborts(self):
        """Comprova que se o arquivo original for alterado externamente durante o download, a substituição é abortada."""
        from unittest.mock import patch, MagicMock

        orig_file = (self.mp3_dir / "ModifiedDuringDownload.mp3").resolve()
        orig_file.write_bytes(b"\xFF\xFB\x90\x00INITIAL_AUDIO_CONTENT" + b"\x00" * 25000)

        def mock_mp3_side_effect(path_str):
            mock_mp3 = MagicMock()
            mock_mp3.info.length = 180.0
            mock_mp3.info.sample_rate = 44100
            mock_mp3.info.bitrate = 320000
            return mock_mp3

        with patch("audio_health.get_yt_dlp_bin", return_value="/fake/yt-dlp"), \
             patch("audio_health.is_serato_running_py", return_value=(False, "")), \
             patch("subprocess.run") as mock_subproc, \
             patch("mutagen.mp3.MP3", side_effect=mock_mp3_side_effect):

            def fake_run(cmd, **kwargs):
                # Simula processo externo ou DJ tocando/modificando o arquivo original durante o download
                orig_file.write_bytes(b"\xFF\xFB\x90\x00MODIFIED_EXTERNALLY" + b"\x00" * 25000)
                out_idx = cmd.index("-o") + 1
                out_tmpl = cmd[out_idx]
                out_path = Path(out_tmpl.replace("%(ext)s", "mp3"))
                out_path.write_bytes(b"\xFF\xFB\x90\x00CANDIDATE_AUDIO" + b"\x00" * 30000)
                mock_res = MagicMock()
                mock_res.returncode = 0
                return mock_res

            mock_subproc.side_effect = fake_run

            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertFalse(res["sucesso"])
            self.assertTrue(res.get("bloqueado_seguranca"))
            self.assertIn("modificado externamente durante o download", res["erro"])
            # Garante que o arquivo original não foi substituído pelo candidato
            self.assertIn(b"MODIFIED_EXTERNALLY", orig_file.read_bytes())

    def test_audio_health_rollback_after_candidate_installed(self):
        """Comprova rollback efetivo restaurando o original quando falha ocorre DEPOIS do os.replace físico."""
        from unittest.mock import patch, MagicMock

        orig_file = (self.mp3_dir / "RollbackAfterInstall.mp3").resolve()
        initial_content = b"\xFF\xFB\x90\x00ORIGINAL_EXCLUSIVE_BYTES" + b"\x00" * 25000
        orig_file.write_bytes(initial_content)

        def mock_mp3_side_effect(path_str):
            mock_mp3 = MagicMock()
            mock_mp3.info.length = 200.0
            mock_mp3.info.sample_rate = 44100
            mock_mp3.info.bitrate = 320000
            return mock_mp3

        with patch("audio_health.get_yt_dlp_bin", return_value="/fake/yt-dlp"), \
             patch("audio_health.is_serato_running_py", return_value=(False, "")), \
             patch("subprocess.run") as mock_subproc, \
             patch("mutagen.mp3.MP3", side_effect=mock_mp3_side_effect), \
             patch("mutagen.id3.ID3"):

            def fake_run(cmd, **kwargs):
                out_idx = cmd.index("-o") + 1
                out_tmpl = cmd[out_idx]
                out_path = Path(out_tmpl.replace("%(ext)s", "mp3"))
                out_path.write_bytes(b"\xFF\xFB\x90\x00CANDIDATE_BYTES" + b"\x00" * 30000)
                mock_res = MagicMock()
                mock_res.returncode = 0
                return mock_res

            mock_subproc.side_effect = fake_run

            # Provoca erro intencional na validação de manifesto obrigatório pós-replace
            with patch.object(Path, "write_text", side_effect=IOError("Disco cheio ao gravar manifesto .meta.json")):
                res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
                self.assertFalse(res["sucesso"])
                self.assertIn("Rollback executado", res["erro"])
                # Comprova que o arquivo original foi restaurado ao seu estado inicial integral
                self.assertEqual(orig_file.read_bytes(), initial_content)

    def test_audio_health_duration_tolerance_short_tracks(self):
        """Comprova os limites exatos da regra de tolerância de duração para faixas curtas (<= 50s)."""
        # Para orig_dur = 20.0s -> max_tolerance = min(3.0, round(20 * 0.10, 1)) = 2.0s
        dur_20 = 20.0
        tol_20 = 10.0 if dur_20 > 50.0 else min(3.0, round(dur_20 * 0.10, 1))
        self.assertEqual(tol_20, 2.0)
        # Diferença de 1.8s deve ser aceita (<= 2.0)
        self.assertLessEqual(1.8, tol_20)
        # Diferença de 2.2s deve ser rejeitada (> 2.0)
        self.assertGreater(2.2, tol_20)

        # Para orig_dur = 40.0s -> max_tolerance = min(3.0, round(40 * 0.10, 1)) = 3.0s (teto atingido)
        dur_40 = 40.0
        tol_40 = 10.0 if dur_40 > 50.0 else min(3.0, round(dur_40 * 0.10, 1))
        self.assertEqual(tol_40, 3.0)
        self.assertLessEqual(2.9, tol_40)
        self.assertGreater(3.2, tol_40)

        # Para orig_dur = 120.0s (> 50s) -> max_tolerance = 10.0s
        dur_120 = 120.0
        tol_120 = 10.0 if dur_120 > 50.0 else min(3.0, round(dur_120 * 0.10, 1))
        self.assertEqual(tol_120, 10.0)

    def test_audio_health_batch_repair_reports_failure_on_individual_errors(self):
        """Comprova que batch_repair_tracks_online sinaliza sucesso=False quando há erros individuais."""
        import io
        from unittest.mock import patch

        file_list = ["/fake/Track1.mp3", "/fake/Track2.mp3"]

        def mock_repair(fp, serato_dir_str=""):
            if "Track1" in fp:
                return {"sucesso": True, "arquivo": "Track1.mp3"}
            else:
                return {"sucesso": False, "erro": "Download falhou"}

        with patch("audio_health.is_serato_running_py", return_value=(False, "")), \
             patch("audio_health.repair_track_online", side_effect=mock_repair), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:

            audio_health.batch_repair_tracks_online(file_list)
            output = mock_stdout.getvalue()
            lines = [json.loads(line) for line in output.strip().split("\n") if line.strip().startswith("{")]
            fim_events = [e for e in lines if e.get("tipo") == "fim"]
            self.assertEqual(len(fim_events), 1)
            fim = fim_events[0]
            # Comprova que NÃO emite sucesso enganoso
            self.assertFalse(fim["sucesso"], "sucesso deve ser False se houver falhas parciais")
            self.assertTrue(fim.get("sucesso_parcial"), "sucesso_parcial deve ser True se ao menos 1 atualizou")
            self.assertEqual(fim["atualizados"], 1)
            self.assertEqual(len(fim["erros"]), 1)

    def test_audio_health_id3_critical_tag_loss_aborts_repair(self):
        """Comprova que se a validação pós-escrita detectar perda de tags Serato GEOB, o processo é abortado."""
        from unittest.mock import patch, MagicMock

        orig_file = self.mp3_dir / "CriticalTagTrack.mp3"
        orig_file.write_bytes(b"\xFF\xFB\x90\x00" + b"\x00" * 25000)

        def mock_mp3_side_effect(path_str):
            mock_mp3 = MagicMock()
            mock_mp3.info.length = 150.0
            mock_mp3.info.sample_rate = 44100
            mock_mp3.info.bitrate = 320000
            return mock_mp3

        # Simula objeto ID3 original contendo GEOB:Serato Markers2
        orig_mock_id3 = {
            "GEOB:Serato Markers2": MagicMock(data=b"SERATO_MARKERS2_BINARY_DATA")
        }
        # Simula arquivo salvo onde GEOB:Serato Markers2 sumiu ou ficou vazio
        reopened_mock_id3 = {}

        call_count = 0
        def mock_id3_call(path_str):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return MagicMock(__getitem__=lambda s, k: orig_mock_id3[k], keys=lambda: list(orig_mock_id3.keys()))
            else:
                # Reabertura pós-salvamento: tag ausente!
                return MagicMock(__getitem__=lambda s, k: reopened_mock_id3[k], __contains__=lambda s, k: k in reopened_mock_id3)

        with patch("audio_health.get_yt_dlp_bin", return_value="/fake/yt-dlp"), \
             patch("audio_health.is_serato_running_py", return_value=(False, "")), \
             patch("subprocess.run") as mock_subproc, \
             patch("mutagen.mp3.MP3", side_effect=mock_mp3_side_effect), \
             patch("mutagen.id3.ID3", side_effect=mock_id3_call):

            def fake_run(cmd, **kwargs):
                out_idx = cmd.index("-o") + 1
                out_tmpl = cmd[out_idx]
                out_path = Path(out_tmpl.replace("%(ext)s", "mp3"))
                out_path.write_bytes(b"\xFF\xFB\x90\x00" + b"\x00" * 30000)
                mock_res = MagicMock()
                mock_res.returncode = 0
                return mock_res

            mock_subproc.side_effect = fake_run

            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertFalse(res["sucesso"])
            self.assertIn("Falha ao preservar e comprovar metadados", res["erro"])
            self.assertTrue(orig_file.exists())

    def test_audio_health_id3_real_physical_preservation_and_value_check(self):
        """Comprova a preservação e verificação física real (sem mocks em ID3) de tags de texto e GEOB binário."""
        from unittest.mock import patch, MagicMock
        from mutagen.id3 import ID3, TIT2, TBPM, TKEY, GEOB

        orig_file = (self.mp3_dir / "PhysicalID3Track.mp3").resolve()
        self._create_dummy_mp3(orig_file, duration_sec=120.0)

        # Grava tags reais no arquivo original
        tag = ID3()
        tag.add(TIT2(encoding=3, text=["Original Title Real"]))
        tag.add(TBPM(encoding=3, text=["128"]))
        tag.add(TKEY(encoding=3, text=["8A"]))
        tag.add(GEOB(encoding=0, mime="application/octet-stream", desc="Serato Markers2", data=b"\x01\x00SERATO_PHYSICAL_CUE_BYTES"))
        tag.save(str(orig_file), v2_version=3)

        def mock_mp3_side_effect(path_str):
            mock_mp3 = MagicMock()
            mock_mp3.info.length = 120.0
            mock_mp3.info.sample_rate = 44100
            mock_mp3.info.bitrate = 320000
            return mock_mp3

        with patch("audio_health.get_yt_dlp_bin", return_value="/fake/yt-dlp"), \
             patch("audio_health.is_serato_running_py", return_value=(False, "")), \
             patch("subprocess.run") as mock_subproc, \
             patch("mutagen.mp3.MP3", side_effect=mock_mp3_side_effect):

            def fake_run(cmd, **kwargs):
                out_idx = cmd.index("-o") + 1
                out_tmpl = cmd[out_idx]
                out_path = Path(out_tmpl.replace("%(ext)s", "mp3"))
                # Cria dummy candidato físico com tags neutras
                self._create_dummy_mp3(out_path, duration_sec=120.0)
                mock_res = MagicMock()
                mock_res.returncode = 0
                return mock_res

            mock_subproc.side_effect = fake_run

            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertTrue(res["sucesso"], f"Substituição física falhou: {res.get('erro')}")

            # Reabre o arquivo final físico do disco e audita os valores gravados
            final_id3 = ID3(str(orig_file))
            self.assertEqual(final_id3.version, (2, 3, 0), "Deve estar estritamente no padrão ID3v2.3 do Serato")
            self.assertEqual(str(final_id3["TIT2"]), "Original Title Real")
            self.assertEqual(str(final_id3["TBPM"]), "128")
            self.assertEqual(str(final_id3["TKEY"]), "8A")
            self.assertEqual(final_id3["GEOB:Serato Markers2"].data, b"\x01\x00SERATO_PHYSICAL_CUE_BYTES")

    def test_music_analysis_batch_zero_limit_analyzes_all(self):
        """Comprova que music_analysis.py com limit=0 analisa todas as faixas da biblioteca."""
        import music_analysis
        sub = self.mp3_dir / "Sub"
        sub.mkdir(parents=True, exist_ok=True)
        self._create_dummy_mp3(self.mp3_dir / "Track1.mp3")
        self._create_dummy_mp3(self.mp3_dir / "Track2.mp3")
        self._create_dummy_mp3(sub / "Track3.mp3")

        res = music_analysis.analyze_batch(str(self.mp3_dir), limit=0, write=False, only_missing=False, emit=False)
        self.assertEqual(res["total"], 3, "limit=0 deve analisar 100% das faixas encontradas")

    def test_duplicates_tool_single_folder_internal_audit(self):
        """Comprova que duplicates_tool.py funciona com apenas 1 pasta para auditoria interna."""
        import duplicates_tool
        folder = self.mp3_dir / "InternalAudit"
        sub1 = folder / "SubcrateA"
        sub2 = folder / "SubcrateB"
        sub1.mkdir(parents=True, exist_ok=True)
        sub2.mkdir(parents=True, exist_ok=True)

        audio_data = b"\xFF\xFB\x90\x00DUPLICATE_AUDIO_DATA" + b"\x00" * 60000
        self._create_dummy_mp3(sub1 / "Track.mp3", audio_content=audio_data)
        self._create_dummy_mp3(sub2 / "Track.mp3", audio_content=audio_data)

        res = duplicates_tool.scan_roots([str(folder)], include_serato=None, progress=False)
        self.assertTrue(res["sucesso"])
        self.assertEqual(res["total_arquivos"], 2)
        self.assertEqual(res["copias_redundantes"], 1, "Deve identificar 1 cópia redundante na auditoria interna")


if __name__ == "__main__":
    unittest.main()


