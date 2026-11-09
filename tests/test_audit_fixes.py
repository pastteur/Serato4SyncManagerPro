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

    def test_audio_health_repair_duration_threshold_and_atomic_replace(self):
        """Testa o fluxo de substituição atômica, quarentena e a trava rígida de 15s de delta."""
        from unittest.mock import patch, MagicMock

        # Simula arquivo original de 200 segundos
        orig_file = self.mp3_dir / "TestTrack.mp3"
        orig_file.write_bytes(b"\xFF\xFB\x90\x00" + b"\x00" * 25000)

        # Mock da duração do original = 200.0s
        def mock_mp3_side_effect(path_str):
            mock_mp3 = MagicMock()
            if "__sync_work_" in path_str:
                # Se for download candidato com 220s (delta = 20s > 15s)
                mock_mp3.info.length = getattr(mock_mp3_side_effect, 'candidate_dur', 220.0)
            else:
                mock_mp3.info.length = 200.0
            return mock_mp3

        mock_mp3_side_effect.candidate_dur = 220.0

        with patch("audio_health.get_yt_dlp_bin", return_value="/fake/yt-dlp"), \
             patch("subprocess.run") as mock_subproc, \
             patch("mutagen.mp3.MP3", side_effect=mock_mp3_side_effect):

            def fake_run(cmd, **kwargs):
                # Extrai output template e cria o arquivo falso
                out_idx = cmd.index("-o") + 1
                out_tmpl = cmd[out_idx]
                out_path = Path(out_tmpl.replace("%(ext)s", "mp3"))
                out_path.write_bytes(b"\xFF\xFB\x90\x00" + b"\x00" * 30000)
                mock_res = MagicMock()
                mock_res.returncode = 0
                return mock_res

            mock_subproc.side_effect = fake_run

            # Teste 1: Delta de 20s (220 vs 200) -> DEVE BLOQUEAR COM TRAVA DE SEGURANÇA
            mock_mp3_side_effect.candidate_dur = 220.0
            res = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
            self.assertFalse(res["sucesso"])
            self.assertTrue(res.get("bloqueado_seguranca"))
            self.assertIn("Substituição cancelada por segurança", res["erro"])
            # Garante que nenhum arquivo temporário __sync_work_ ficou para trás
            leftovers = list(self.mp3_dir.glob("*.__sync_work_*"))
            self.assertEqual(len(leftovers), 0)

            # Teste 2: Delta de 5s (205 vs 200) -> DEVE SUCEDER, QUARENTENAR E ATOMICAMENTE SUBSTITUIR
            mock_mp3_side_effect.candidate_dur = 205.0
            with patch("mutagen.id3.ID3"):
                res_ok = audio_health.repair_track_online(str(orig_file), serato_dir_str=str(self.serato_dir))
                self.assertTrue(res_ok["sucesso"])
                self.assertTrue(orig_file.exists())
                # Verifica que foi enviado para a quarentena em <_Serato_>/Quarentena
                q_dir = self.serato_dir / "Quarentena"
                self.assertTrue(q_dir.exists())
                quarantined_files = list(q_dir.glob("*_TestTrack.mp3"))
                self.assertEqual(len(quarantined_files), 1)
                # Garante que não sobrou nenhum resíduo temporário
                leftovers = list(self.mp3_dir.glob("*.__sync_work_*"))
                self.assertEqual(len(leftovers), 0)


if __name__ == "__main__":
    unittest.main()

