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
import struct
import shutil
import unicodedata
import csv
import datetime
import json
import argparse
import hashlib
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


def parse_crate_binary(data: bytes):
    """
    Analisa estruturalmente um arquivo binário .crate do Serato.
    Retorna:
      header_bytes: Cabeçalho vrsn original preservado.
      faixas_ordenadas: Lista de caminhos relativos em sua ordem original no crate.
      blocos_otrk: Lista de tuplas (caminho_relativo, bloco_otrk_bytes).
      outros_blocos: Lista de blocos binários não-otrk preservados integralmente (ex: ovct, osrt).
    Valida rigorosamente os cabeçalhos e tamanhos de blocos.
    """
    if len(data) < 8 or not data.startswith(b'vrsn'):
        return None, [], [], []

    try:
        vrsn_len = struct.unpack('>I', data[4:8])[0]
        header_end = 8 + vrsn_len
        if header_end > len(data):
            return None, [], [], []
        header_bytes = data[:header_end]
    except Exception:
        return None, [], [], []

    faixas_ordenadas = []
    blocos_otrk = []
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
            # Bloco truncado; interrompe sem corromper
            break

        raw_block = data[idx:block_end]

        if tag == b'otrk':
            # Localiza ptrk dentro do bloco otrk de forma estruturada
            otrk_payload = data[idx+8:block_end]
            p_idx = 0
            found_ptrk = False
            while p_idx + 8 <= len(otrk_payload):
                p_tag = otrk_payload[p_idx:p_idx+4]
                try:
                    p_len = struct.unpack('>I', otrk_payload[p_idx+4:p_idx+8])[0]
                except Exception:
                    break
                p_end = p_idx + 8 + p_len
                if p_end <= len(otrk_payload) and p_tag == b'ptrk':
                    try:
                        path_str = otrk_payload[p_idx+8:p_end].decode('utf-16-be')
                        norm_path = normalizar_nfc(path_str)
                        faixas_ordenadas.append(norm_path)
                        blocos_otrk.append((norm_path, raw_block))
                        found_ptrk = True
                        break
                    except UnicodeDecodeError:
                        pass
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


def salvar_cache(cache_file: Path, dados: dict, lib_path: str = None, st_dev: int = 0):
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
        tmp = cache_file.with_suffix('.tmp')
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        shutil.move(tmp, cache_file)
    except Exception as e:
        print(f"⚠️ Erro ao salvar cache: {e}", file=sys.stderr, flush=True)


# ==============================================================================
# MOTOR ROBUSTO DE SINCRONIZAÇÃO E AUDITORIA
# ==============================================================================

def sincronizar_biblioteca(mp3_dir_str: str, serato_dir_str: str, logs_dir_str: str = None, 
                           export_csv: bool = True, emit_json_summary: bool = False,
                           dry_run: bool = False):
    
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
    varredura_incompleta = False

    is_external = str(path_serato).startswith("/Volumes/")
    if is_external:
        raiz_relativa = path_serato.parent  # /Volumes/[DiskName]
    else:
        raiz_relativa = Path.home()          # /Users/[Usuario]

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
        arquivos_pasta_meta = []
        tamanho_total_pasta = 0

        for arq in arquivos:
            if arq.startswith('._') or arq.startswith('.'):
                continue

            caminho_completo = caminho_atual / arq
            if caminho_completo.suffix.lower() in AUDIO_EXTENSIONS:
                if caminho_completo.is_symlink() and not caminho_completo.exists():
                    if not dry_run:
                        try:
                            caminho_completo.unlink()
                        except OSError:
                            pass
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

                # Regra de caminho relativo estrito
                try:
                    relativo = caminho_completo.relative_to(raiz_relativa)
                    relativo_str = normalizar_nfc(str(relativo))
                except ValueError:
                    try:
                        relativo = caminho_completo.relative_to(path_mp3)
                        relativo_str = normalizar_nfc(str(relativo))
                    except ValueError:
                        relativo_str = normalizar_nfc(str(caminho_completo))

                musicas_pasta_relativas.append(relativo_str)
                arquivos_pasta_meta.append((relativo_str, nome_nfc, tamanho, mtime_ns, ctime_ns, st_dev, st_ino))

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
                        "caminho_abs": str((raiz_relativa / f_rel).resolve()) if raiz_relativa else str(path_mp3 / f_rel),
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

            prefixo_log = "🔍 [ANÁLISE] " if dry_run else ""
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
                # Se a varredura teve erro de acesso, NÃO propõe exclusão de faixas!
                if varredura_incompleta:
                    print(f"   ⚠️ [PROTEÇÃO] Remoções suspensas na crate [{nome_exibicao}] devido a erros de leitura no scanner.", flush=True)
                else:
                    total_faixas_removidas += len(faixas_removidas)
                    msg_rem = f"{prefixo_log}🗑️ {len(faixas_removidas)} faixa(s) removida(s) da Crate [{nome_exibicao}]"
                    print(f"   {msg_rem}", flush=True)
                    movimentacoes_log.append(msg_rem)
                    for f_item in sorted(list(faixas_removidas))[:3]:
                        print(f"      - {Path(f_item).name}", flush=True)
                    if len(faixas_removidas) > 3:
                        print(f"      ... (-{len(faixas_removidas) - 3} outras faixas)", flush=True)

            # Preserva ordenação original: mantém faixas que já existiam na mesma ordem, adiciona novas no final
            if faixas_antigas_ordenadas:
                faixas_finais_ordenadas = [f for f in faixas_antigas_ordenadas if f in conjunto_novo]
                novas_para_adicionar = [f for f in musicas_pasta_relativas if f not in set(faixas_finais_ordenadas)]
                faixas_finais_ordenadas.extend(novas_para_adicionar)
            else:
                faixas_finais_ordenadas = list(musicas_pasta_relativas)

            tamanho_gravado = crate_tamanho
            if not dry_run:
                # Bloqueia gravação se varredura for incompleta
                if varredura_incompleta:
                    print(f"   ⚠️ Gravação de '{nome_crate}' bloqueada por segurança (varredura incompleta).", flush=True)
                else:
                    tmp_crate = caminho_crate.with_suffix('.tmp')
                    bak_crate = caminho_crate.with_suffix('.bak')
                    try:
                        with open(tmp_crate, 'wb') as f:
                            # Preserva cabeçalho vrsn original se existente, ou usa o padrão Serato
                            if header_antigo and len(header_antigo) >= 8:
                                f.write(header_antigo)
                            else:
                                f.write(b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000')

                            # Preserva blocos não-otrk existentes (ovct, osrt, etc.)
                            for b_extra in outros_blocos:
                                f.write(b_extra)

                            # Grava registros otrk/ptrk na ordem validada
                            for mus in faixas_finais_ordenadas:
                                ptrk = criar_tag_tlv('ptrk', mus)
                                otrk = b'otrk' + struct.pack('>I', len(ptrk)) + ptrk
                                f.write(otrk)

                            f.flush()
                            os.fsync(f.fileno())

                        tamanho_gravado = tmp_crate.stat().st_size

                        # Backup prévio atômico se a crate já existia
                        if caminho_crate.exists():
                            try:
                                shutil.copy2(caminho_crate, bak_crate)
                            except Exception:
                                pass

                        shutil.move(tmp_crate, caminho_crate)
                        total_crates_gravadas += 1
                        if not faixas_adicionadas and not faixas_removidas:
                            print(f"   🔹 Crate atualizada: {nome_exibicao} ({qtd_arquivos} faixas)", flush=True)
                    except Exception as e:
                        print(f"   ❌ Erro ao gravar crate {nome_crate}: {e}", file=sys.stderr, flush=True)
            else:
                total_crates_gravadas += 1
                if not faixas_adicionadas and not faixas_removidas:
                    print(f"   🔍 [ANÁLISE] Crate seria atualizada: {nome_exibicao} ({qtd_arquivos} faixas)", flush=True)

            novo_cache[chave_cache] = {
                "qtd": qtd_arquivos,
                "bytes": tamanho_total_pasta,
                "sig": sig_pasta,
                "crate_bytes": tamanho_gravado
            }

    # Auditoria de crates deletadas
    for antiga in sorted(list(crates_fisicas_antigas)):
        if antiga not in crates_processadas_agora:
            if varredura_incompleta:
                print(f"   🛡️ [PROTEÇÃO] Crate física '{antiga}' preservada: varredura do scanner foi parcial.", flush=True)
                continue

            if not dry_run:
                try:
                    (crates_dir / antiga).unlink()
                except Exception:
                    pass
            nome_amigavel = antiga.replace(".crate", "").replace("%%", " -> ")
            msg_del = f"🚨 Crate COMPLETA Deletada do HD: [{nome_amigavel}]"
            if dry_run:
                msg_del = f"🔍 [ANÁLISE] {msg_del}"
            print(f"   {msg_del}", flush=True)
            movimentacoes_log.append(msg_del)

    # Crates novas criadas
    for nova in sorted(list(crates_processadas_agora)):
        if nova not in crates_fisicas_antigas:
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
            h_p, ord_p, out_p = parse_neworder_pref(neworder_file.read_bytes())
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

    lista_pref_final = []
    # 1. Preserva a ordem já configurada no Serato pelo usuário
    for item in ordem_existente:
        if item in conjunto_crates_atuais and item not in lista_pref_final:
            lista_pref_final.append(item)

    # 2. Anexa novas crates que ainda não figuravam no neworder.pref
    for item in sorted(list(conjunto_crates_atuais)):
        if item not in lista_pref_final:
            lista_pref_final.append(item)

    if not dry_run and not varredura_incompleta:
        blocos_nior = []
        for item in lista_pref_final:
            item_limpo = item.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
            nior = criar_tag_tlv('tvcn', normalizar_nfc(item_limpo))
            blocos_nior.append(b'nior' + struct.pack('>I', len(nior)) + nior)

        cabecalho_usar = header_pref if (header_pref and len(header_pref) >= 8) else b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000'
        novo_conteudo_pref = cabecalho_usar + b''.join(outros_pref_blocos) + b''.join(blocos_nior)

        pref_alterado = True
        if neworder_file.exists():
            try:
                if neworder_file.read_bytes() == novo_conteudo_pref:
                    pref_alterado = False
            except Exception:
                pass

        if pref_alterado:
            tmp_pref = neworder_file.with_suffix('.tmp')
            try:
                with open(tmp_pref, 'wb') as f:
                    f.write(novo_conteudo_pref)
                    f.flush()
                    os.fsync(f.fileno())
                shutil.move(tmp_pref, neworder_file)
                print("   ✓ neworder.pref atualizado com preservação da organização existente.", flush=True)
            except Exception as e:
                print(f"   ❌ Erro ao atualizar neworder.pref: {e}", file=sys.stderr, flush=True)
        else:
            print("   🔒 neworder.pref inalterado (HD protegido contra escrita redundante).", flush=True)

        # Salva cache somente se a varredura for completa e sem erros
        salvar_cache(cache_file, novo_cache, lib_path=str(path_mp3))
    else:
        if dry_run:
            print("   🔍 [MODO ANÁLISE] neworder.pref e cache não foram alterados (somente leitura).", flush=True)
        elif varredura_incompleta:
            print("   🛡️ [PROTEÇÃO] neworder.pref e cache não atualizados devido a falhas parciais na varredura.", flush=True)

    # EXPORTAÇÃO CSV DE DUPLICADOS (Somente fora do dry_run)
    csv_gerado_path = None
    if export_csv and relatorio_duplicados and not dry_run:
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
        print("🔍 Pré-avaliação concluída com sucesso! Nenhuma alteração física realizada.\n", flush=True)
    else:
        print("🎯 Sincronização concluída com sucesso! Pode abrir o Serato DJ Pro.\n", flush=True)

    resumo_dados = {
        "sucesso": not varredura_incompleta,
        "status_analise": "parcial_com_erros" if varredura_incompleta else "completo",
        "erros_leitura": erros_leitura,
        "dry_run": dry_run,
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

    # No Dry Run: NÃO grava resumo em disco!
    if not dry_run and not varredura_incompleta:
        resumo_path = path_logs / ".serato_sync_summary.json"
        try:
            with open(resumo_path, "w", encoding="utf-8") as rf:
                json.dump(resumo_dados, rf, ensure_ascii=False, indent=2)
        except Exception:
            pass

    if emit_json_summary:
        print(f"__PAYLOAD_JSON_SUMMARY__{json.dumps(resumo_dados)}", flush=True)

    return (not varredura_incompleta), resumo_dados


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
        dry_run=args.dry_run
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
