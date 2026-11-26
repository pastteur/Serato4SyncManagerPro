#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - MOTOR OFICIAL (serato_macos_app.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Motor de alta performance com auditoria binária estrita de crates,
preservação de ordenação original e blocos desconhecidos, trava matemática
anti-falso-positivo, caminhos relativos puros e conformidade total com o Serato 4.
================================================================================
"""

import sys
import os

sys.dont_write_bytecode = True
import struct
import shutil
import unicodedata
import csv
import datetime
import json
import argparse
import hashlib
import uuid
import base64
from pathlib import Path

# Garante flushing imediato de logs em stdout/stderr para captura em tempo real
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

# Vendor fallback: permite carregar dependências empacotadas sem exigir pip local
_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

DEFAULT_LOGS_DIR = Path(os.path.expanduser("~/SeratoSync/logs"))
AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')
IGNORED_SUBFOLDERS = {'contents', 'unknownalbum', 'unknownartist'}

# ==============================================================================
# UTILITÁRIOS BINÁRIOS E UNICODE DO SERATO DJ PRO 4
# ==============================================================================

def normalizar_nfc(texto: str) -> str:
    """Aplica normalização NFC estrita para compatibilidade total com o Serato 4."""
    if texto is None:
        return ""
    return unicodedata.normalize('NFC', str(texto))


def calcular_assinatura_pasta(arquivos_meta: list) -> str:
    """
    Gera uma assinatura hash SHA-256 matemática baseada estritamente nos metadados físicos:
    caminho_rel_nfc + nome_nfc + tamanho + mtime_ns + ctime_ns + st_dev + st_ino.
    Utiliza serialização não-ambígua:
    [len_caminho: uint32][caminho_bytes][len_nome: uint32][nome_bytes][5x uint64 BE: size, mtime, ctime, dev, ino].
    Nota: Esta assinatura atesta rigorosamente a imutabilidade dos metadados de arquivo no sistema de arquivos;
    ela não substitui a hash de áudio criptográfica para comprovação de conteúdo idêntico.
    """
    h = hashlib.sha256()
    for item in sorted(arquivos_meta, key=lambda x: x[0]):
        rel_nfc, nome_nfc, tamanho, mtime_ns, ctime_ns, dev, ino = item
        rel_bytes = rel_nfc.encode('utf-8')
        nome_bytes = nome_nfc.encode('utf-8')

        h.update(struct.pack('>II', len(rel_bytes), len(nome_bytes)))
        h.update(rel_bytes)
        h.update(nome_bytes)
        h.update(struct.pack(
            '>QQQQQ',
            max(0, int(tamanho)),
            max(0, int(mtime_ns)),
            max(0, int(ctime_ns)),
            max(0, int(dev)),
            max(0, int(ino))
        ))
    return h.hexdigest()


def compute_quick_audio_hash(filepath: Path) -> str:
    """
    Calcula hash SHA-256 do conteúdo do arquivo para comprovação de duplicatas.
    Ignora cabeçalho ID3v2 (início) e rodapé ID3v1 (últimos 128 bytes), de modo que
    duas cópias do mesmo áudio com tags diferentes continuem batendo.
    ATENÇÃO: o áudio não é decodificado, apenas os bytes são somados.
    """
    try:
        with open(filepath, 'rb') as f:
            header = f.read(10)
            start_offset = 0
            if len(header) == 10 and header[:3] == b'ID3':
                tag_size = ((header[6] & 0x7F) << 21) | ((header[7] & 0x7F) << 14) | ((header[8] & 0x7F) << 7) | (header[9] & 0x7F)
                start_offset = 10 + tag_size
                # Rodapé ID3v2 (flag 0x10) ocupa mais 10 bytes
                if header[5] & 0x10:
                    start_offset += 10

            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            end_offset = file_size
            if file_size > 128:
                f.seek(file_size - 128)
                if f.read(3) == b'TAG':
                    end_offset -= 128

            if end_offset <= start_offset:
                return ""

            h = hashlib.sha256()
            f.seek(start_offset)
            bytes_left = end_offset - start_offset
            while bytes_left > 0:
                chunk = f.read(min(bytes_left, 65536))
                if not chunk:
                    break
                h.update(chunk)
                bytes_left -= len(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def criar_tag_tlv(tag_str: str, valor_str: str) -> bytes:
    """Gera bloco binário TLV (Tag 4 bytes + Length big-endian + UTF-16 BE sem BOM)."""
    tag_bytes = tag_str.encode('ascii')
    valor_bytes = valor_str.encode('utf-16-be')
    tamanho_bytes = struct.pack('>I', len(valor_bytes))
    return tag_bytes + tamanho_bytes + valor_bytes


def parse_crate_binary(data: bytes, strict: bool = False):
    """
    Analisa estruturalmente um arquivo binário .crate do Serato.
    Retorna:
      header_bytes: Cabeçalho vrsn original preservado.
      faixas_ordenadas: Lista de caminhos relativos em sua ordem original no crate.
      blocos_otrk: Lista de tuplas (caminho_relativo, bloco_otrk_bytes).
      outros_blocos: Lista de blocos binários não-otrk preservados integralmente (ex: ovct, osrt).
    Rejeita estruturas truncadas, tamanhos inválidos ou bytes residuais não interpretáveis.
    """
    def _fail(msg: str):
        if strict:
            raise ValueError(msg)
        return None, [], [], []

    if not data or len(data) < 8 or not data.startswith(b'vrsn'):
        return _fail("Cabeçalho vrsn ausente ou inválido.")

    try:
        vrsn_len = struct.unpack('>I', data[4:8])[0]
        header_end = 8 + vrsn_len
        if header_end > len(data):
            return _fail(f"Cabeçalho vrsn truncado (esperado {header_end}, disponível {len(data)} bytes).")
        header_bytes = data[:header_end]
    except Exception as e:
        return _fail(f"Falha ao decodificar cabeçalho vrsn: {e}")

    faixas_ordenadas = []
    blocos_otrk = []
    outros_blocos = []

    idx = header_end
    total_len = len(data)

    while idx < total_len:
        if idx + 8 > total_len:
            return _fail(f"Bytes residuais não interpretáveis no final da crate ({total_len - idx} bytes).")

        tag = data[idx:idx+4]
        try:
            block_len = struct.unpack('>I', data[idx+4:idx+8])[0]
        except Exception as e:
            return _fail(f"Falha ao ler tamanho do bloco em offset {idx}: {e}")

        block_end = idx + 8 + block_len
        if block_end > total_len:
            return _fail(
                f"Bloco '{tag.decode('ascii', errors='replace')}' truncado "
                f"(esperado até {block_end}, arquivo tem {total_len} bytes)."
            )

        raw_block = data[idx:block_end]

        if tag == b'otrk':
            # Localiza ptrk dentro do bloco otrk de forma estruturada
            otrk_payload = data[idx+8:block_end]
            p_idx = 0
            found_ptrk = False
            while p_idx < len(otrk_payload):
                if p_idx + 8 > len(otrk_payload):
                    return _fail("Sub-bloco interno de 'otrk' truncado ou bytes residuais.")
                p_tag = otrk_payload[p_idx:p_idx+4]
                try:
                    p_len = struct.unpack('>I', otrk_payload[p_idx+4:p_idx+8])[0]
                except Exception as e:
                    return _fail(f"Falha ao ler tamanho de sub-bloco em 'otrk': {e}")
                p_end = p_idx + 8 + p_len
                if p_end > len(otrk_payload):
                    return _fail(
                        f"Sub-bloco '{p_tag.decode('ascii', errors='replace')}' truncado dentro de 'otrk'."
                    )
                if p_tag == b'ptrk':
                    try:
                        path_str = otrk_payload[p_idx+8:p_end].decode('utf-16-be')
                        norm_path = normalizar_nfc(path_str)
                        faixas_ordenadas.append(norm_path)
                        blocos_otrk.append((norm_path, raw_block))
                        found_ptrk = True
                    except UnicodeDecodeError as e:
                        return _fail(f"Caminho 'ptrk' com codificação UTF-16-BE inválida: {e}")
                p_idx = p_end

            if not found_ptrk:
                outros_blocos.append(raw_block)
        else:
            outros_blocos.append(raw_block)

        idx = block_end

    return header_bytes, faixas_ordenadas, blocos_otrk, outros_blocos


def ler_faixas_crate_binaria(caminho_crate: Path):
    """
    Lê uma .crate existente e extrai informações preservando ordem original e blocos adicionais.
    Retorna (faixas_set, faixas_lista_ordenada, outros_blocos, header_bytes).
    """
    if not caminho_crate.exists():
        return set(), [], [], None
    try:
        with open(caminho_crate, 'rb') as f:
            data = f.read()
        header, faixas, blocos_otrk, outros = parse_crate_binary(data)
        if header is not None:
            return set(faixas), faixas, outros, header
    except Exception as e:
        print(f"   ⚠️ Aviso ao ler crate prévia {caminho_crate.name}: {e}", flush=True)
    return set(), [], [], None


def parse_neworder_pref(data: bytes):
    """
    Analisa o arquivo neworder.pref extraindo a ordem configurada das crates
    e preservando quaisquer blocos desconhecidos.
    Retorna (header_bytes, ordered_crate_names, outros_blocos).
    """
    if len(data) < 8 or not data.startswith(b'vrsn'):
        return None, [], []

    try:
        vrsn_len = struct.unpack('>I', data[4:8])[0]
        header_end = 8 + vrsn_len
        if header_end > len(data):
            return None, [], []
        header = data[:header_end]
    except Exception:
        return None, [], []

    ordered_crates = []
    outros_blocos = []
    idx = header_end
    total_len = len(data)

    while idx + 8 <= total_len:
        tag = data[idx:idx+4]
        try:
            block_len = struct.unpack('>I', data[idx+4:idx+8])[0]
        except Exception:
            break
        block_end = idx + 8 + block_len
        if block_end > total_len:
            break
        raw_block = data[idx:block_end]

        if tag == b'nior':
            nior_payload = data[idx+8:block_end]
            if len(nior_payload) >= 8 and nior_payload[:4] == b'tvcn':
                try:
                    tvcn_len = struct.unpack('>I', nior_payload[4:8])[0]
                    if 8 + tvcn_len <= len(nior_payload):
                        c_name = nior_payload[8:8+tvcn_len].decode('utf-16-be')
                        ordered_crates.append(normalizar_nfc(c_name))
                        idx = block_end
                        continue
                except Exception:
                    pass
        outros_blocos.append(raw_block)
        idx = block_end

    return header, ordered_crates, outros_blocos


def carregar_cache(cache_file: Path, expected_lib: str = None) -> dict:
    if not cache_file.exists():
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Validação de escopo: garante que o cache pertence à biblioteca atual
            meta = data.get("_meta", {})
            if expected_lib and meta.get("lib_path") != expected_lib:
                return {}
            return data.get("crates", data)
    except Exception:
        return {}


def salvar_cache(cache_file: Path, dados: dict, lib_path: str = None, st_dev: int = 0) -> bool:
    tmp = cache_file.with_name(f".tmp_{cache_file.name}_{os.getpid()}")
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_meta": {
                "lib_path": lib_path or "",
                "st_dev": st_dev,
                "timestamp": datetime.datetime.now().isoformat(),
                "engine": "Serato4SyncPro-v4.1"
            },
            "crates": dados
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, cache_file)
        return True
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        print(f"⚠️ Erro ao salvar cache: {e}", file=sys.stderr, flush=True)
        return False


# ==============================================================================
# MOTOR ROBUSTO DE SINCRONIZAÇÃO E AUDITORIA
# ==============================================================================

def _sha256_file(filepath: Path) -> str:
    """Calcula SHA-256 integral de um arquivo em disco para validação de plano imutável."""
    try:
        if not filepath.exists() or not filepath.is_file():
            return ""
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _compute_library_id(path_mp3: Path, path_serato: Path) -> str:
    """Identificador determinístico da biblioteca baseado nos caminhos canônicos."""
    raw = f"{path_mp3.resolve()}|{path_serato.resolve()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _resolve_raiz_relativa(path_mp3: Path, path_serato: Path) -> Path:
    """Determina a raiz relativa de forma consistente para volumes externos, Home e layouts personalizados."""
    serato_resolved = path_serato.resolve()
    mp3_resolved = path_mp3.resolve()

    if str(serato_resolved).startswith("/Volumes/"):
        return serato_resolved.parent
    try:
        home_resolved = Path.home().resolve()
        if mp3_resolved.is_relative_to(home_resolved):
            return home_resolved
    except Exception:
        pass
    try:
        if mp3_resolved.is_relative_to(serato_resolved.parent):
            return serato_resolved.parent
    except Exception:
        pass
    return mp3_resolved.parent


def _build_plan_hash(plan_payload: dict) -> str:
    """Gera hash SHA-256 canônico do plano de execução."""
    clean = {k: v for k, v in plan_payload.items() if k != "plan_hash"}
    encoded = json.dumps(clean, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _scan_audio_files_snapshot(path_mp3: Path) -> tuple:
    """Coleta snapshot determinístico dos arquivos de áudio atuais (abs_path, size, mtime_ns, sha256)."""
    snapshot = {}
    erros = []

    def _on_err(os_err):
        erros.append(str(os_err))

    for raiz, _, arquivos in os.walk(str(path_mp3), onerror=_on_err):
        caminho_atual = Path(raiz)
        if any(part.startswith('.') for part in caminho_atual.parts):
            continue
        for arq in arquivos:
            if arq.startswith('._') or arq.startswith('.'):
                continue
            caminho_completo = caminho_atual / arq
            if caminho_completo.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            if caminho_completo.is_symlink() and not caminho_completo.exists():
                continue
            try:
                st = caminho_completo.stat()
                abs_str = normalizar_nfc(str(caminho_completo.resolve()))
                snapshot[abs_str] = {
                    "abs_path": abs_str,
                    "size": st.st_size,
                    "mtime_ns": getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)),
                    "sha256": _sha256_file(caminho_completo),
                }
            except OSError as e:
                erros.append(f"{caminho_completo}: {e}")
    return snapshot, erros


def sincronizar_biblioteca(mp3_dir_str: str, serato_dir_str: str, logs_dir_str: str = None, 
                           export_csv: bool = True, emit_json_summary: bool = False,
                           dry_run: bool = False, plan: dict = None, plan_file: str = None):
    
    if dry_run:
        print("\n🔍 [SERATO 4 SYNC PRO] - MODO ANÁLISE / PRÉ-AVALIAÇÃO ATIVADO (SOMENTE LEITURA) 🔍", flush=True)
        print("💡 Nenhuma alteração física (.crate, .pref, .json ou logs) será gravada em disco.\n", flush=True)
    else:
        print("\n⚡ [SERATO 4 SYNC MANAGER PRO] - INICIANDO AUDITORIA E SINCRONIZAÇÃO NATIVA ⚡", flush=True)

    if not mp3_dir_str or not mp3_dir_str.strip():
        print("❌ ERRO CRÍTICO: Caminho da pasta de músicas MP3 não informado.", flush=True)
        return False, "Caminho MP3 não informado."
    if not serato_dir_str or not serato_dir_str.strip():
        print("❌ ERRO CRÍTICO: Caminho da pasta Serato não informado.", flush=True)
        return False, "Caminho Serato não informado."

    path_mp3 = Path(os.path.expanduser(mp3_dir_str.strip())).resolve()
    path_serato = Path(os.path.expanduser(serato_dir_str.strip())).resolve()
    path_logs = Path(os.path.expanduser(logs_dir_str or str(DEFAULT_LOGS_DIR))).resolve()

    # Blindagem de segurança: previne escanear raiz do sistema, Home ou Desktop
    desktop_path = (Path.home() / "Desktop").resolve()
    if path_mp3 in (Path.home().resolve(), desktop_path, Path("/").resolve()):
        print(f"❌ ERRO DE SEGURANÇA: O caminho fornecido aponta para pasta do sistema ({path_mp3}). Operação cancelada.", flush=True)
        return False, "Caminho do sistema bloqueado por segurança."

    print(f"📂 Pasta Master MP3  : {path_mp3}", flush=True)
    print(f"📂 Pasta Serato      : {path_serato}", flush=True)
    print(f"📂 Diretório de Logs : {path_logs}\n", flush=True)

    if not path_mp3.exists() or not path_mp3.is_dir():
        print(f"❌ ERRO CRÍTICO: A pasta de músicas informada não existe ou não é diretório: {path_mp3}", flush=True)
        return False, "Pasta MP3 não encontrada."

    crates_dir = path_serato / "Subcrates"

    # No Dry-Run: NÃO cria diretórios fisicamente em disco!
    if not dry_run:
        crates_dir.mkdir(parents=True, exist_ok=True)
        path_logs.mkdir(parents=True, exist_ok=True)

    # Identifica crates físicas antigas presentes no disco
    crates_fisicas_antigas = set()
    if crates_dir.exists():
        crates_fisicas_antigas = set([
            normalizar_nfc(f.name) 
            for f in crates_dir.glob("*.crate") 
            if not f.name.startswith('.') and not f.name.endswith('.bak') and not f.name.endswith('.tmp')
        ])

    cache_file = path_logs / ".serato_sync_cache.json"
    cache_anterior = carregar_cache(cache_file, expected_lib=str(path_mp3)) if not dry_run else {}
    novo_cache = {}

    crates_masters = set()
    mapa_subcrates = {}
    mapa_crates_arvore = {}
    relatorio_duplicados = []
    arquivos_vistos = {}  # chave -> info
    crates_processadas_agora = set()

    total_faixas = 0
    total_crates_gravadas = 0
    crates_inalteradas = 0
    total_faixas_adicionadas = 0
    total_faixas_removidas = 0
    movimentacoes_log = []

    erros_leitura = []
    erros_gravacao = []
    varredura_incompleta = False
    planos_gravacao = []
    broken_symlinks = []
    fases_executadas = []
    rollback_executado = False
    estado_parcial = False
    sync_journal_id = None
    plan_invalidated = False
    arquivos_plan_records = []
    crates_para_deletar = []
    crates_novas = []
    lista_pref_final_from_plan = None
    executando_plano_imutavel = (not dry_run) and (plan is not None or plan_file is not None)

    if not dry_run:
        try:
            import journal
            sync_journal_id = journal.record_sync_start(str(path_mp3), str(path_serato), dry_run=False)
        except Exception as e_j:
            erros_gravacao.append(f"Falha ao iniciar registro no Journal: {e_j}")

    def _log_fase(fase: str, status: str, detalhes: str = None):
        fases_executadas.append({"fase": fase, "status": status, "detalhes": detalhes})
        if not dry_run and sync_journal_id:
            try:
                import journal
                journal.record_sync_step(sync_journal_id, fase, status, detalhes)
            except Exception as e_js:
                erros_gravacao.append(f"Falha ao registrar fase '{fase}' no Journal: {e_js}")

    # ==========================================================================
    # FASE 1 & 2: EXECUÇÃO DE PLANO IMUTÁVEL OU VARREDURA + PLANEJAMENTO
    # ==========================================================================
    raiz_relativa = _resolve_raiz_relativa(path_mp3, path_serato)

    if executando_plano_imutavel:
        _log_fase("validacao_plano", "iniciada")
        plan_obj = plan
        if plan_obj is None and plan_file:
            try:
                with open(plan_file, "r", encoding="utf-8") as pf:
                    plan_obj = json.load(pf)
            except Exception as e_pf:
                plan_invalidated = True
                err_p = f"Falha ao carregar arquivo de plano '{plan_file}': {e_pf}"
                erros_gravacao.append(err_p)
                print(f"❌ PLANO INVALIDADO: {err_p}", file=sys.stderr, flush=True)
                plan_obj = None

        if plan_obj is not None:
            expected_hash = plan_obj.get("plan_hash", "")
            computed_hash = _build_plan_hash(plan_obj)
            if not expected_hash or expected_hash != computed_hash:
                plan_invalidated = True
                erros_gravacao.append("PLANO INVALIDADO: assinatura hash do plano não confere (plano adulterado ou corrompido).")
            elif str(Path(plan_obj.get("mp3_dir", "")).resolve()) != str(path_mp3) or str(Path(plan_obj.get("serato_dir", "")).resolve()) != str(path_serato):
                plan_invalidated = True
                erros_gravacao.append("PLANO INVALIDADO: caminhos da biblioteca divergem do plano aprovado.")
            else:
                # Verifica integridade de todos os arquivos e hashes em relação à prévia
                current_files, scan_errs = _scan_audio_files_snapshot(path_mp3)
                if scan_errs:
                    plan_invalidated = True
                    erros_gravacao.append(f"PLANO INVALIDADO: erro ao verificar arquivos da biblioteca: {scan_errs[0]}")
                else:
                    planned_files = {
                        normalizar_nfc(item["abs_path"]): item
                        for item in plan_obj.get("files", [])
                    }
                    if set(current_files.keys()) != set(planned_files.keys()):
                        added = len(set(current_files.keys()) - set(planned_files.keys()))
                        removed = len(set(planned_files.keys()) - set(current_files.keys()))
                        plan_invalidated = True
                        erros_gravacao.append(
                            f"PLANO INVALIDADO: a biblioteca foi modificada após a análise (+{added} arquivo(s), -{removed} arquivo(s)). Execute uma nova Análise."
                        )
                    else:
                        for abs_p, p_meta in planned_files.items():
                            c_meta = current_files[abs_p]
                            if (
                                c_meta["size"] != p_meta.get("size")
                                or c_meta["mtime_ns"] != p_meta.get("mtime_ns")
                                or c_meta["sha256"] != p_meta.get("sha256")
                            ):
                                plan_invalidated = True
                                erros_gravacao.append(
                                    f"PLANO INVALIDADO: arquivo modificado após a análise ({Path(abs_p).name}). Execute uma nova Análise."
                                )
                                break

                # Verifica integridade das crates-alvo e neworder.pref
                if not plan_invalidated:
                    for cw in plan_obj.get("crates_to_write", []):
                        c_path = Path(cw["caminho_crate"])
                        expected_c_hash = cw.get("crate_sha256_before")
                        actual_c_hash = _sha256_file(c_path) if c_path.exists() else None
                        if actual_c_hash != expected_c_hash:
                            plan_invalidated = True
                            erros_gravacao.append(
                                f"PLANO INVALIDADO: crate '{c_path.name}' foi modificada externamente após a análise."
                            )
                            break

                if not plan_invalidated:
                    for cd in plan_obj.get("crates_to_delete", []):
                        c_path = Path(cd["caminho_crate"])
                        expected_d_hash = cd.get("sha256_before")
                        actual_d_hash = _sha256_file(c_path) if c_path.exists() else None
                        if actual_d_hash != expected_d_hash:
                            plan_invalidated = True
                            erros_gravacao.append(
                                f"PLANO INVALIDADO: crate '{c_path.name}' para remoção foi alterada externamente após a análise."
                            )
                            break

                if not plan_invalidated:
                    pref_path = path_serato / "neworder.pref"
                    expected_pref_hash = plan_obj.get("neworder_pref_before_sha256")
                    actual_pref_hash = _sha256_file(pref_path) if pref_path.exists() else None
                    if actual_pref_hash != expected_pref_hash:
                        plan_invalidated = True
                        erros_gravacao.append("PLANO INVALIDADO: neworder.pref foi modificado externamente após a análise.")

        if plan_invalidated or erros_gravacao:
            _log_fase("validacao_plano", "falha", "; ".join(erros_gravacao))
            for err_msg in erros_gravacao:
                print(f"   ❌ {err_msg}", file=sys.stderr, flush=True)
        else:
            _log_fase("validacao_plano", "concluida", f"Plano {plan_obj.get('plan_id')} validado")
            print(f"🔒 Plano imutável validado: {plan_obj.get('plan_id')}", flush=True)
            for cw in plan_obj.get("crates_to_write", []):
                hdr_b64 = cw.get("header_antigo_b64")
                hdr_bytes = base64.b64decode(hdr_b64) if hdr_b64 else None
                outros_b = [base64.b64decode(b) for b in cw.get("outros_blocos_b64", [])]
                planos_gravacao.append({
                    "caminho_crate": Path(cw["caminho_crate"]),
                    "nome_crate": cw["nome_crate"],
                    "nome_exibicao": cw["nome_exibicao"],
                    "faixas_finais_ordenadas": list(cw["faixas_finais_ordenadas"]),
                    "header_antigo": hdr_bytes,
                    "outros_blocos": outros_b,
                    "chave_cache": cw["chave_cache"],
                    "qtd_arquivos": cw["qtd_arquivos"],
                    "tamanho_total_pasta": cw["tamanho_total_pasta"],
                    "sig_pasta": cw["sig_pasta"],
                    "faixas_adicionadas": set(cw.get("faixas_adicionadas", [])),
                    "faixas_removidas": set(cw.get("faixas_removidas", [])),
                })
            crates_para_deletar = [cd["nome_arquivo"] for cd in plan_obj.get("crates_to_delete", [])]
            crates_novas = list(plan_obj.get("crates_novas", []))
            crates_masters = set(plan_obj.get("crates_masters", []))
            mapa_subcrates = {k: set(v) for k, v in plan_obj.get("mapa_subcrates", {}).items()}
            total_faixas = int(plan_obj.get("total_faixas", 0))
            crates_inalteradas = int(plan_obj.get("crates_inalteradas", 0))
            mapa_crates_arvore = plan_obj.get("mapa_crates_arvore", {})
            relatorio_duplicados = plan_obj.get("relatorio_duplicados", [])
            lista_pref_final_from_plan = plan_obj.get("neworder_pref_list")
            if isinstance(plan_obj.get("novo_cache"), dict):
                novo_cache.update(plan_obj["novo_cache"])

    if not executando_plano_imutavel:
        _log_fase("varredura", "iniciada")

        print(f"🔗 Raiz de Cálculo Relativo: {raiz_relativa}", flush=True)
        print("🔍 Realizando varredura profunda e auditoria de binários...\n", flush=True)

        def on_walk_error(os_error):
            nonlocal varredura_incompleta
            varredura_incompleta = True
            err_msg = f"Falha de acesso ao ler diretório: {os_error}"
            erros_leitura.append(err_msg)
            print(f"   ⚠️ [ERRO DE I/O] {err_msg}", file=sys.stderr, flush=True)

        for raiz, _, arquivos in os.walk(str(path_mp3), onerror=on_walk_error):
            caminho_atual = Path(raiz)

            # Filtro de arquivos ocultos do macOS (._*, .DS_Store, .Trash)
            if any(part.startswith('.') for part in caminho_atual.parts):
                continue

            musicas_pasta_relativas = []
            arquivos_abs_map = {}
            arquivos_pasta_meta = []
            tamanho_total_pasta = 0

            for arq in arquivos:
                if arq.startswith('._') or arq.startswith('.'):
                    continue

                caminho_completo = caminho_atual / arq
                if caminho_completo.suffix.lower() in AUDIO_EXTENSIONS:
                    if caminho_completo.is_symlink() and not caminho_completo.exists():
                        if not dry_run:
                            broken_symlinks.append(caminho_completo)
                        continue

                    try:
                        st = caminho_completo.stat()
                        tamanho = st.st_size
                        mtime_ns = getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9))
                        ctime_ns = getattr(st, 'st_ctime_ns', int(st.st_ctime * 1e9))
                        st_dev = st.st_dev
                        st_ino = st.st_ino
                    except OSError as e:
                        # Falha de leitura em arquivo: NÃO converte em 0/0!
                        varredura_incompleta = True
                        erros_leitura.append(f"Erro ao consultar stat({caminho_completo.name}): {e}")
                        print(f"   ⚠️ [FALHA DE LEITURA] Impossível acessar metadados de {caminho_completo.name}: {e}", file=sys.stderr, flush=True)
                        continue

                    tamanho_total_pasta += tamanho
                    nome_nfc = normalizar_nfc(arq)
                    abs_resolved_str = normalizar_nfc(str(caminho_completo.resolve()))

                    # Regra de caminho relativo estrito (separado do caminho absoluto real)
                    try:
                        relativo = caminho_completo.resolve().relative_to(raiz_relativa)
                        relativo_str = normalizar_nfc(str(relativo))
                    except ValueError:
                        try:
                            relativo = caminho_completo.resolve().relative_to(path_mp3)
                            relativo_str = normalizar_nfc(str(relativo))
                        except ValueError:
                            relativo_str = abs_resolved_str

                    musicas_pasta_relativas.append(relativo_str)
                    arquivos_abs_map[relativo_str] = abs_resolved_str
                    arquivos_pasta_meta.append((relativo_str, nome_nfc, tamanho, mtime_ns, ctime_ns, st_dev, st_ino))

                    if dry_run:
                        arquivos_plan_records.append({
                            "abs_path": abs_resolved_str,
                            "rel_path": relativo_str,
                            "size": tamanho,
                            "mtime_ns": mtime_ns,
                            "sha256": _sha256_file(caminho_completo),
                        })

                    # Auditoria precisa de duplicidades
                    chave_duplicado = (nome_nfc, tamanho)
                    if chave_duplicado in arquivos_vistos:
                        info_orig = arquivos_vistos[chave_duplicado]
                        orig_path = Path(info_orig["caminho"])

                        # Confirmação exata por hash do fluxo de áudio
                        h_atual = compute_quick_audio_hash(caminho_completo)
                        h_orig = info_orig.get("hash_audio") or compute_quick_audio_hash(orig_path)
                        info_orig["hash_audio"] = h_orig

                        if h_atual and h_orig and h_atual == h_orig:
                            grau = "IDENTICO_COMPROVADO"
                            motivo = "Conteúdo de áudio binário 100% idêntico (mesmo hash SHA-256 do fluxo de áudio)."
                        elif h_atual and h_orig and h_atual != h_orig:
                            grau = "POSSIVEL_DUPLICADO"
                            motivo = "Mesmo nome e tamanho de arquivo, porém fluxos de áudio divergem."
                        else:
                            grau = "POSSIVEL_DUPLICADO"
                            motivo = "Mesmo nome e tamanho de arquivo (verificação de áudio pendente)."

                        relatorio_duplicados.append({
                            "id": f"dup-{len(relatorio_duplicados)+1}",
                            "nome": arq,
                            "copia": str(caminho_atual),
                            "original": str(info_orig["pasta"]),
                            "caminho_copia": str(caminho_completo),
                            "caminho_original": str(info_orig["caminho"]),
                            "tamanho": tamanho,
                            "grau_certeza": grau,
                            "motivo": motivo,
                            "hash_audio": h_atual
                        })
                    else:
                        arquivos_vistos[chave_duplicado] = {
                            "pasta": caminho_atual,
                            "caminho": caminho_completo,
                            "hash_audio": None
                        }

            if musicas_pasta_relativas:
                try:
                    rel_pasta = caminho_atual.relative_to(path_mp3)
                    partes = rel_pasta.parts
                except ValueError:
                    partes = [caminho_atual.name]

                if not partes:
                    continue

                partes_limpas = [normalizar_nfc(p) for p in partes if p.lower() not in IGNORED_SUBFOLDERS]
                if not partes_limpas:
                    continue

                master = partes_limpas[0]
                crates_masters.add(master)

                nome_crate = "%%".join(partes_limpas)
                nome_exibicao = " -> ".join(partes_limpas)
                if len(partes_limpas) > 1:
                    if master not in mapa_subcrates:
                        mapa_subcrates[master] = set()
                    mapa_subcrates[master].add("%%".join(partes_limpas[1:]))

                nome_arquivo_crate = f"{nome_crate}.crate"
                caminho_crate = crates_dir / nome_arquivo_crate
                crates_processadas_agora.add(nome_arquivo_crate)
                total_faixas += len(musicas_pasta_relativas)

                mapa_crates_arvore[nome_crate] = {
                    "nome_crate": nome_crate,
                    "nome_exibicao": nome_exibicao,
                    "master": master,
                    "subcrate": "%%".join(partes_limpas[1:]) if len(partes_limpas) > 1 else "",
                    "total_faixas": len(musicas_pasta_relativas),
                    "faixas": [
                        {
                            "nome": Path(f_rel).name,
                            "caminho_rel": f_rel,
                            "caminho_abs": arquivos_abs_map.get(f_rel, normalizar_nfc(str((path_mp3 / f_rel).resolve()))),
                            "formato": Path(f_rel).suffix.upper().replace('.', ''),
                        }
                        for f_rel in musicas_pasta_relativas
                    ]
                }

                # Assinatura física rigorosa dos metadados dos arquivos
                chave_cache = normalizar_nfc(str(caminho_atual.resolve()))
                qtd_arquivos = len(musicas_pasta_relativas)
                sig_pasta = calcular_assinatura_pasta(arquivos_pasta_meta)

                crate_existe = caminho_crate.exists()
                crate_tamanho = 0
                if crate_existe:
                    try:
                        c_stat = caminho_crate.stat()
                        crate_tamanho = c_stat.st_size
                    except OSError:
                        pass

                dados_prev_cache = cache_anterior.get(chave_cache) if cache_anterior else None
                cache_perfeito = (
                    not dry_run and
                    dados_prev_cache is not None and
                    dados_prev_cache.get("sig") == sig_pasta and
                    dados_prev_cache.get("qtd") == qtd_arquivos and
                    dados_prev_cache.get("bytes") == tamanho_total_pasta and
                    crate_existe and
                    crate_tamanho > 8 and
                    dados_prev_cache.get("crate_bytes") == crate_tamanho
                )

                if cache_perfeito:
                    novo_cache[chave_cache] = dados_prev_cache
                    crates_inalteradas += 1
                    continue

                # Leitura estrutural do crate preservando ordem existente e blocos desconhecidos
                faixas_antigas_set, faixas_antigas_ordenadas, outros_blocos, header_antigo = ler_faixas_crate_binaria(caminho_crate)
                conjunto_novo = set(musicas_pasta_relativas)

                faixas_adicionadas = conjunto_novo - faixas_antigas_set
                faixas_removidas = faixas_antigas_set - conjunto_novo

                # Preserva ordenação original: mantém faixas que já existiam na mesma ordem, adiciona novas no final
                if faixas_antigas_ordenadas:
                    faixas_finais_ordenadas = [f for f in faixas_antigas_ordenadas if f in conjunto_novo]
                    novas_para_adicionar = [f for f in musicas_pasta_relativas if f not in set(faixas_finais_ordenadas)]
                    faixas_finais_ordenadas.extend(novas_para_adicionar)
                else:
                    faixas_finais_ordenadas = list(musicas_pasta_relativas)

                planos_gravacao.append({
                    "caminho_crate": caminho_crate,
                    "nome_crate": nome_crate,
                    "nome_exibicao": nome_exibicao,
                    "faixas_finais_ordenadas": faixas_finais_ordenadas,
                    "header_antigo": header_antigo,
                    "outros_blocos": outros_blocos,
                    "chave_cache": chave_cache,
                    "qtd_arquivos": qtd_arquivos,
                    "tamanho_total_pasta": tamanho_total_pasta,
                    "sig_pasta": sig_pasta,
                    "faixas_adicionadas": faixas_adicionadas,
                    "faixas_removidas": faixas_removidas,
                })

        # ==========================================================================
        # FASE 2: PLANEJAMENTO
        # ==========================================================================
        if varredura_incompleta:
            _log_fase("varredura", "falha", f"{len(erros_leitura)} erro(s) de leitura")
            _log_fase("planejamento", "cancelado", "Varredura incompleta")
            print(
                f"\n🛡️ [PROTEÇÃO DE INTEGRIDADE] Varredura incompleta ({len(erros_leitura)} erro(s)). "
                "Fases seguintes canceladas: nenhuma crate foi modificada ou removida.",
                flush=True
            )
        else:
            _log_fase("varredura", "concluida", f"{total_faixas} faixas mapeadas")
            crates_para_deletar = [
                antiga for antiga in sorted(list(crates_fisicas_antigas))
                if antiga not in crates_processadas_agora
            ]
            crates_novas = [
                nova for nova in sorted(list(crates_processadas_agora))
                if nova not in crates_fisicas_antigas
            ]
            _log_fase(
                "planejamento",
                "concluida",
                f"{len(planos_gravacao)} crate(s) para gravar, {len(crates_para_deletar)} para remover, {len(crates_novas)} nova(s)"
            )

    # ==========================================================================
    # FASE 3: VALIDAÇÃO PRÉVIA
    # ==========================================================================
    validacao_previa_ok = (not varredura_incompleta) and (not erros_gravacao)
    if validacao_previa_ok and not dry_run:
        try:
            if not crates_dir.exists() or not os.access(str(crates_dir), os.W_OK):
                raise PermissionError(f"Diretório de crates sem permissão de escrita: {crates_dir}")
            for plano in planos_gravacao:
                if not plano.get("nome_crate"):
                    raise ValueError("Plano de gravação contém crate sem nome.")
                for tr in plano.get("faixas_finais_ordenadas", []):
                    if not isinstance(tr, str) or not tr.strip():
                        raise ValueError(f"Caminho de faixa inválido no plano da crate {plano['nome_crate']}.")
            _log_fase("validacao_previa", "concluida")
        except Exception as e_val:
            validacao_previa_ok = False
            err_val = f"Falha na validação prévia: {e_val}"
            erros_gravacao.append(err_val)
            _log_fase("validacao_previa", "falha", err_val)
            print(f"\n❌ [VALIDAÇÃO PRÉVIA] {err_val}", file=sys.stderr, flush=True)
    elif validacao_previa_ok and dry_run:
        _log_fase("validacao_previa", "simulada")
    else:
        _log_fase("validacao_previa", "cancelada")

    # ==========================================================================
    # FASE 4: GRAVAÇÃO TRANSACIONAL (CRATES)
    # ==========================================================================
    crates_gravadas_nesta_sessao = []
    if validacao_previa_ok:
        import crate_ops

        prefixo_log = "🔍 [ANÁLISE] " if dry_run else ""
        _log_fase("gravacao", "iniciada" if not dry_run else "simulada")

        for plano in planos_gravacao:
            caminho_crate = plano["caminho_crate"]
            nome_crate = plano["nome_crate"]
            nome_exibicao = plano["nome_exibicao"]
            faixas_adicionadas = plano["faixas_adicionadas"]
            faixas_removidas = plano["faixas_removidas"]
            qtd_arquivos = plano["qtd_arquivos"]

            if faixas_adicionadas:
                total_faixas_adicionadas += len(faixas_adicionadas)
                msg_add = f"{prefixo_log}🆕 {len(faixas_adicionadas)} nova(s) faixa(s) para a Crate [{nome_exibicao}]"
                print(f"   {msg_add}", flush=True)
                movimentacoes_log.append(msg_add)
                for f_item in sorted(list(faixas_adicionadas))[:3]:
                    print(f"      + {Path(f_item).name}", flush=True)
                if len(faixas_adicionadas) > 3:
                    print(f"      ... (+{len(faixas_adicionadas) - 3} outras faixas)", flush=True)

            if faixas_removidas:
                total_faixas_removidas += len(faixas_removidas)
                msg_rem = f"{prefixo_log}🗑️ {len(faixas_removidas)} faixa(s) removida(s) da Crate [{nome_exibicao}]"
                print(f"   {msg_rem}", flush=True)
                movimentacoes_log.append(msg_rem)
                for f_item in sorted(list(faixas_removidas))[:3]:
                    print(f"      - {Path(f_item).name}", flush=True)
                if len(faixas_removidas) > 3:
                    print(f"      ... (-{len(faixas_removidas) - 3} outras faixas)", flush=True)

            if not dry_run:
                res = crate_ops.write_crate_atomic(
                    caminho_crate,
                    plano["faixas_finais_ordenadas"],
                    header_antigo=plano["header_antigo"],
                    outros_blocos=plano["outros_blocos"],
                    action_name="sync_crate"
                )
                if res.get("sucesso"):
                    total_crates_gravadas += 1
                    crates_gravadas_nesta_sessao.append({
                        "caminho_crate": caminho_crate,
                        "sobrescrita": bool(res.get("sobrescrita")),
                        "backup": res.get("backup"),
                        "hash_anterior": res.get("hash_anterior"),
                        "qtd_esperada": len(plano["faixas_finais_ordenadas"]),
                    })
                    try:
                        tamanho_gravado = caminho_crate.stat().st_size
                    except OSError:
                        tamanho_gravado = 0
                    novo_cache[plano["chave_cache"]] = {
                        "qtd": qtd_arquivos,
                        "bytes": plano["tamanho_total_pasta"],
                        "sig": plano["sig_pasta"],
                        "crate_bytes": tamanho_gravado
                    }
                    if not faixas_adicionadas and not faixas_removidas:
                        print(f"   🔹 Crate atualizada: {nome_exibicao} ({qtd_arquivos} faixas)", flush=True)
                else:
                    err_msg = res.get("erro", f"Falha desconhecida ao gravar crate {nome_crate}")
                    erros_gravacao.append(err_msg)
                    print(f"   ❌ Erro ao gravar crate {nome_crate}: {err_msg}", file=sys.stderr, flush=True)
                    print("   🛑 Interrompendo gravações restantes para preservar integridade transacional.", file=sys.stderr, flush=True)
                    break
            else:
                total_crates_gravadas += 1
                if not faixas_adicionadas and not faixas_removidas:
                    print(f"   🔍 [ANÁLISE] Crate seria atualizada: {nome_exibicao} ({qtd_arquivos} faixas)", flush=True)

        if not dry_run and erros_gravacao:
            _log_fase("gravacao", "falha", "; ".join(erros_gravacao))
        elif not dry_run:
            _log_fase("gravacao", "concluida", f"{total_crates_gravadas} crate(s) gravada(s)")

    # ==========================================================================
    # FASE 5: VERIFICAÇÃO, STAGING DE EXCLUSÕES, neworder.pref E CACHE
    # ==========================================================================
    staging_dir = None
    crates_em_staging = []  # lista de (orig_path, staged_path)
    pref_foi_alterado = False
    pref_existed_before = False
    pref_orig_bytes = None
    cache_foi_alterado = False
    cache_existed_before = False
    cache_orig_bytes = None

    def _restaurar_arquivo_atomico(target_path: Path, existed_before: bool, orig_bytes: bytes, label: str):
        try:
            if existed_before and orig_bytes is not None:
                tmp_r = target_path.with_name(f".tmp_rb_{target_path.name}_{os.getpid()}")
                with open(tmp_r, 'wb') as rf:
                    rf.write(orig_bytes)
                    rf.flush()
                    os.fsync(rf.fileno())
                os.replace(tmp_r, target_path)
            elif not existed_before and target_path.exists():
                target_path.unlink()
            return None
        except Exception as e_r:
            return f"Falha ao reverter {label}: {e_r}"

    def _executar_rollback_global():
        nonlocal rollback_executado, estado_parcial
        if rollback_executado:
            return
        rollback_falhas = []

        # 1. Reverter cache se foi alterado nesta sessão
        if cache_foi_alterado:
            err_c = _restaurar_arquivo_atomico(cache_file, cache_existed_before, cache_orig_bytes, "cache")
            if err_c:
                rollback_falhas.append(err_c)

        # 2. Reverter neworder.pref se foi alterado nesta sessão
        if pref_foi_alterado:
            err_p = _restaurar_arquivo_atomico(neworder_file, pref_existed_before, pref_orig_bytes, "neworder.pref")
            if err_p:
                rollback_falhas.append(err_p)

        # 3. Restaurar crates antigas movidas para staging
        for orig_p, staged_p in reversed(crates_em_staging):
            try:
                if staged_p.exists():
                    os.replace(str(staged_p), str(orig_p))
            except Exception as e_st:
                rollback_falhas.append(f"Falha ao restaurar crate antiga '{orig_p.name}' do staging: {e_st}")
        if staging_dir and staging_dir.exists():
            try:
                staging_dir.rmdir()
            except Exception:
                pass

        # 4. Reverter crates gravadas nesta sessão
        for item_grav in reversed(crates_gravadas_nesta_sessao):
            c_path = item_grav["caminho_crate"]
            if item_grav["sobrescrita"] and item_grav.get("backup"):
                rb_ok, rb_msg = crate_ops.restore_crate_from_backup_atomic(
                    c_path,
                    Path(item_grav["backup"]),
                    expected_hash=item_grav.get("hash_anterior"),
                )
                if not rb_ok:
                    rollback_falhas.append(rb_msg)
            elif not item_grav["sobrescrita"] and c_path.exists():
                try:
                    c_path.unlink()
                except Exception as e_unlink:
                    rollback_falhas.append(f"Falha ao remover crate recém-criada {c_path.name}: {e_unlink}")

        rollback_executado = True
        if rollback_falhas:
            estado_parcial = True
            erros_gravacao.extend(rollback_falhas)
            _log_fase("rollback_sessao", "parcial", "; ".join(rollback_falhas))
        else:
            _log_fase(
                "rollback_sessao",
                "concluido",
                f"{len(crates_gravadas_nesta_sessao)} gravada(s) e {len(crates_em_staging)} antiga(s) revertida(s)"
            )

    if not dry_run and not varredura_incompleta and not erros_gravacao:
        # 5.1 Verificação pós-gravação de todas as crates gravadas nesta sessão
        for item_grav in crates_gravadas_nesta_sessao:
            c_path = item_grav["caminho_crate"]
            try:
                if not c_path.exists() or c_path.stat().st_size < 16:
                    raise IOError(f"Crate gravada ausente ou truncada: {c_path.name}")
                v_hdr, v_tracks, _, _ = crate_ops.parse_crate_binary(c_path.read_bytes())
                if v_hdr is None or len(v_tracks) != item_grav["qtd_esperada"]:
                    raise IOError(f"Divergência estrutural pós-gravação em {c_path.name}")
            except Exception as e_ver:
                erros_gravacao.append(f"Falha na verificação pós-gravação: {e_ver}")
                break

        if erros_gravacao:
            _log_fase("verificacao", "falha", "; ".join(erros_gravacao))
        else:
            _log_fase("verificacao", "concluida")

    # 5.2 Mover crates antigas para staging temporário (sem exclusão definitiva ainda)
    if not dry_run and not varredura_incompleta and not erros_gravacao and crates_para_deletar:
        stamp_st = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        staging_dir = crates_dir / f".staging_delete_{os.getpid()}_{stamp_st}"
        try:
            staging_dir.mkdir(parents=True, exist_ok=True)
            for antiga in crates_para_deletar:
                orig_p = crates_dir / antiga
                staged_p = staging_dir / antiga
                os.replace(str(orig_p), str(staged_p))
                crates_em_staging.append((orig_p, staged_p))
        except Exception as e_del:
            err_del = f"Falha ao preparar exclusão (staging) de crate antiga: {e_del}"
            erros_gravacao.append(err_del)
            print(f"   ❌ {err_del}", file=sys.stderr, flush=True)

    # Crates novas criadas (log informativo; em erro de gravação não reporta criação concluída)
    if not erros_gravacao:
        for nova in crates_novas:
            nome_amigavel = nova.replace(".crate", "").replace("%%", " -> ")
            msg_new = f"📂 Nova Crate COMPLETA Criada: [{nome_amigavel}]"
            if dry_run:
                msg_new = f"🔍 [ANÁLISE] {msg_new}"
            print(f"   {msg_new}", flush=True)
            movimentacoes_log.append(msg_new)

    # TRATAMENTO CONSERVADOR DO neworder.pref
    print("\n🧹 Verificando preferências de exibição de crates (neworder.pref)...", flush=True)
    neworder_file = path_serato / "neworder.pref"

    # Lê ordenação pré-existente
    ordem_existente = []
    header_pref = None
    outros_pref_blocos = []
    if neworder_file.exists():
        try:
            pref_existed_before = True
            pref_orig_bytes = neworder_file.read_bytes()
            h_p, ord_p, out_p = parse_neworder_pref(pref_orig_bytes)
            if h_p is not None:
                header_pref = h_p
                ordem_existente = ord_p
                outros_pref_blocos = out_p
        except Exception:
            pass

    # Mantém a ordem original do DJ para crates existentes, remove excluídas, adiciona novas ao final
    conjunto_crates_atuais = set()
    for master in crates_masters:
        conjunto_crates_atuais.add(master)
        if master in mapa_subcrates:
            for sub in mapa_subcrates[master]:
                conjunto_crates_atuais.add(f"{master}%%{sub}")

    if lista_pref_final_from_plan is not None:
        lista_pref_final = list(lista_pref_final_from_plan)
    else:
        lista_pref_final = []
        # 1. Preserva a ordem já configurada no Serato pelo usuário
        for item in ordem_existente:
            if item in conjunto_crates_atuais and item not in lista_pref_final:
                lista_pref_final.append(item)

        # 2. Anexa novas crates que ainda não figuravam no neworder.pref
        for item in sorted(list(conjunto_crates_atuais)):
            if item not in lista_pref_final:
                lista_pref_final.append(item)

    if not dry_run and not varredura_incompleta and not erros_gravacao:
        blocos_nior = []
        for item in lista_pref_final:
            item_limpo = item.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
            nior = criar_tag_tlv('tvcn', normalizar_nfc(item_limpo))
            blocos_nior.append(b'nior' + struct.pack('>I', len(nior)) + nior)

        cabecalho_usar = header_pref if (header_pref and len(header_pref) >= 8) else b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000'
        novo_conteudo_pref = cabecalho_usar + b''.join(outros_pref_blocos) + b''.join(blocos_nior)

        pref_alterado = True
        if pref_existed_before and pref_orig_bytes == novo_conteudo_pref:
            pref_alterado = False

        if pref_alterado:
            tmp_pref = neworder_file.with_name(f".tmp_neworder_{os.getpid()}.pref")
            try:
                with open(tmp_pref, 'wb') as f:
                    f.write(novo_conteudo_pref)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_pref, neworder_file)
                pref_foi_alterado = True
                print("   ✓ neworder.pref atualizado com preservação da organização existente.", flush=True)
            except Exception as e:
                if tmp_pref.exists():
                    try:
                        tmp_pref.unlink()
                    except Exception:
                        pass
                err_pref = f"Erro ao atualizar neworder.pref: {e}"
                erros_gravacao.append(err_pref)
                print(f"   ❌ {err_pref}", file=sys.stderr, flush=True)
        else:
            print("   🔒 neworder.pref inalterado (HD protegido contra escrita redundante).", flush=True)

        # Salva cache somente se todas as etapas anteriores forem 100% íntegras
        if not erros_gravacao:
            if cache_file.exists():
                try:
                    cache_existed_before = True
                    cache_orig_bytes = cache_file.read_bytes()
                except Exception:
                    pass
            try:
                cache_ok = salvar_cache(cache_file, novo_cache, lib_path=str(path_mp3))
                if cache_ok is False:
                    erros_gravacao.append("Erro ao atualizar cache de sincronização em disco.")
                else:
                    cache_foi_alterado = True
            except Exception as e_cache:
                erros_gravacao.append(f"Erro ao atualizar cache de sincronização: {e_cache}")
                print(f"   ❌ Erro ao atualizar cache: {e_cache}", file=sys.stderr, flush=True)
    else:
        if dry_run:
            print("   🔍 [MODO ANÁLISE] neworder.pref e cache não foram alterados (somente leitura).", flush=True)
        elif varredura_incompleta:
            print("   🛡️ [PROTEÇÃO] neworder.pref e cache não atualizados devido a falhas parciais na varredura.", flush=True)
        elif erros_gravacao:
            print("   🛡️ [PROTEÇÃO] neworder.pref e cache preservados sem alteração devido a erros de gravação.", flush=True)

    # COMMIT OU ROLLBACK GLOBAL DA TRANSAÇÃO
    if not dry_run and not varredura_incompleta and not erros_gravacao:
        # Confirma exclusão definitiva das crates em staging
        for orig_p, staged_p in crates_em_staging:
            try:
                if staged_p.exists():
                    staged_p.unlink()
            except Exception as e_commit_del:
                erros_gravacao.append(f"Falha ao confirmar remoção de '{orig_p.name}': {e_commit_del}")
            nome_amigavel = orig_p.name.replace(".crate", "").replace("%%", " -> ")
            msg_del = f"🚨 Crate COMPLETA Deletada do HD: [{nome_amigavel}]"
            print(f"   {msg_del}", flush=True)
            movimentacoes_log.append(msg_del)
        if staging_dir and staging_dir.exists():
            try:
                staging_dir.rmdir()
            except Exception:
                pass
        # Remove symlinks quebrados somente após confirmação integral
        for sym in broken_symlinks:
            try:
                sym.unlink()
            except OSError:
                pass
    elif dry_run and not varredura_incompleta:
        for antiga in crates_para_deletar:
            nome_amigavel = antiga.replace(".crate", "").replace("%%", " -> ")
            msg_del = f"🔍 [ANÁLISE] 🚨 Crate COMPLETA Deletada do HD: [{nome_amigavel}]"
            print(f"   {msg_del}", flush=True)
            movimentacoes_log.append(msg_del)
    elif not dry_run and erros_gravacao:
        _executar_rollback_global()
        for antiga in crates_para_deletar:
            print(f"   🛡️ [PROTEÇÃO] Crate física '{antiga}' preservada devido a falhas na transação.", flush=True)
    elif not dry_run and varredura_incompleta:
        for antiga in crates_para_deletar:
            print(f"   🛡️ [PROTEÇÃO] Crate física '{antiga}' preservada: varredura do scanner foi parcial.", flush=True)

    # ==========================================================================
    # FASE 6: FINALIZAÇÃO
    # ==========================================================================
    operacao_ok = (not varredura_incompleta) and (not erros_gravacao)

    # EXPORTAÇÃO CSV DE DUPLICADOS (Somente fora do dry_run e quando operacao_ok)
    csv_gerado_path = None
    if export_csv and relatorio_duplicados and not dry_run and operacao_ok:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = path_logs / f"relatorio_duplicados_{ts}.csv"
        try:
            with open(csv_file, mode='w', encoding='utf-8', newline='') as fc:
                writer = csv.writer(fc, delimiter=';')
                writer.writerow(['Nome do Arquivo', 'Pasta da Cópia', 'Pasta Original', 'Tamanho (Bytes)', 'Grau de Certeza', 'Motivo'])
                for item in relatorio_duplicados:
                    writer.writerow([
                        item["nome"], item["copia"], item["original"], item["tamanho"],
                        item.get("grau_certeza", ""), item.get("motivo", "")
                    ])
            csv_gerado_path = str(csv_file)
            print(f"\n📊 [HISTÓRICO DE DUPLICADOS SALVO EM CSV]", flush=True)
            print(f"   📂 Arquivo: {csv_file}", flush=True)
        except Exception as e:
            print(f"   ❌ Erro ao exportar CSV: {e}", file=sys.stderr, flush=True)

    # RELATÓRIO FINAL
    print("\n📊 [RELATÓRIO FINAL DE AUDITORIA]", flush=True)
    if varredura_incompleta:
        print(f"   ⚠️ ESTADO: PARCIAL COM {len(erros_leitura)} ERROS DE LEITURA.", flush=True)
        print("   🔒 Gravações destrutivas foram bloqueadas preventivamente para evitar exclusões indevidas.", flush=True)
    elif erros_gravacao:
        print(f"   ❌ ESTADO: FALHA NA SINCRONIZAÇÃO ({len(erros_gravacao)} erro(s) crítico(s)).", flush=True)
        if rollback_executado and not estado_parcial:
            print("   ↩️ Rollback das crates alteradas nesta sessão foi confirmado.", flush=True)
        elif estado_parcial:
            print("   ⚠️ ATENÇÃO: Estado parcial detectado. Verifique o Journal e os backups (.bak) antes de prosseguir.", flush=True)
    elif total_crates_gravadas == 0 and crates_inalteradas > 0 and not movimentacoes_log:
        print("   ℹ️  Nenhum arquivo ou pasta foi alterado desde o último sync.", flush=True)
        print("   🔒 HD protegido contra escritas desnecessárias.", flush=True)
    else:
        rotulo_gravadas = "Crates seriam regravadas" if dry_run else "Crates regravadas"
        print(f"   🎯 {rotulo_gravadas}: {total_crates_gravadas} | Crates inalteradas: {crates_inalteradas}", flush=True)
        if total_faixas_adicionadas > 0 or total_faixas_removidas > 0:
            print(f"   📈 Movimentações: +{total_faixas_adicionadas} adicionada(s), -{total_faixas_removidas} removida(s)", flush=True)

    print(f"   📂 Total de {total_faixas} faixa(s) mapeada(s)!", flush=True)
    if dry_run:
        if operacao_ok:
            print("🔍 Pré-avaliação concluída com sucesso! Nenhuma alteração física realizada.\n", flush=True)
        else:
            print("⚠️ Pré-avaliação concluída com erros de leitura. Nenhuma alteração física realizada.\n", flush=True)
    else:
        if operacao_ok:
            print("🎯 Sincronização concluída com sucesso! Pode abrir o Serato DJ Pro.\n", flush=True)
        else:
            print("❌ Sincronização NÃO foi concluída devido a erros críticos. Nenhuma alteração final foi confirmada.\n", flush=True)

    estado_final = "completo" if operacao_ok else ("estado_parcial" if estado_parcial else "falha")
    _log_fase("finalizacao", "concluida" if operacao_ok else "falha", estado_final)

    if not dry_run and sync_journal_id:
        try:
            import journal
            journal.record_sync_finish(
                sync_journal_id,
                sucesso=operacao_ok,
                estado=estado_final,
                erros=erros_leitura + erros_gravacao,
                detalhes={
                    "total_faixas": total_faixas,
                    "crates_gravadas": total_crates_gravadas,
                    "rollback_executado": rollback_executado,
                    "estado_parcial": estado_parcial,
                },
            )
        except Exception:
            pass

    library_id = _compute_library_id(path_mp3, path_serato)
    resumo_dados = {
        "sucesso": operacao_ok,
        "status_analise": "parcial_com_erros" if not operacao_ok else "completo",
        "estado_parcial": estado_parcial,
        "rollback_executado": rollback_executado,
        "fases": fases_executadas,
        "erros_leitura": erros_leitura,
        "erros_gravacao": erros_gravacao,
        "dry_run": dry_run,
        "plan_invalidated": plan_invalidated,
        "mp3_path": str(path_mp3),
        "serato_path": str(path_serato),
        "library_id": library_id,
        "total_faixas": total_faixas,
        "crates_gravadas": total_crates_gravadas,
        "crates_inalteradas": crates_inalteradas,
        "faixas_adicionadas": total_faixas_adicionadas,
        "faixas_removidas": total_faixas_removidas,
        "total_duplicados": len(relatorio_duplicados),
        "csv_duplicados": csv_gerado_path,
        "duplicados": relatorio_duplicados,
        "crates_arvore": mapa_crates_arvore,
        "movimentacoes": movimentacoes_log
    }

    if dry_run and operacao_ok:
        plan_id = f"plan-{uuid.uuid4().hex[:12]}"
        crates_to_write_plan = []
        for plano in planos_gravacao:
            c_path = plano["caminho_crate"]
            crates_to_write_plan.append({
                "caminho_crate": str(c_path),
                "nome_crate": plano["nome_crate"],
                "nome_exibicao": plano["nome_exibicao"],
                "faixas_finais_ordenadas": list(plano["faixas_finais_ordenadas"]),
                "header_antigo_b64": base64.b64encode(plano["header_antigo"]).decode("ascii") if plano.get("header_antigo") else None,
                "outros_blocos_b64": [base64.b64encode(b).decode("ascii") for b in plano.get("outros_blocos", [])],
                "chave_cache": plano["chave_cache"],
                "qtd_arquivos": plano["qtd_arquivos"],
                "tamanho_total_pasta": plano["tamanho_total_pasta"],
                "sig_pasta": plano["sig_pasta"],
                "faixas_adicionadas": sorted(list(plano.get("faixas_adicionadas", set()))),
                "faixas_removidas": sorted(list(plano.get("faixas_removidas", set()))),
                "crate_sha256_before": _sha256_file(c_path) if c_path.exists() else None,
            })

        crates_to_delete_plan = []
        for antiga in crates_para_deletar:
            c_path = crates_dir / antiga
            crates_to_delete_plan.append({
                "nome_arquivo": antiga,
                "caminho_crate": str(c_path),
                "sha256_before": _sha256_file(c_path) if c_path.exists() else None,
            })

        pref_path = path_serato / "neworder.pref"
        plan_payload = {
            "plan_id": plan_id,
            "created_at": datetime.datetime.now().isoformat(),
            "mp3_dir": str(path_mp3),
            "serato_dir": str(path_serato),
            "library_id": library_id,
            "raiz_relativa": str(raiz_relativa),
            "files": sorted(arquivos_plan_records, key=lambda x: x["abs_path"]),
            "crates_to_write": crates_to_write_plan,
            "crates_to_delete": crates_to_delete_plan,
            "crates_novas": list(crates_novas),
            "crates_masters": sorted(list(crates_masters)),
            "mapa_subcrates": {k: sorted(list(v)) for k, v in mapa_subcrates.items()},
            "neworder_pref_before_sha256": _sha256_file(pref_path) if pref_path.exists() else None,
            "neworder_pref_list": list(lista_pref_final),
            "total_faixas": total_faixas,
            "crates_inalteradas": crates_inalteradas,
            "mapa_crates_arvore": mapa_crates_arvore,
            "relatorio_duplicados": relatorio_duplicados,
        }
        plan_hash = _build_plan_hash(plan_payload)
        plan_payload["plan_hash"] = plan_hash
        resumo_dados["plan_id"] = plan_id
        resumo_dados["plan_hash"] = plan_hash
        resumo_dados["plan"] = plan_payload

    # No Dry Run: NÃO grava resumo em disco!
    if not dry_run and operacao_ok:
        resumo_path = path_logs / ".serato_sync_summary.json"
        per_lib_dir = path_logs / "summaries"
        per_lib_path = per_lib_dir / f"{library_id}.json"
        try:
            with open(resumo_path, "w", encoding="utf-8") as rf:
                json.dump(resumo_dados, rf, ensure_ascii=False, indent=2)
            per_lib_dir.mkdir(parents=True, exist_ok=True)
            with open(per_lib_path, "w", encoding="utf-8") as pf:
                json.dump(resumo_dados, pf, ensure_ascii=False, indent=2)
        except Exception:
            pass

    if emit_json_summary:
        print(f"__PAYLOAD_JSON_SUMMARY__{json.dumps(resumo_dados)}", flush=True)

    return operacao_ok, resumo_dados


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Engine")
    parser.add_argument("mp3_pos", nargs="?", default="", help="Caminho MP3 (posicional)")
    parser.add_argument("serato_pos", nargs="?", default="", help="Caminho Serato (posicional)")
    parser.add_argument("logs_pos", nargs="?", default="", help="Caminho Logs (posicional)")
    parser.add_argument("--mp3", type=str, default="", help="Caminho da pasta MP3 Master")
    parser.add_argument("--serato", type=str, default="", help="Caminho da pasta Serato")
    parser.add_argument("--logs", type=str, default="", help="Caminho da pasta Logs/Cache")
    parser.add_argument("--no-csv", action="store_true", help="Desativa exportação de CSV")
    parser.add_argument("--json-summary", action="store_true", help="Emite payload JSON ao final para a UI")
    parser.add_argument("--dry-run", action="store_true", help="Modo simulação / pré-avaliação (não grava nada em disco)")
    parser.add_argument("--execute-plan", type=str, default="", help="Caminho do arquivo JSON do plano imutável aprovado")
    parser.add_argument("--cli", action="store_true", help="Modo CLI estrito")

    args = parser.parse_args()

    mp3_final = args.mp3 or args.mp3_pos
    serato_final = args.serato or args.serato_pos
    logs_final = args.logs or args.logs_pos or str(DEFAULT_LOGS_DIR)

    if not mp3_final or not serato_final:
        print("❌ Erro: Os caminhos de MP3 e Serato devem ser explicitamente fornecidos.", file=sys.stderr)
        sys.exit(1)

    ok, _ = sincronizar_biblioteca(
        mp3_dir_str=mp3_final,
        serato_dir_str=serato_final,
        logs_dir_str=logs_final,
        export_csv=not args.no_csv,
        emit_json_summary=args.json_summary,
        dry_run=args.dry_run,
        plan_file=args.execute_plan or None
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
