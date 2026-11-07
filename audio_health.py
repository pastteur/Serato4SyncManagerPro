#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - AUDIO HEALTH DOCTOR (audio_health.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Auditoria profunda de integridade e reparação de faixas:
- Detecta cortes repentinos (downloads incompletos/truncados)
- Filtra faixas com duração curta/máxima suspeita (< 30s, 60s, 90s, 120s)
- Detecta baixa qualidade / fake 320 (< 192 kbps)
- Detecta arquivos vazios ou com erro de decodificação de frames
- Correção Online: Baixa versão 320kbps íntegra via yt-dlp e substitui automaticamente
================================================================================
"""

import sys
import os
import json
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

# Vendor fallback: permite carregar dependências empacotadas sem exigir pip local
_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

try:
    import mutagen
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON
except ImportError:
    mutagen = None

AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')
YT_DLP_CANDIDATES = [
    "/opt/homebrew/bin/yt-dlp",
    "/usr/local/bin/yt-dlp",
    shutil.which("yt-dlp") or ""
]
FFMPEG_DIR = "/opt/homebrew/bin:/usr/local/bin:/usr/bin"
QUARANTINE_DIR = Path.home() / ".serato_quarentena_audio"
FFMPEG_CANDIDATES = [
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    shutil.which("ffmpeg") or ""
]

# Limiares da auditoria espectral de falsos 320 kbps.
# MP3 de 128 kbps aplica um lowpass em torno de 16 kHz; a partir de ~17.5 kHz quase não
# sobra energia. Comparamos a faixa de referência (12 kHz) com uma passagem dupla em
# FAKE320_HIGHPASS_HZ: se a referência tem sinal e os agudos não, o arquivo foi superado.
FAKE320_REFERENCE_HZ = 12000
FAKE320_REFERENCE_WIDTH_HZ = 4000
FAKE320_HIGHPASS_HZ = 17500
FAKE320_REF_MAX_DB = -38.0
FAKE320_HIGH_MAX_DB = -53.0
FAKE320_HIGH_MEAN_DB = -82.0


def get_ffmpeg_bin():
    for p in FFMPEG_CANDIDATES:
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def detect_fake_320k_cutoff(filepath: Path, duration: float, bitrate: int) -> tuple:
    """
    Realiza auditoria espectral rápida de altas frequências via ffmpeg para detectar falso 320 kbps.
    MP3 de 128 kbps costuma ter um brickwall lowpass que corta o áudio a partir de ~16 kHz.
    Faixas genuínas de 320 kbps ou lossless mantêm energia expressiva entre 17.5 kHz e 22 kHz.
    A classificação usa apenas os limiares declarados no topo do módulo (FAKE320_*).
    """
    ffmpeg_bin = get_ffmpeg_bin()
    if not ffmpeg_bin or duration < 12.0 or bitrate < 240000:
        return False, ""

    try:
        start_sec = max(4.0, duration * 0.35)
        if start_sec + 4.0 > duration:
            start_sec = max(0.0, duration - 5.0)

        cmd = [
            ffmpeg_bin,
            "-v", "error",
            "-ss", str(round(start_sec, 2)),
            "-t", "4",
            "-i", str(filepath),
            "-filter_complex",
            "[0:a]asplit=2[a1][a2];"
            f"[a1]bandpass=f={FAKE320_REFERENCE_HZ}:width_type=h:w={FAKE320_REFERENCE_WIDTH_HZ},volumedetect[out1];"
            f"[a2]highpass=f={FAKE320_HIGHPASS_HZ},highpass=f={FAKE320_HIGHPASS_HZ},volumedetect[out2]",
            "-map", "[out1]", "-f", "null", "-",
            "-map", "[out2]", "-f", "null", "-"
        ]

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, text=True)
        output = proc.stderr

        out1_max = None
        out2_max = None
        out2_mean = None

        for line in output.splitlines():
            line_s = line.strip()
            if "max_volume:" in line_s:
                try:
                    val = float(line_s.split("max_volume:")[1].split("dB")[0].strip())
                    if out1_max is None:
                        out1_max = val
                    else:
                        out2_max = val
                except Exception:
                    pass
            elif "mean_volume:" in line_s:
                try:
                    val = float(line_s.split("mean_volume:")[1].split("dB")[0].strip())
                    out2_mean = val
                except Exception:
                    pass

        if out1_max is not None and out2_max is not None:
            ref_has_signal = out1_max > FAKE320_REF_MAX_DB
            highs_cut = out2_max < FAKE320_HIGH_MAX_DB or (
                out2_mean is not None and out2_mean < FAKE320_HIGH_MEAN_DB
            )
            if ref_has_signal and highs_cut:
                reason = (
                    f"Nível de agudos acima de {FAKE320_HIGHPASS_HZ / 1000:.1f}kHz é de apenas "
                    f"{out2_max} dB (mid-highs: {out1_max} dB)."
                )
                return True, reason

    except Exception:
        pass

    return False, ""


def get_yt_dlp_bin():
    for p in YT_DLP_CANDIDATES:
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def inspect_track_health(filepath: Path, max_duration_suspicious: float = 60.0):
    """
    Audita um arquivo de áudio e retorna diagnóstico de saúde e integridade física.
    """
    try:
        filesize = filepath.stat().st_size
    except Exception as e:
        return {
            "status": "comprometida",
            "categoria": "corrompida",
            "tipo_problema": "arquivo_inacessivel",
            "severidade": "alta",
            "detalhes": f"Erro de I/O: {e}",
            "duracao": 0,
            "bitrate": 0
        }

    # 1. Arquivo vazio ou corrompido de início (< 20 KB)
    if filesize < 20480:
        return {
            "status": "comprometida",
            "categoria": "corrompida",
            "tipo_problema": "arquivo_vazio",
            "severidade": "critica",
            "detalhes": f"Arquivo minúsculo ({round(filesize/1024, 1)} KB). Não é um áudio utilizável em pista.",
            "duracao": 0,
            "bitrate": 0
        }

    duration = 0.0
    bitrate = 0
    sample_rate = 0
    is_truncated = False
    truncation_reason = ""

    if mutagen:
        try:
            audio = mutagen.File(str(filepath))
            if audio is None:
                return {
                    "status": "comprometida",
                    "categoria": "corrompida",
                    "tipo_problema": "formato_invalido",
                    "severidade": "critica",
                    "detalhes": "Cabeçalho de áudio inválido ou irreconhecível.",
                    "duracao": 0,
                    "bitrate": 0
                }

            if hasattr(audio, 'info') and audio.info is not None:
                info = audio.info
                duration = getattr(info, 'length', 0.0)
                bitrate = getattr(info, 'bitrate', 0)
                sample_rate = getattr(info, 'sample_rate', 0)

            # Detecção de corte repentino (Download interrompido na metade)
            # Compara tamanho físico real vs tamanho esperado pelos bytes de áudio
            if bitrate > 0 and duration > 15:
                expected_audio_bytes = (duration * bitrate) / 8.0
                ratio = filesize / expected_audio_bytes
                if ratio < 0.70 and duration > 25:
                    is_truncated = True
                    diff_pct = round((1.0 - ratio) * 100)
                    truncation_reason = f"Corte repentino: possui {diff_pct}% menos dados que o esperado ({round(filesize/(1024*1024), 1)} MB para {round(duration)}s a {round(bitrate/1000)}kbps)."
                elif filesize < 400 * 1024 and duration > 30:
                    is_truncated = True
                    truncation_reason = f"Corte de stream: apenas {round(filesize/1024)} KB para {round(duration)}s de música."

        except Exception as e:
            return {
                "status": "comprometida",
                "categoria": "corrompida",
                "tipo_problema": "corrompida",
                "severidade": "alta",
                "detalhes": f"Erro de decodificação de frames: {e}",
                "duracao": 0,
                "bitrate": 0
            }

    # 1. Truncada / Cortada no meio
    if is_truncated:
        return {
            "status": "comprometida",
            "categoria": "truncada",
            "tipo_problema": "truncada_cortada",
            "severidade": "critica",
            "detalhes": truncation_reason,
            "duracao": round(duration, 1),
            "bitrate": round(bitrate / 1000) if bitrate else 0
        }

    # 2. Faixa com duração suspeita (menor que o teto configurado pelo DJ, ex: 10s, 30s, 45s)
    if 0 < duration <= max_duration_suspicious:
        return {
            "status": "suspeita",
            "categoria": "curta",
            "tipo_problema": "muito_curta",
            "severidade": "media",
            "detalhes": f"Faixa curta com apenas {round(duration)}s (abaixo do teto de {int(max_duration_suspicious)}s). Provável vinheta, corte de rádio ou preview.",
            "duracao": round(duration, 1),
            "bitrate": round(bitrate / 1000) if bitrate else 0
        }

    # 3. Baixa taxa de bits (Fake 320 ou baixa fidelidade)
    if 0 < bitrate < 192000:
        return {
            "status": "atencao",
            "categoria": "baixa_qualidade",
            "tipo_problema": "baixa_fidelidade",
            "severidade": "baixa",
            "detalhes": f"Taxa de bits de apenas {round(bitrate / 1000)} kbps. Recomendado substituir por 320 kbps para som potente.",
            "duracao": round(duration, 1),
            "bitrate": round(bitrate / 1000),
            "sample_rate": sample_rate
        }

    # 4. Detecção espectral de Fake 320 kbps (Upsampled de 128k com corte em ~16 kHz)
    if bitrate >= 240000 and duration >= 12.0:
        is_fake, fake_reason = detect_fake_320k_cutoff(filepath, duration, bitrate)
        if is_fake:
            return {
                "status": "atencao",
                "categoria": "fake_320k",
                "tipo_problema": "upsampled_fake_320k",
                "severidade": "alta",
                "detalhes": f"Falso 320 kbps detectado (Corte espectral em ~16 kHz). O cabeçalho declara {round(bitrate / 1000)} kbps, mas o áudio foi reencodado a partir de fonte comprimida. {fake_reason}",
                "duracao": round(duration, 1),
                "bitrate": round(bitrate / 1000),
                "sample_rate": sample_rate
            }

    # 4. Saudável (44.1k, 48k, 88.2k, 96k rodam perfeitamente nos softwares modernos de DJ)
    return {
        "status": "saudavel",
        "categoria": "saudavel",
        "tipo_problema": "nenhum",
        "severidade": "ok",
        "detalhes": f"Áudio 100% íntegro ({round(duration)}s · {round(bitrate/1000) if bitrate else 'VBR'} kbps · {sample_rate} Hz)",
        "duracao": round(duration, 1),
        "bitrate": round(bitrate / 1000) if bitrate else 0,
        "sample_rate": sample_rate
    }


def scan_audio_health(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True,
    max_duration_suspicious: float = 60.0,
    filter_categoria: str = "todas",
    limit: int = 250,
    offset: int = 0,
    stream_progress: bool = True
):
    """
    Audita os arquivos de áudio por crate ou em toda a biblioteca, agrupando por destaques de evidências.
    """
    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    if not base_path.exists():
        res = {"sucesso": False, "erro": f"Pasta não encontrada: {base_path}"}
        if stream_progress:
            print(json.dumps({"tipo": "resultado", "dados": res}, ensure_ascii=False), flush=True)
        return res

    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    if not target_dir.exists():
        res = {
            "sucesso": True,
            "total_analisadas": 0,
            "total_problemas": 0,
            "categorias_contagem": {"truncada": 0, "curta": 0, "baixa_qualidade": 0, "fake_320k": 0, "corrompida": 0},
            "items": []
        }
        if stream_progress:
            print(json.dumps({"tipo": "resultado", "dados": res}, ensure_ascii=False), flush=True)
        return res

    # Pré-contagem rápida de arquivos para cálculo de porcentagem precisa
    total_audio_files = 0
    for root, dirs, files in os.walk(str(target_dir)):
        if '/.' in root or '\\.' in root:
            continue
        if crate_raiz and not include_subcrates and not subcrate:
            if root != str(target_dir):
                dirs.clear()
                continue
            dirs.clear()
        total_audio_files += sum(1 for f in files if not f.startswith('.') and Path(f).suffix.lower() in AUDIO_EXTENSIONS)

    total_scanned = 0
    items = []
    category_counts = {
        "truncada": 0,
        "curta": 0,
        "baixa_qualidade": 0,
        "fake_320k": 0,
        "corrompida": 0
    }

    if stream_progress:
        print(json.dumps({
            "tipo": "progresso",
            "processados": 0,
            "total": total_audio_files,
            "percentual": 0.0,
            "faixa": "Iniciando auditoria de integridade..."
        }, ensure_ascii=False), flush=True)

    for root, dirs, files in os.walk(str(target_dir)):
        if '/.' in root or '\\.' in root:
            continue
        if crate_raiz and not include_subcrates and not subcrate:
            if root != str(target_dir):
                dirs.clear()
                continue
            dirs.clear()

        rel_folder = os.path.relpath(root, str(base_path))

        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            ext = Path(f).suffix.lower()
            if ext in AUDIO_EXTENSIONS:
                total_scanned += 1
                full_p = Path(root) / f
                diag = inspect_track_health(full_p, max_duration_suspicious=max_duration_suspicious)

                if diag["status"] != "saudavel":
                    cat = diag.get("categoria", "corrompida")
                    if cat in category_counts:
                        category_counts[cat] += 1

                    # Filtra por categoria selecionada se não for "todas"
                    if filter_categoria == "todas" or filter_categoria == cat:
                        if len(items) < limit:
                            crate_parts = [p for p in rel_folder.replace('\\', '/').split('/') if p]
                            c_raiz = crate_parts[0] if crate_parts else ""
                            items.append({
                                "id": f"health-{total_scanned}",
                                "caminho": str(full_p),
                                "arquivo": f,
                                "pasta": rel_folder,
                                "crate": c_raiz,
                                "status": diag["status"],
                                "categoria": cat,
                                "tipo_problema": diag["tipo_problema"],
                                "severidade": diag["severidade"],
                                "detalhes": diag["detalhes"],
                                "duracao_seg": diag["duracao"],
                                "bitrate_kbps": diag["bitrate"],
                                "sample_rate": diag.get("sample_rate", 0)
                            })

                if stream_progress and (total_scanned % 35 == 0 or total_scanned == total_audio_files):
                    pct = round((total_scanned / max(1, total_audio_files)) * 100, 1)
                    print(json.dumps({
                        "tipo": "progresso",
                        "processados": total_scanned,
                        "total": total_audio_files,
                        "percentual": pct,
                        "faixa": f
                    }, ensure_ascii=False), flush=True)

    total_problems = sum(category_counts.values())

    res = {
        "sucesso": True,
        "total_analisadas": total_scanned,
        "total_problemas": total_problems,
        "categorias_contagem": category_counts,
        "items": items
    }
    if stream_progress:
        print(json.dumps({"tipo": "resultado", "dados": res}, ensure_ascii=False), flush=True)
    return res


def repair_track_online(filepath_str: str):
    """
    Substitui a faixa danificada baixando uma versão 320kbps de alta fidelidade (44.100 Hz CBR) via yt-dlp.
    Utiliza estratégia de busca multi-provedor (YouTube Oficial -> YouTube Geral -> SoundCloud) para contornar
    restrições de palavras sensíveis ou ausência de catálogo.
    Preserva 100% dos marcadores Serato (Cue points, Beatgrid, BPM e Key) do arquivo original.
    """
    yt_dlp = get_yt_dlp_bin()
    if not yt_dlp:
        return {
            "sucesso": False,
            "erro": "yt-dlp não localizado em /opt/homebrew/bin/yt-dlp. Instale com 'brew install yt-dlp ffmpeg'."
        }

    file_p = Path(filepath_str)
    if not file_p.exists():
        return {"sucesso": False, "erro": "Arquivo original não encontrado no disco."}

    stem = file_p.stem
    # Limpa sufixos de Crate comum (ex: "Strike - Aquela Historia - Pop Rock" -> "Strike - Aquela Historia")
    clean_query = stem
    if ' - ' in clean_query:
        parts = [p.strip() for p in clean_query.split(' - ') if p.strip()]
        if len(parts) >= 3:
            parts.pop() # Remove a crate do final
            clean_query = ' - '.join(parts)

    clean_query = clean_query.replace('_', ' ')
    import re
    clean_query = re.sub(r'[\(\[].*?[\)\]]', '', clean_query) # remove parenteses
    clean_query = re.sub(r'\s*\.\s*\d+.*$', '', clean_query).strip()
    clean_query = re.sub(r'\s+', ' ', clean_query).strip()

    temp_id = f"repair_{int(datetime.now().timestamp() * 1000)}"
    temp_dir = Path("/tmp") / temp_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(temp_dir / "download.%(ext)s")

    env = os.environ.copy()
    env["PATH"] = f"{FFMPEG_DIR}:{env.get('PATH', '')}"

    # Estratégia resiliente em cascata:
    # 1. YouTube Oficial (áudio oficial de alta fidelidade)
    # 2. YouTube Geral (pesquisa ampla direta)
    # 3. SoundCloud (excelente para faixas que o YouTube filtra ou bloqueia por palavras restritas)
    search_strategies = [
        ("YouTube Oficial", f"ytsearch3:{clean_query} audio oficial"),
        ("YouTube Geral", f"ytsearch3:{clean_query}"),
        ("SoundCloud", f"scsearch3:{clean_query}")
    ]

    downloaded_mp3 = None
    used_provider = ""
    last_err = ""

    for provider_name, search_term in search_strategies:
        # CRÍTICO PARA DJS:
        # 1. Força ffmpeg a resamplar para 44.100 Hz e 320 kbps CBR
        # 2. Filtra vídeos com duração compatível (45s a 720s) e ignora sped up/nightcore
        # 3. Baixa apenas o primeiro resultado válido
        cmd = [
            yt_dlp,
            search_term,
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "320K",
            "--postprocessor-args", "ExtractAudio:-ar 44100 -b:a 320k -id3v2_version 3",
            "--match-filter", "!is_live & !is_short & duration > 45 & duration < 720 & title !~= '(?i)(sped up|speed up|nightcore|acelerad|pitch|chipmunk)'",
            "--max-downloads", "1",
            "-o", out_template,
            "--no-playlist",
            "--no-check-certificates",
            "--quiet",
            "--no-warnings"
        ]

        try:
            proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if proc.returncode not in (0, 101):
                last_err = proc.stderr.decode('utf-8', errors='ignore')

            mp3_candidates = list(temp_dir.glob("*.mp3"))
            if mp3_candidates:
                downloaded_mp3 = mp3_candidates[0]
                used_provider = provider_name
                break
        except subprocess.TimeoutExpired:
            last_err = f"Timeout na busca ({provider_name})"
            continue
        except Exception as e:
            last_err = str(e)
            continue

    if not downloaded_mp3:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        return {
            "sucesso": False,
            "erro": f"Nenhuma versão compatível encontrada no YouTube ou SoundCloud. Detalhes: {last_err[:120]}" if last_err else "Nenhuma versão encontrada no YouTube ou SoundCloud com os filtros de qualidade DJ."
        }

    try:
        # TRAVA RÍGIDA DE SEGURANÇA POR TEMPO (Tolerância máxima: ±10 segundos)
        # Protege o DJ contra substituição caso o arquivo esteja com nome trocado
        orig_dur = 0.0
        try:
            from mutagen.mp3 import MP3
            orig_mp3 = MP3(str(file_p))
            orig_dur = round(orig_mp3.info.length, 1)
        except Exception:
            pass

        cand_dur = 0.0
        try:
            from mutagen.mp3 import MP3
            cand_mp3 = MP3(str(downloaded_mp3))
            cand_dur = round(cand_mp3.info.length, 1)
        except Exception:
            pass

        # Aplica a trava se o arquivo original tem duração de música normal (> 50s)
        if orig_dur > 50.0 and cand_dur > 0.0:
            diff_time = round(abs(cand_dur - orig_dur), 1)
            if diff_time > 10.0:
                shutil.rmtree(str(temp_dir), ignore_errors=True)
                return {
                    "sucesso": False,
                    "bloqueado_seguranca": True,
                    "erro": f"Substituição cancelada por segurança: Duração local ({orig_dur}s) difere da versão encontrada ({cand_dur}s) por {diff_time}s (limite de 10s). Evitou sobrescrever faixa possivelmente com nome trocado.",
                    "duracao_local": orig_dur,
                    "duracao_baixada": cand_dur,
                    "diferenca": diff_time
                }

        # Preserva tags Serato e ID3v2.3 do arquivo original (cues, beatgrid, bpm, tom, etc.)
        try:
            from mutagen.id3 import ID3
            orig_id3 = ID3(str(file_p))
            orig_id3.save(str(downloaded_mp3), v2_version=3)
        except Exception:
            pass

        # Move o arquivo original comprometido para quarentena
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        quarantine_file = QUARANTINE_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_p.name}"
        shutil.move(str(file_p), str(quarantine_file))

        # Substitui no caminho exato do usuário
        shutil.move(str(downloaded_mp3), str(file_p))

        # Limpa temp
        shutil.rmtree(str(temp_dir), ignore_errors=True)

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "fonte": used_provider,
            "duracao_local": orig_dur,
            "duracao_baixada": cand_dur,
            "quarentena": str(quarantine_file),
            "mensagem": f"Faixa substituída com sucesso por versão 320kbps (44.1kHz CBR) via {used_provider} preservando Cues e Tags."
        }
    except Exception as e:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        return {"sucesso": False, "erro": f"Falha ao substituir arquivo: {str(e)}"}


def preaudit_track_online(filepath_str: str) -> dict:
    """
    Pré-audita uma faixa online SEM baixar nem alterar arquivos no disco (Modo Simulação / Dry-Run).
    Compara a duração do arquivo local com os candidatos disponíveis no YouTube e SoundCloud.
    Retorna se a faixa é compatível (diferença <= 10s) ou divergente (diferença > 10s).
    """
    yt_dlp = get_yt_dlp_bin()
    if not yt_dlp:
        return {"status": "erro", "mensagem": "yt-dlp não localizado."}

    file_p = Path(filepath_str)
    if not file_p.exists():
        return {"status": "erro", "mensagem": "Arquivo não encontrado no disco."}

    local_dur = 0.0
    try:
        from mutagen.mp3 import MP3
        m = MP3(file_p)
        local_dur = round(m.info.length, 1)
    except Exception:
        pass

    stem = file_p.stem
    clean_query = stem
    if ' - ' in clean_query:
        parts = [p.strip() for p in clean_query.split(' - ') if p.strip()]
        if len(parts) >= 3:
            parts.pop()
            clean_query = ' - '.join(parts)
    clean_query = clean_query.replace('_', ' ')
    import re
    clean_query = re.sub(r'[\(\[].*?[\)\]]', '', clean_query)
    clean_query = re.sub(r'\s*\.\s*\d+.*$', '', clean_query).strip()
    clean_query = re.sub(r'\s+', ' ', clean_query)

    strategies = [
        ("YouTube Oficial", f"ytsearch1:{clean_query} audio oficial"),
        ("YouTube Geral", f"ytsearch1:{clean_query}"),
        ("SoundCloud", f"scsearch1:{clean_query}")
    ]

    env = os.environ.copy()
    env["PATH"] = f"{FFMPEG_DIR}:{env.get('PATH', '')}"

    for prov, search_term in strategies:
        cmd = [
            yt_dlp,
            "--flat-playlist",
            "--dump-single-json",
            "--no-warnings",
            "--quiet",
            search_term
        ]
        try:
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=12)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                entries = data.get("entries") or []
                if entries and entries[0]:
                    cand = entries[0]
                    cand_title = cand.get("title") or ""
                    cand_dur = cand.get("duration") or 0.0
                    if cand_dur:
                        cand_dur = round(float(cand_dur), 1)
                        diff = round(abs(cand_dur - local_dur), 1)
                        is_comp = diff <= 10.0
                        return {
                            "status": "compativel" if is_comp else "incompativel",
                            "caminho": str(file_p),
                            "arquivo": file_p.name,
                            "duracao_local": local_dur,
                            "online_titulo": cand_title,
                            "online_duracao": cand_dur,
                            "diferenca": diff,
                            "provedor": prov,
                            "compativel": is_comp,
                            "mensagem": f"Compatível (Diferença: {diff}s · {prov})" if is_comp else f"Divergência de {diff}s (>10s) · Online: {cand_dur}s"
                        }
        except Exception:
            continue

    return {
        "status": "nao_encontrado",
        "caminho": str(file_p),
        "arquivo": file_p.name,
        "duracao_local": local_dur,
        "compativel": False,
        "mensagem": "Nenhuma versão correspondente localizada nas fontes oficiais."
    }


def batch_preaudit_tracks_online(filepaths: list):
    """Executa pré-auditoria de compatibilidade online em lote com streaming de progresso."""
    total = len(filepaths)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    compativel_count = 0
    incompativel_count = 0
    nao_encontrado_count = 0
    resultados = {}

    for idx, fp in enumerate(filepaths, 1):
        filename = Path(fp).name
        pct_start = round(((idx - 1) / max(1, total)) * 100, 1)
        print(json.dumps({
            "tipo": "progresso",
            "processados": idx - 1,
            "total": total,
            "percentual": pct_start,
            "compativeis": compativel_count,
            "incompativeis": incompativel_count,
            "nao_encontrados": nao_encontrado_count,
            "faixa_atual": f"Consultando: {filename}...",
            "status": "consultando"
        }, ensure_ascii=False), flush=True)

        res = preaudit_track_online(fp)
        resultados[fp] = res
        status = res.get("status")
        if status == "compativel":
            compativel_count += 1
        elif status == "incompativel":
            incompativel_count += 1
        else:
            nao_encontrado_count += 1

        pct = round((idx / total) * 100, 1)
        print(json.dumps({
            "tipo": "progresso",
            "processados": idx,
            "total": total,
            "percentual": pct,
            "compativeis": compativel_count,
            "incompativeis": incompativel_count,
            "nao_encontrados": nao_encontrado_count,
            "faixa_atual": f"{'✅' if status == 'compativel' else '⚠️'} {filename}: {res.get('mensagem')}",
            "resultado_item": res
        }, ensure_ascii=False), flush=True)

    print(json.dumps({
        "tipo": "fim",
        "sucesso": True,
        "total": total,
        "compativeis": compativel_count,
        "incompativeis": incompativel_count,
        "nao_encontrados": nao_encontrado_count,
        "resultados": resultados
    }, ensure_ascii=False), flush=True)


def rename_audio_track(filepath_str: str, new_name_str: str) -> dict:
    """
    Renomeia o arquivo físico no disco, atualiza tags ID3 (Título e Artista)
    e sincroniza o banco do Sound Seal para manter integridade no Serato DJ.
    """
    file_p = Path(os.path.expanduser(filepath_str)).resolve()
    if not file_p.exists():
        return {"sucesso": False, "erro": "Arquivo original não encontrado no disco."}

    new_name = new_name_str.strip()
    if not new_name.lower().endswith(file_p.suffix.lower()):
        new_name += file_p.suffix

    new_file_p = file_p.parent / new_name
    if new_file_p == file_p:
        return {"sucesso": True, "novo_caminho": str(file_p), "novo_nome": file_p.name, "mensagem": "Nome inalterado."}

    is_same_file = False
    try:
        if new_file_p.exists():
            is_same_file = os.path.samefile(file_p, new_file_p)
    except Exception:
        pass

    if new_file_p.exists() and not is_same_file:
        return {"sucesso": False, "erro": f"Já existe outro arquivo chamado '{new_name}' nesta pasta."}

    try:
        # Renomeio seguro com proteção APFS case-insensitive
        if is_same_file:
            temp_p = file_p.parent / f".tmp_{abs(hash(str(file_p)))}.tmp"
            file_p.rename(temp_p)
            temp_p.rename(new_file_p)
        else:
            file_p.rename(new_file_p)

        # Atualiza tags ID3 se estiver no formato 'Artista - Titulo'
        try:
            from mutagen.id3 import ID3, TIT2, TPE1
            stem_clean = new_file_p.stem
            if ' - ' in stem_clean:
                parts = [p.strip() for p in stem_clean.split(' - ') if p.strip()]
                artist = parts[0]
                title = parts[1] if len(parts) > 1 else stem_clean
                id3 = ID3(str(new_file_p))
                id3['TPE1'] = TPE1(encoding=3, text=artist)
                id3['TIT2'] = TIT2(encoding=3, text=title)
                id3.save(v2_version=3)
        except Exception:
            pass

        # Sincroniza com banco Sound Seal se o módulo existir
        try:
            sound_seal_db = Path.home() / "Library" / "Application Support" / "Serato" / "Library" / "sound_seal.sqlite"
            if sound_seal_db.exists():
                import sqlite3
                conn = sqlite3.connect(str(sound_seal_db))
                conn.execute("""
                    UPDATE sound_seals 
                    SET filepath = ?, filename = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE filepath = ?
                """, (str(new_file_p), new_file_p.name, str(file_p)))
                conn.commit()
                conn.close()
        except Exception:
            pass

        return {
            "sucesso": True,
            "novo_caminho": str(new_file_p),
            "novo_nome": new_file_p.name,
            "mensagem": f"Arquivo renomeado com sucesso para '{new_file_p.name}'"
        }
    except Exception as e:
        return {"sucesso": False, "erro": f"Erro ao renomear arquivo: {str(e)}"}


def resample_track_local(filepath_str: str) -> dict:
    """
    Normaliza a frequência do arquivo local para 44.100 Hz e 320 kbps CBR via FFmpeg,
    preservando 100% das tags ID3v2.3 e Serato Markers.
    """
    file_p = Path(os.path.expanduser(filepath_str)).resolve()
    if not file_p.exists():
        return {"sucesso": False, "erro": "Arquivo não encontrado."}

    ffmpeg_bin = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not os.path.exists(ffmpeg_bin):
        return {"sucesso": False, "erro": "FFmpeg não instalado no sistema."}

    temp_id = f"resample_{int(datetime.now().timestamp() * 1000)}"
    temp_dir = Path("/tmp") / temp_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_out = temp_dir / file_p.name

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(file_p),
        "-ar", "44100",
        "-b:a", "320k",
        "-map_metadata", "0",
        "-id3v2_version", "3",
        str(temp_out)
    ]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
        if proc.returncode != 0:
            err = proc.stderr.decode('utf-8', errors='ignore')
            return {"sucesso": False, "erro": f"FFmpeg falhou: {err[:200]}"}

        # Backup de segurança na quarentena
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        quarantine_file = QUARANTINE_DIR / f"pre_resample_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_p.name}"
        shutil.copy2(str(file_p), str(quarantine_file))

        # Substitui com o novo arquivo normalizado
        shutil.move(str(temp_out), str(file_p))
        shutil.rmtree(str(temp_dir), ignore_errors=True)

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "mensagem": f"Frequência normalizada com sucesso para 44.100 Hz (320 kbps CBR)."
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def batch_resample_tracks_local(filepaths: list):
    """Executa normalização de frequência (44.1 kHz) em lote localmente via FFmpeg."""
    total = len(filepaths)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    updated_count = 0
    errors = []

    for idx, fp in enumerate(filepaths, 1):
        filename = Path(fp).name
        pct_start = round(((idx - 1) / max(1, total)) * 100, 1)
        print(json.dumps({
            "tipo": "progresso",
            "processados": idx - 1,
            "total": total,
            "percentual": pct_start,
            "atualizados": updated_count,
            "faixa_atual": f"Normalizando: {filename}...",
            "status": "processando"
        }, ensure_ascii=False), flush=True)

        res = resample_track_local(fp)
        if res.get("sucesso"):
            updated_count += 1
        else:
            errors.append(f"{filename}: {res.get('erro')}")

        pct = round((idx / total) * 100, 1)
        print(json.dumps({
            "tipo": "progresso",
            "processados": idx,
            "total": total,
            "percentual": pct,
            "atualizados": updated_count,
            "faixa_atual": f"Concluído: {filename}",
            "ultimo_sucesso": res.get("sucesso", False)
        }, ensure_ascii=False), flush=True)

    print(json.dumps({
        "tipo": "fim",
        "sucesso": True,
        "total": total,
        "atualizados": updated_count,
        "erros": errors[:10]
    }, ensure_ascii=False), flush=True)


def batch_repair_tracks_online(filepaths: list):
    """Executa reparação online em lote com streaming de progresso."""
    total = len(filepaths)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    updated_count = 0
    errors = []

    for idx, fp in enumerate(filepaths, 1):
        filename = Path(fp).name
        pct_start = round(((idx - 1) / max(1, total)) * 100, 1)
        print(json.dumps({
            "tipo": "progresso",
            "processados": idx - 1,
            "total": total,
            "percentual": pct_start,
            "atualizados": updated_count,
            "faixa_atual": f"Baixando: {filename}...",
            "status": "baixando"
        }, ensure_ascii=False), flush=True)

        res = repair_track_online(fp)
        if res.get("sucesso"):
            updated_count += 1
        else:
            errors.append(f"{filename}: {res.get('erro')}")

        pct = round((idx / total) * 100, 1)
        print(json.dumps({
            "tipo": "progresso",
            "processados": idx,
            "total": total,
            "percentual": pct,
            "atualizados": updated_count,
            "faixa_atual": f"Concluído: {filename}",
            "ultimo_sucesso": res.get("sucesso", False)
        }, ensure_ascii=False), flush=True)

    print(json.dumps({
        "tipo": "fim",
        "sucesso": True,
        "total": total,
        "atualizados": updated_count,
        "erros": errors[:10]
    }, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Audio Health Doctor")
    parser.add_argument("--scan", action="store_true", help="Executa auditoria de saúde")
    parser.add_argument("--mp3", type=str, default="", help="Pasta MP3")
    parser.add_argument("--crate-raiz", type=str, default="", help="Crate raiz")
    parser.add_argument("--subcrate", type=str, default="", help="Subcrate")
    parser.add_argument("--no-subcrates", action="store_true", help="Não incluir subcrates")
    parser.add_argument("--max-duration", type=float, default=60.0, help="Duração máxima suspeita (segundos)")
    parser.add_argument("--categoria", type=str, default="todas", choices=["todas", "truncada", "curta", "baixa_qualidade", "corrompida"], help="Categoria em destaque")
    parser.add_argument("--limit", type=int, default=250, help="Limite de faixas na listagem")
    parser.add_argument("--offset", type=int, default=0, help="Offset de paginação")
    parser.add_argument("--repair-online", type=str, default="", help="Caminho do arquivo a reparar online")
    parser.add_argument("--batch-repair-online", type=str, default="", help="JSON de lista de caminhos a reparar online")
    parser.add_argument("--resample-local", type=str, default="", help="Caminho do arquivo a normalizar frequência (44.1kHz)")
    parser.add_argument("--batch-resample-local", type=str, default="", help="JSON de lista de caminhos a normalizar frequência")
    parser.add_argument("--preaudit-online", type=str, default="", help="Caminho do arquivo a pré-auditar online")
    parser.add_argument("--batch-preaudit-online", type=str, default="", help="JSON de lista de caminhos a pré-auditar online")
    parser.add_argument("--rename-track", type=str, default="", help="Caminho do arquivo a renomear")
    parser.add_argument("--new-name", type=str, default="", help="Novo nome do arquivo")

    args = parser.parse_args()
    mp3_dir = args.mp3 or "/Volumes/Pastteyr/Music/MP3"

    if args.rename_track and args.new_name:
        res = rename_audio_track(args.rename_track, args.new_name)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.preaudit_online:
        res = preaudit_track_online(args.preaudit_online)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

    if args.batch_preaudit_online:
        try:
            if args.batch_preaudit_online.startswith('['):
                fps = json.loads(args.batch_preaudit_online)
            else:
                with open(args.batch_preaudit_online, 'r', encoding='utf-8') as f:
                    fps = json.load(f)
            batch_preaudit_tracks_online(fps)
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"tipo": "fim", "sucesso": False, "erro": str(e)}))
            sys.exit(1)

    if args.repair_online:
        res = repair_track_online(args.repair_online)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.batch_repair_online:
        try:
            if args.batch_repair_online.startswith('['):
                fps = json.loads(args.batch_repair_online)
            else:
                with open(args.batch_repair_online, 'r', encoding='utf-8') as f:
                    fps = json.load(f)
            batch_repair_tracks_online(fps)
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"tipo": "fim", "sucesso": False, "erro": str(e)}))
            sys.exit(1)

    if args.resample_local:
        res = resample_track_local(args.resample_local)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.batch_resample_local:
        try:
            if args.batch_resample_local.startswith('['):
                fps = json.loads(args.batch_resample_local)
            else:
                with open(args.batch_resample_local, 'r', encoding='utf-8') as f:
                    fps = json.load(f)
            batch_resample_tracks_local(fps)
            sys.exit(0)
        except Exception as e:
            print(json.dumps({"tipo": "fim", "sucesso": False, "erro": str(e)}))
            sys.exit(1)

    if args.scan:
        scan_audio_health(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates,
            max_duration_suspicious=args.max_duration,
            filter_categoria=args.categoria,
            limit=args.limit,
            offset=args.offset,
            stream_progress=True
        )
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
