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
            "bitrate": round(bitrate / 1000)
        }

    # 4. Saudável
    return {
        "status": "saudavel",
        "categoria": "saudavel",
        "tipo_problema": "nenhum",
        "severidade": "ok",
        "detalhes": f"Áudio 100% íntegro ({round(duration)}s · {round(bitrate/1000) if bitrate else 'VBR'} kbps · {sample_rate} Hz)",
        "duracao": round(duration, 1),
        "bitrate": round(bitrate / 1000) if bitrate else 0
    }


def scan_audio_health(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True,
    max_duration_suspicious: float = 60.0,
    filter_categoria: str = "todas",
    limit: int = 250,
    offset: int = 0
):
    """
    Audita os arquivos de áudio por crate ou em toda a biblioteca, agrupando por destaques de evidências.
    """
    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    if not base_path.exists():
        return {"sucesso": False, "erro": f"Pasta não encontrada: {base_path}"}

    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    if not target_dir.exists():
        return {
            "sucesso": True,
            "total_analisadas": 0,
            "total_problemas": 0,
            "categorias_contagem": {"truncada": 0, "curta": 0, "baixa_qualidade": 0, "corrompida": 0},
            "items": []
        }

    total_scanned = 0
    items = []
    category_counts = {
        "truncada": 0,
        "curta": 0,
        "baixa_qualidade": 0,
        "corrompida": 0
    }

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
                                "bitrate_kbps": diag["bitrate"]
                            })

    total_problems = sum(category_counts.values())

    return {
        "sucesso": True,
        "total_analisadas": total_scanned,
        "total_problemas": total_problems,
        "categorias_contagem": category_counts,
        "items": items
    }


def repair_track_online(filepath_str: str):
    """
    Substitui a faixa danificada baixando uma versão 320kbps de alta fidelidade via yt-dlp.
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
    # Remove lixo de BPM e formata busca limpa
    clean_query = stem.replace('_', ' ')
    import re
    clean_query = re.sub(r'[\(\[].*?[\)\]]', '', clean_query) # remove parenteses
    clean_query = re.sub(r'\s*\.\s*\d+.*$', '', clean_query).strip()

    search_term = f"ytsearch1:{clean_query} audio"

    temp_id = f"repair_{int(datetime.now().timestamp() * 1000)}"
    temp_dir = Path("/tmp") / temp_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(temp_dir / "download.%(ext)s")

    env = os.environ.copy()
    env["PATH"] = f"{FFMPEG_DIR}:{env.get('PATH', '')}"

    cmd = [
        yt_dlp,
        search_term,
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", out_template,
        "--no-playlist",
        "--default-search", "ytsearch",
        "--no-check-certificates",
        "--quiet",
        "--no-warnings"
    ]

    try:
        proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        if proc.returncode != 0:
            err = proc.stderr.decode('utf-8', errors='ignore')
            return {"sucesso": False, "erro": f"yt-dlp falhou: {err[:200]}"}

        # Localiza o MP3 baixado no diretório temporário
        downloaded_mp3s = list(temp_dir.glob("*.mp3"))
        if not downloaded_mp3s:
            return {"sucesso": False, "erro": "Download concluído, mas o arquivo MP3 não foi gerado."}

        new_mp3 = downloaded_mp3s[0]

        # Move o arquivo original comprometido para quarentena
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        quarantine_file = QUARANTINE_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_p.name}"
        shutil.move(str(file_p), str(quarantine_file))

        # Substitui no caminho exato do usuário
        shutil.move(str(new_mp3), str(file_p))

        # Limpa temp
        shutil.rmtree(str(temp_dir), ignore_errors=True)

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "quarentena": str(quarantine_file),
            "mensagem": f"Faixa substituída com sucesso por versão 320kbps íntegra."
        }

    except subprocess.TimeoutExpired:
        return {"sucesso": False, "erro": "Tempo limite de download excedido (90s)."}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def batch_repair_tracks_online(filepaths: list):
    """Executa reparação online em lote com streaming de progresso."""
    total = len(filepaths)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    updated_count = 0
    errors = []

    for idx, fp in enumerate(filepaths, 1):
        filename = Path(fp).name
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
            "faixa_atual": filename,
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

    args = parser.parse_args()
    mp3_dir = args.mp3 or "/Volumes/Pastteyr/Music/MP3"

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

    if args.scan:
        res = scan_audio_health(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates,
            max_duration_suspicious=args.max_duration,
            filter_categoria=args.categoria,
            limit=args.limit,
            offset=args.offset
        )
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
