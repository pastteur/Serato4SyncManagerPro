#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - AUDIO HEALTH DOCTOR (audio_health.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Auditoria profunda de saúde de áudio: detecta faixas cortadas no meio (downloads
interrompidos), faixas muito curtas (< 60s), arquivos corrompidos e baixa fidelidade.
================================================================================
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

try:
    import mutagen
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.wave import WAVE
except ImportError:
    mutagen = None

AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')


def inspect_track_health(filepath: Path, min_duration_sec: float = 60.0):
    """
    Audita um arquivo de áudio e retorna diagnóstico de saúde e integridade.
    """
    filename = filepath.name
    try:
        filesize = filepath.stat().st_size
    except Exception as e:
        return {
            "status": "erro",
            "tipo_problema": "arquivo_inacessivel",
            "severidade": "alta",
            "detalhes": f"Erro de I/O: {e}",
            "duracao": 0,
            "bitrate": 0
        }

    # Arquivo vazio ou quase vazio
    if filesize < 10240: # Menos de 10 KB
        return {
            "status": "comprometida",
            "tipo_problema": "arquivo_vazio",
            "severidade": "critica",
            "detalhes": f"Arquivo minúsculo ({round(filesize/1024, 1)} KB). Não é uma música válida.",
            "duracao": 0,
            "bitrate": 0
        }

    duration = 0.0
    bitrate = 0
    sample_rate = 0
    channels = 0
    is_truncated = False
    truncation_reason = ""

    if mutagen:
        try:
            audio = mutagen.File(str(filepath))
            if audio is None:
                return {
                    "status": "comprometida",
                    "tipo_problema": "formato_invalido",
                    "severidade": "critica",
                    "detalhes": "Cabeçalho de áudio inválido ou irreconhecível.",
                    "duracao": 0,
                    "bitrate": 0
                }

            if hasattr(audio, 'info'):
                info = audio.info
                duration = getattr(info, 'length', 0.0)
                bitrate = getattr(info, 'bitrate', 0)
                sample_rate = getattr(info, 'sample_rate', 0)
                channels = getattr(info, 'channels', 0)

            # Verificação de truncamento / interrupção de download
            # Se tiver bitrate e duração declarada, compara tamanho físico esperado vs real
            if bitrate > 0 and duration > 0:
                expected_audio_bytes = (duration * bitrate) / 8.0
                ratio = filesize / expected_audio_bytes
                # Se o arquivo tiver menos de 75% dos bytes esperados para o bitrate declarado
                if ratio < 0.70 and duration > 30:
                    is_truncated = True
                    truncation_reason = f"Tamanho físico ({round(filesize/(1024*1024), 1)} MB) é {round((1-ratio)*100)}% menor que o esperado para {round(duration)}s a {round(bitrate/1000)}kbps."

        except Exception as e:
            return {
                "status": "comprometida",
                "tipo_problema": "corrompida",
                "severidade": "alta",
                "detalhes": f"Erro ao decodificar frames de áudio: {e}",
                "duracao": 0,
                "bitrate": 0
            }

    # Diagnósticos específicos

    # 1. Truncada / Cortada no meio
    if is_truncated:
        return {
            "status": "comprometida",
            "tipo_problema": "truncada_cortada",
            "severidade": "critica",
            "detalhes": f"Download incompleto ou áudio quebrado: {truncation_reason}",
            "duracao": round(duration, 1),
            "bitrate": round(bitrate / 1000) if bitrate else 0
        }

    # 2. Faixa muito curta (Preview / Vinheta acidental)
    if 0 < duration < min_duration_sec:
        return {
            "status": "suspeita",
            "tipo_problema": "muito_curta",
            "severidade": "media",
            "detalhes": f"Duração muito curta ({round(duration)}s). Provável preview ou vinheta incompleta.",
            "duracao": round(duration, 1),
            "bitrate": round(bitrate / 1000) if bitrate else 0
        }

    # 3. Baixa taxa de bits (Fidelidade baixa para pista de dança)
    if 0 < bitrate < 192000:
        return {
            "status": "atencao",
            "tipo_problema": "baixa_fidelidade",
            "severidade": "baixa",
            "detalhes": f"Qualidade de apenas {round(bitrate / 1000)} kbps. Recomendado substituir por 320 kbps para som potente.",
            "duracao": round(duration, 1),
            "bitrate": round(bitrate / 1000)
        }

    # 4. Saudável
    return {
        "status": "saudavel",
        "tipo_problema": "nenhum",
        "severidade": "ok",
        "detalhes": f"Áudio 100% íntegro ({round(duration)}s · {round(bitrate/1000) if bitrate else 'VBR'} kbps · {sample_rate} Hz)",
        "duracao": round(duration, 1),
        "bitrate": round(bitrate / 1000) if bitrate else 0
    }


def scan_audio_health(mp3_base_dir: str, min_duration_sec: float = 60.0, limit: int = 50, offset: int = 0, filter_issues_only: bool = True):
    """
    Varre a pasta de músicas e compila o relatório de saúde de forma ágil com paginação sob demanda.
    """
    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    if not base_path.exists():
        return {"sucesso": False, "erro": f"Pasta não encontrada: {base_path}"}

    total_files = 0
    items = []

    for root, _, files in os.walk(str(base_path)):
        if '/.' in root or '\\.' in root:
            continue
        rel_folder = os.path.relpath(root, str(base_path))

        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            ext = Path(f).suffix.lower()
            if ext in AUDIO_EXTENSIONS:
                total_files += 1

                if total_files > offset and len(items) < limit:
                    full_p = Path(root) / f
                    diag = inspect_track_health(full_p, min_duration_sec=min_duration_sec)
                    is_issue = diag["status"] != "saudavel"

                    if (filter_issues_only and is_issue) or not filter_issues_only:
                        crate_parts = [p for p in rel_folder.replace('\\', '/').split('/') if p]
                        crate_raiz = crate_parts[0] if crate_parts else ""
                        items.append({
                            "id": f"health-{total_files}",
                            "caminho": str(full_p),
                            "arquivo": f,
                            "pasta": rel_folder,
                            "crate": crate_raiz,
                            "status": diag["status"],
                            "tipo_problema": diag["tipo_problema"],
                            "severidade": diag["severidade"],
                            "detalhes": diag["detalhes"],
                            "duracao_seg": diag["duracao"],
                            "bitrate_kbps": diag["bitrate"]
                        })

    return {
        "sucesso": True,
        "total_analisadas": total_files,
        "total_problemas": len(items),
        "limit": limit,
        "offset": offset,
        "items": items
    }


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Audio Health Doctor")
    parser.add_argument("--scan", action="store_true", help="Executa auditoria de saúde")
    parser.add_argument("--mp3", type=str, default="", help="Pasta MP3")
    parser.add_argument("--min-duration", type=float, default=60.0, help="Duração mínima considerada normal (segundos)")
    parser.add_argument("--limit", type=int, default=50, help="Limite de faixas na listagem")
    parser.add_argument("--offset", type=int, default=0, help="Offset de paginação")
    parser.add_argument("--all", action="store_true", help="Lista todas as faixas (não apenas com problemas)")

    args = parser.parse_args()
    mp3_dir = args.mp3 or "/Volumes/Pastteyr/Music/MP3"

    if args.scan:
        res = scan_audio_health(
            mp3_dir,
            min_duration_sec=args.min_duration,
            limit=args.limit,
            offset=args.offset,
            filter_issues_only=not args.all
        )
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
