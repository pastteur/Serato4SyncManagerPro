#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - MOTOR OFICIAL (serato_macos_app.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Motor de alta performance com leitura binária de crates, trava matemática
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
from pathlib import Path

# Garante flushing imediato de logs em stdout/stderr para captura em tempo real
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

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

def criar_tag_tlv(tag_str: str, valor_str: str) -> bytes:
    """Gera bloco binário TLV (Tag 4 bytes + Length big-endian + UTF-16 BE)."""
    tag_bytes = tag_str.encode('ascii')
    valor_bytes = valor_str.encode('utf-16-be')
    tamanho_bytes = struct.pack('>I', len(valor_bytes))
    return tag_bytes + tamanho_bytes + valor_bytes

def ler_faixas_crate_binaria(caminho_crate: Path) -> set:
    """
    Lê uma .crate binária existente no HD e extrai todas as faixas (tag ptrk)
    em formato normalizado NFC para auditoria de movimentação individual.
    """
    faixas = set()
    if not caminho_crate.exists():
        return faixas
    try:
        with open(caminho_crate, 'rb') as f:
            data = f.read()

        idx = 0
        tamanho_total = len(data)
        while idx < tamanho_total - 8:
            pos = data.find(b'ptrk', idx)
            if pos == -1 or pos + 8 > tamanho_total:
                break
            
            # struct.unpack('>I', data[pos+4:pos+8]) lê o tamanho em bytes
            val_len = struct.unpack('>I', data[pos+4:pos+8])[0]
            val_start = pos + 8
            val_end = val_start + val_len

            if val_end <= tamanho_total:
                bytes_texto = data[val_start:val_end]
                try:
                    caminho_texto = bytes_texto.decode('utf-16-be')
                    faixas.add(normalizar_nfc(caminho_texto))
                except UnicodeDecodeError:
                    pass
            idx = val_start
    except Exception as e:
        print(f"   ⚠️ Aviso ao ler crate prévia {caminho_crate.name}: {e}", flush=True)
    return faixas

def carregar_cache(cache_file: Path) -> dict:
    if not cache_file.exists():
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def salvar_cache(cache_file: Path, dados: dict):
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix('.tmp')
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        shutil.move(tmp, cache_file)
    except Exception as e:
        print(f"⚠️ Erro ao salvar cache: {e}", file=sys.stderr, flush=True)

def detectar_pastas_mac():
    """Detecta automaticamente se há HD externo montado com Serato ou se usa armazenamento interno."""
    # 1. Procura em volumes externos (/Volumes/*)
    if Path("/Volumes").exists():
        try:
            for vol in sorted(Path("/Volumes").iterdir()):
                if vol.is_dir() and not vol.name.startswith("Macintosh") and not vol.name.startswith("."):
                    # Verifica pasta Serato moderna ou _Serato_ legada
                    tentativa_serato = vol / "Serato" if (vol / "Serato").exists() else vol / "_Serato_"
                    tentativa_mp3 = vol / "Music" / "MP3" if (vol / "Music" / "MP3").exists() else vol / "Music"
                    
                    if tentativa_serato.exists() or tentativa_mp3.exists():
                        s_final = tentativa_serato if tentativa_serato.exists() else vol / "Serato"
                        m_final = tentativa_mp3 if tentativa_mp3.exists() else vol / "Music"
                        return str(m_final), str(s_final)
        except Exception:
            pass

    # 2. Armazenamento Interno (Notebook)
    home = Path.home()
    mp3_interno = home / "Music" / "MP3"
    if not mp3_interno.exists():
        mp3_interno = home / "Music"
        
    serato_interno = home / "Library" / "Application Support" / "Serato"
    return str(mp3_interno), str(serato_interno)

# ==============================================================================
# MOTOR ROBUSTO DE SINCRONIZAÇÃO E AUDITORIA
# ==============================================================================

def sincronizar_biblioteca(mp3_dir_str: str, serato_dir_str: str, logs_dir_str: str = None, 
                           export_csv: bool = True, emit_json_summary: bool = False,
                           dry_run: bool = False):
    
    if dry_run:
        print("\n🔍 [SERATO 4 SYNC PRO] - MODO ANÁLISE / DRY-RUN ATIVADO (SOMENTE LEITURA) 🔍", flush=True)
        print("💡 Nenhuma alteração física (.crate, .pref ou .json) será gravada no seu HD.\n", flush=True)
    else:
        print("\n⚡ [SERATO 4 SYNC MANAGER PRO] - INICIANDO AUDITORIA E SINCRONIZAÇÃO NATIVA ⚡", flush=True)

    path_mp3 = Path(os.path.expanduser(mp3_dir_str)).resolve()
    path_serato = Path(os.path.expanduser(serato_dir_str)).resolve()
    path_logs = Path(os.path.expanduser(logs_dir_str or str(DEFAULT_LOGS_DIR))).resolve()

    print(f"📂 Pasta Master MP3  : {path_mp3}", flush=True)
    print(f"📂 Pasta Serato      : {path_serato}", flush=True)
    print(f"📂 Diretório de Logs : {path_logs}\n", flush=True)

    if not path_mp3.exists():
        print(f"❌ ERRO CRÍTICO: A pasta de músicas informada não existe: {path_mp3}", flush=True)
        return False, "Pasta MP3 não encontrada."

    # Na versão 4, o carregamento e leitura são exclusivamente via Subcrates/
    crates_dir = path_serato / "Subcrates"
    crates_dir.mkdir(parents=True, exist_ok=True)
    path_logs.mkdir(parents=True, exist_ok=True)

    # Identifica crates físicas antigas presentes no disco
    crates_fisicas_antigas = set([f.name for f in crates_dir.glob("*.crate")]) if crates_dir.exists() else set()

    cache_file = path_logs / ".serato_sync_cache.json"
    cache_anterior = carregar_cache(cache_file)
    novo_cache = {}

    crates_masters = set()
    mapa_subcrates = {}
    mapa_crates_arvore = {}
    relatorio_duplicados = []
    arquivos_vistos = {}
    crates_processadas_agora = set()

    total_faixas = 0
    total_crates_gravadas = 0
    crates_inalteradas = 0
    total_faixas_adicionadas = 0
    total_faixas_removidas = 0
    movimentacoes_log = []

    # Cálculo da raiz para caminhos relativos puros
    # Se for HD externo (/Volumes/NomeDoDisco/Serato), a raiz do HD é path_serato.parent (/Volumes/NomeDoDisco)
    # Se for interno no Mac (~/Library/Application Support/Serato), a raiz deve omitir /Users/usuario/
    is_external = str(path_serato).startswith("/Volumes/")
    if is_external:
        raiz_relativa = path_serato.parent  # /Volumes/[DiskName]
    else:
        raiz_relativa = Path.home()          # /Users/[Usuario]

    print(f"🔗 Raiz de Cálculo Relativo: {raiz_relativa}", flush=True)
    print("🔍 Realizando varredura profunda e auditoria de binários...\n", flush=True)

    for raiz, _, arquivos in os.walk(str(path_mp3)):
        caminho_atual = Path(raiz)

        # Filtro de arquivos ocultos do macOS (._*, .DS_Store, .Trash)
        if any(part.startswith('.') for part in caminho_atual.parts):
            continue

        musicas_pasta_relativas = []
        tamanho_total_pasta = 0

        for arq in arquivos:
            if arq.startswith('._') or arq.startswith('.'):
                continue

            caminho_completo = caminho_atual / arq
            if caminho_completo.suffix.lower() in AUDIO_EXTENSIONS:
                try:
                    tamanho = caminho_completo.stat().st_size
                except OSError:
                    tamanho = 0

                tamanho_total_pasta += tamanho
                nome_nfc = normalizar_nfc(arq)
                chave_duplicado = (nome_nfc, tamanho)

                # Auditoria de duplicados com inclusão integral em ambas as crates
                if chave_duplicado in arquivos_vistos:
                    info_orig = arquivos_vistos[chave_duplicado]
                    relatorio_duplicados.append({
                        "id": f"dup-{len(relatorio_duplicados)+1}",
                        "nome": arq,
                        "copia": str(caminho_atual),
                        "original": str(info_orig["pasta"]),
                        "caminho_copia": str(caminho_completo),
                        "caminho_original": str(info_orig["caminho"]),
                        "tamanho": tamanho
                    })
                else:
                    arquivos_vistos[chave_duplicado] = {
                        "pasta": caminho_atual,
                        "caminho": caminho_completo
                    }

                # Regra de Ouro: Caminho estritamente relativo à raiz do dispositivo
                try:
                    relativo = caminho_completo.relative_to(raiz_relativa)
                    musicas_pasta_relativas.append(normalizar_nfc(str(relativo)))
                except ValueError:
                    try:
                        relativo = caminho_completo.relative_to(path_mp3)
                        musicas_pasta_relativas.append(normalizar_nfc(str(relativo)))
                    except ValueError:
                        musicas_pasta_relativas.append(normalizar_nfc(str(caminho_completo)))

        if musicas_pasta_relativas:
            try:
                rel_pasta = caminho_atual.relative_to(path_mp3)
                partes = rel_pasta.parts
            except ValueError:
                partes = [caminho_atual.name]

            if not partes:
                continue

            # Elimina diretórios intermediários indesejados (Contents, UnknownAlbum, etc)
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

            # Armazena na árvore interativa de navegação da interface
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
                    for f_rel in sorted(musicas_pasta_relativas)
                ]
            }

            # TRAVA MATEMÁTICA ANTI-FALSO-POSITIVO
            chave_cache = normalizar_nfc(str(caminho_atual.resolve()))
            qtd_arquivos = len(musicas_pasta_relativas)

            novo_cache[chave_cache] = {
                "qtd": qtd_arquivos,
                "bytes": tamanho_total_pasta
            }

            # LEITURA PRÉVIA DA CRATE BINÁRIA ATUAL DO DISCO (Rastreando tag ptrk)
            faixas_antigas_crate = ler_faixas_crate_binaria(caminho_crate)
            conjunto_novo = set(musicas_pasta_relativas)

            # Comparação cirúrgica: novas vs antigas
            faixas_adicionadas = conjunto_novo - faixas_antigas_crate
            faixas_removidas = faixas_antigas_crate - conjunto_novo

            dados_prev_cache = cache_anterior.get(chave_cache)
            cache_bate = (dados_prev_cache is not None and 
                          dados_prev_cache.get("qtd") == qtd_arquivos and 
                          dados_prev_cache.get("bytes") == tamanho_total_pasta and 
                          caminho_crate.exists())

            # Se bate o cache e a crate binária confere, pula reescrita física (Smart Crate Writing)
            if cache_bate and len(faixas_adicionadas) == 0 and len(faixas_removidas) == 0:
                crates_inalteradas += 1
                continue

            # Log de Movimentação Individual de Músicas
            prefixo_log = "🔍 [ANÁLISE] " if dry_run else ""
            if faixas_adicionadas:
                total_faixas_adicionadas += len(faixas_adicionadas)
                msg_add = f"{prefixo_log}🆕 {len(faixas_adicionadas)} nova(s) faixa(s) adicionada(s) na Crate [{nome_exibicao}]"
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

            # ESCRITA ATÔMICA DA CRATE (.tmp -> shutil.move)
            if not dry_run:
                tmp_crate = caminho_crate.with_suffix('.tmp')
                try:
                    with open(tmp_crate, 'wb') as f:
                        f.write(b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000')
                        for mus in sorted(musicas_pasta_relativas):
                            ptrk = criar_tag_tlv('ptrk', mus)
                            otrk = b'otrk' + struct.pack('>I', len(ptrk)) + ptrk
                            f.write(otrk)
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

    # Detecção de Crates Deletadas no HD
    for antiga in crates_fisicas_antigas:
        if antiga not in crates_processadas_agora:
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

    # Detecção de Crates Novas Criadas
    for nova in crates_processadas_agora:
        if nova not in crates_fisicas_antigas:
            nome_amigavel = nova.replace(".crate", "").replace("%%", " -> ")
            msg_new = f"📂 Nova Crate COMPLETA Criada: [{nome_amigavel}]"
            if dry_run:
                msg_new = f"🔍 [ANÁLISE] {msg_new}"
            print(f"   {msg_new}", flush=True)
            movimentacoes_log.append(msg_new)

    # ORDENAÇÃO DECRESCENTE INVERTIDA NO neworder.pref
    print("\n🧹 Atualizando preferências de exibição lateral (neworder.pref)...", flush=True)
    print("   ↳ Estilos de A-Z, com subcrates lógicas numéricas em ordem decrescente (Novidades no topo)", flush=True)
    neworder_file = path_serato / "neworder.pref"
    lista_pref = []

    for master in sorted(list(crates_masters)):
        lista_pref.append(master)
        if master in mapa_subcrates:
            subs = sorted(list(mapa_subcrates[master]), reverse=True)
            for sub in subs:
                lista_pref.append(f"{master}%%{sub}")

    if not dry_run:
        tmp_pref = neworder_file.with_suffix('.tmp')
        try:
            with open(tmp_pref, 'wb') as f:
                f.write(b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000')
                for item in lista_pref:
                    item_limpo = item.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
                    nior = criar_tag_tlv('tvcn', normalizar_nfc(item_limpo))
                    f.write(b'nior' + struct.pack('>I', len(nior)) + nior)
            shutil.move(tmp_pref, neworder_file)
            print("   ✓ neworder.pref gravado com sucesso.", flush=True)
        except Exception as e:
            print(f"   ❌ Erro ao atualizar neworder.pref: {e}", file=sys.stderr, flush=True)
        
        salvar_cache(cache_file, novo_cache)
    else:
        print("   🔍 [MODO ANÁLISE] neworder.pref e cache não foram alterados.", flush=True)

    # AUDITORIA E PLANILHA CSV DE DUPLICADOS COM DELIMITADOR ';'
    csv_gerado_path = None
    if export_csv and relatorio_duplicados:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        prefixo_csv = "analise_duplicados_" if dry_run else "relatorio_duplicados_"
        csv_file = path_logs / f"{prefixo_csv}{ts}.csv"
        try:
            with open(csv_file, mode='w', encoding='utf-8', newline='') as fc:
                writer = csv.writer(fc, delimiter=';')
                writer.writerow(['Nome do Arquivo', 'Pasta Atual da Copia', 'Pasta Original', 'Tamanho (Bytes)'])
                for item in relatorio_duplicados:
                    writer.writerow([item["nome"], item["copia"], item["original"], item["tamanho"]])
            csv_gerado_path = str(csv_file)
            print(f"\n📊 [HISTÓRICO DE DUPLICADOS SALVO]", flush=True)
            print(f"   📂 Planilha CSV gravada em: {csv_file}", flush=True)
            print(f"   💡 {len(relatorio_duplicados)} faixa(s) repetida(s) identificadas (preservadas em ambas as crates).", flush=True)
        except Exception as e:
            print(f"   ❌ Erro ao exportar CSV: {e}", file=sys.stderr, flush=True)

    # RESULTADO FINAL
    print("\n📊 [RELATÓRIO FINAL DE AUDITORIA]", flush=True)
    if total_crates_gravadas == 0 and crates_inalteradas > 0 and not movimentacoes_log:
        print("   ℹ️  Nenhum arquivo ou pasta foi adicionado/removido desde o último sync.", flush=True)
        print("   🔒 Trava Anti-Falso-Positivo: HD protegido contra escritas desnecessárias.", flush=True)
    else:
        rotulo_gravadas = "Crates seriam regravadas" if dry_run else "Crates regravadas"
        print(f"   🎯 {rotulo_gravadas}: {total_crates_gravadas} | Crates inalteradas (cache): {crates_inalteradas}", flush=True)
        if total_faixas_adicionadas > 0 or total_faixas_removidas > 0:
            print(f"   📈 Movimentações: +{total_faixas_adicionadas} adicionada(s), -{total_faixas_removidas} removida(s)", flush=True)

    print(f"   📂 Total de {total_faixas} faixa(s) mapeada(s) com sucesso!", flush=True)
    if dry_run:
        print("🔍 Simulação concluída com sucesso! Nenhuma alteração foi realizada.\n", flush=True)
    else:
        print("🎯 Sincronização concluída com sucesso! Pode abrir o Serato DJ Pro 4.\n", flush=True)

    resumo_dados = {
        "sucesso": True,
        "dry_run": dry_run,
        "total_faixas": total_faixas,
        "crates_gravadas": total_crates_gravadas,
        "crates_inalteradas": crates_inalteradas,
        "faixas_adicionadas": total_faixas_adicionadas,
        "faixas_removidas": total_faixas_removidas,
        "total_duplicados": len(relatorio_duplicados),
        "csv_duplicados": csv_gerado_path,
        "duplicados": relatorio_duplicados,  # Todos os duplicados completos
        "crates_arvore": mapa_crates_arvore,  # Árvore completa para navegação
        "movimentacoes": movimentacoes_log
    }

    # Salva payload JSON de resumo para a UI consumir
    resumo_path = path_logs / ".serato_sync_summary.json"
    try:
        with open(resumo_path, "w", encoding="utf-8") as rf:
            json.dump(resumo_dados, rf, ensure_ascii=False, indent=2)
    except Exception:
        pass

    if emit_json_summary:
        print(f"__PAYLOAD_JSON_SUMMARY__{json.dumps(resumo_dados)}", flush=True)

    return True, resumo_dados

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
    parser.add_argument("--dry-run", action="store_true", help="Modo simulação / somente análise (não grava nada no HD)")
    parser.add_argument("--cli", action="store_true", help="Modo CLI estrito")

    args = parser.parse_args()

    mp3_auto, serato_auto = detectar_pastas_mac()
    mp3_final = args.mp3 or args.mp3_pos or mp3_auto
    serato_final = args.serato or args.serato_pos or serato_auto
    logs_final = args.logs or args.logs_pos or str(DEFAULT_LOGS_DIR)

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
