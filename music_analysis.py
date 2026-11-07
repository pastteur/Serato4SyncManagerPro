#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - ANÁLISE DE BPM E TOM (music_analysis.py)
================================================================================
Estimativa local de BPM e tonalidade SEM dependências externas (sem numpy,
aubio ou librosa). O áudio é decodificado como PCM mono por FFmpeg e analisado
em Python puro.

- BPM: envelope de energia por quadro + autocorrelação com comb-filter (60–200).
- Tom: Goertzel nas notas C3–B4 + perfis de Krumhansl-Schmuckler (maior/menor).
  Converte para notação Camelot (8A/8B...), usada para mixagem harmônica.

Limitações honestas:
- Estimativas, não garantias. Faixas com tempo variável ou muito ruído podem
  errar; o campo de confiança indica quando o resultado é fraco.
- Tom aproximado: acordes ambíguos ou modos (dórico, mixolídio) podem sair
  como o tom relativo.

Escrita de tags: somente MP3 (ID3v2.3, campos TBPM e TKEY). Antes de qualquer
escrita o estado anterior do bloco ID3 é gravado no journal (undo).
================================================================================
"""

import sys
import os

sys.dont_write_bytecode = True
import math
import json
import shutil
import argparse
import subprocess
from array import array
from pathlib import Path

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

try:
    import mutagen
    from mutagen.id3 import ID3, TBPM, TKEY
except ImportError:
    mutagen = None
    ID3 = None

ANALYSIS_SR = 11025
BPM_MIN = 70.0
BPM_MAX = 180.0
BPM_STEP = 0.5
BPM_SECONDS = 90
KEY_FRAME = 2048
KEY_FRAMES = 40
KEY_MIDI_RANGE = range(48, 72)  # C3 .. B4

FFMPEG_CANDIDATES = [
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    shutil.which("ffmpeg") or ""
]

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Kessler profiles
KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

# Notação Camelot (mixagem harmônica)
CAMELOT_MAJOR = {0: "8B", 1: "3B", 2: "10B", 3: "5B", 4: "12B", 5: "7B",
                 6: "2B", 7: "9B", 8: "4B", 9: "11B", 10: "6B", 11: "1B"}
CAMELOT_MINOR = {0: "5A", 1: "12A", 2: "7A", 3: "2A", 4: "9A", 5: "4A",
                 6: "11A", 7: "6A", 8: "1A", 9: "8A", 10: "3A", 11: "10A"}


def get_ffmpeg_bin():
    for p in FFMPEG_CANDIDATES:
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def decode_mono_pcm(filepath, seconds=BPM_SECONDS, start=0.0, sr=ANALYSIS_SR):
    """Decodifica o áudio como PCM 16-bit mono. Retorna array('h') ou None."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        return None
    cmd = [
        ffmpeg, "-v", "error",
        "-ss", str(round(float(start), 2)),
        "-t", str(float(seconds)),
        "-i", str(filepath),
        "-ac", "1", "-ar", str(sr),
        "-f", "s16le", "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    samples = array('h')
    samples.frombytes(proc.stdout[: len(proc.stdout) - (len(proc.stdout) % 2)])
    if sys.byteorder == 'big':
        samples.byteswap()
    return samples


def _onset_envelope(samples, hop=128):
    """Envelope de onsets: aumento positivo da energia logarítmica por quadro."""
    energies = []
    for i in range(0, len(samples) - hop, hop):
        acc = 0
        for v in samples[i:i + hop]:
            acc += v * v
        energies.append(math.log1p(acc / hop))
    if len(energies) < 4:
        return [], 0.0
    onsets = [0.0] + [max(0.0, energies[i] - energies[i - 1]) for i in range(1, len(energies))]
    fps = sr_frame_rate(hop)
    return onsets, fps


def sr_frame_rate(hop):
    return ANALYSIS_SR / float(hop)


def _lag_corr(onsets, lag):
    n = len(onsets)
    if lag <= 0 or lag >= n:
        return None
    acc = 0.0
    for i in range(n - lag):
        acc += onsets[i] * onsets[i + lag]
    return acc / (n - lag)


def _comb_score(onsets, lag_frames):
    """Correlação do envelope em múltiplos do período (1x e 2x), com atraso fracionário."""
    score = 0.0
    for mult, weight in ((1, 1.0), (2, 0.5)):
        lag = lag_frames * mult
        l0 = int(math.floor(lag))
        frac = lag - l0
        c0 = _lag_corr(onsets, l0)
        c1 = _lag_corr(onsets, l0 + 1)
        if c0 is None:
            continue
        if c1 is None:
            c1 = c0
        score += weight * ((1.0 - frac) * c0 + frac * c1)
    return score


def estimate_bpm(samples):
    """Retorna (bpm, confiança 0..1). Confiança = pico / média dos candidatos."""
    onsets, fps = _onset_envelope(samples)
    if not onsets or fps <= 0:
        return 0.0, 0.0

    scores = {}
    bpm = BPM_MIN
    while bpm <= BPM_MAX + 1e-9:
        period_frames = 60.0 * fps / bpm
        scores[round(bpm, 2)] = _comb_score(onsets, period_frames)
        bpm += BPM_STEP

    if not scores:
        return 0.0, 0.0

    best_bpm = max(scores, key=lambda b: scores[b])
    best = scores[best_bpm]
    if best <= 0:
        return 0.0, 0.0

    # Correção de oitava: prefere a leitura na faixa de dança 90–150 BPM
    if best_bpm < 90.0 and scores.get(round(best_bpm * 2, 2), 0) >= 0.9 * best and best_bpm * 2 <= BPM_MAX:
        best_bpm = round(best_bpm * 2, 2)
    elif best_bpm > 150.0 and scores.get(round(best_bpm / 2, 2), 0) >= 0.9 * best and best_bpm / 2 >= BPM_MIN:
        best_bpm = round(best_bpm / 2, 2)

    mean = sum(scores.values()) / len(scores)
    confidence = 0.0 if mean <= 0 else min(1.0, max(0.0, (best / mean - 1.0) / 4.0))
    return float(best_bpm), round(confidence, 3)


def _goertzel_power(frame, freq, sr):
    w = 2.0 * math.pi * freq / sr
    coeff = 2.0 * math.cos(w)
    s1 = 0.0
    s2 = 0.0
    for x in frame:
        s0 = x + coeff * s1 - s2
        s2 = s1
        s1 = s0
    return s1 * s1 + s2 * s2 - coeff * s1 * s2


def _chroma(samples):
    n = len(samples)
    if n < KEY_FRAME * 2:
        return None
    hann = [0.5 - 0.5 * math.cos(2 * math.pi * i / (KEY_FRAME - 1)) for i in range(KEY_FRAME)]

    # Escolhe quadros com energia acima da mediana (evita silêncio)
    positions = list(range(0, n - KEY_FRAME, KEY_FRAME))
    if len(positions) > KEY_FRAMES:
        step = len(positions) / float(KEY_FRAMES)
        positions = [positions[int(i * step)] for i in range(KEY_FRAMES)]

    energies = []
    for p in positions:
        energies.append(sum(v * v for v in samples[p:p + KEY_FRAME]))
    if not energies:
        return None
    median = sorted(energies)[len(energies) // 2]

    chroma = [0.0] * 12
    used = 0
    freqs = [(m, 440.0 * (2.0 ** ((m - 69) / 12.0))) for m in KEY_MIDI_RANGE]
    for p, e in zip(positions, energies):
        if e < median:
            continue
        frame = [samples[p + i] * hann[i] for i in range(KEY_FRAME)]
        for midi, freq in freqs:
            chroma[midi % 12] += _goertzel_power(frame, freq, ANALYSIS_SR)
        used += 1
    if used == 0:
        return None
    total = sum(chroma)
    if total <= 0:
        return None
    return [c / total for c in chroma]


def _pearson(a, b):
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def estimate_key(samples):
    """Retorna dict com tom, Camelot e confiança, ou None."""
    chroma = _chroma(samples)
    if chroma is None:
        return None
    best = None
    for tonic in range(12):
        for mode, profile in (("major", KK_MAJOR), ("minor", KK_MINOR)):
            rotated = [profile[(i - tonic) % 12] for i in range(12)]
            corr = _pearson(chroma, rotated)
            if best is None or corr > best[0]:
                best = (corr, tonic, mode)
    corr, tonic, mode = best
    name = "%s %s" % (PITCH_NAMES[tonic], mode)
    camelot = CAMELOT_MAJOR[tonic] if mode == "major" else CAMELOT_MINOR[tonic]
    return {"tom": name, "camelot": camelot, "confianca": round(max(0.0, corr), 3)}


def analyze_file(filepath, seconds=BPM_SECONDS):
    """Analisa BPM e tom de um arquivo. Não grava nada."""
    samples = decode_mono_pcm(filepath, seconds=seconds)
    if not samples or len(samples) < ANALYSIS_SR:
        return {"sucesso": False, "erro": "Não foi possível decodificar o áudio (FFmpeg ausente ou arquivo inválido)"}

    bpm, bpm_conf = estimate_bpm(samples)
    key = estimate_key(samples) or {"tom": "", "camelot": "", "confianca": 0.0}
    return {
        "sucesso": True,
        "arquivo": Path(filepath).name,
        "bpm": round(bpm, 1),
        "bpm_confianca": bpm_conf,
        "tom": key["tom"],
        "camelot": key["camelot"],
        "tom_confianca": key["confianca"],
    }


def write_analysis_tags(filepath, bpm=None, key_text=None, overwrite=False):
    """Grava TBPM/TKEY em MP3. Registra o estado anterior no journal antes da escrita."""
    if ID3 is None:
        return {"sucesso": False, "erro": "Mutagen não instalado"}
    path = Path(filepath)
    if path.suffix.lower() != ".mp3":
        return {"sucesso": False, "erro": "Escrita de BPM/Tom automatizada apenas para MP3 (ID3)"}
    try:
        tags = ID3(str(path))
    except Exception:
        tags = ID3()

    alterou = False
    if bpm and (overwrite or not tags.get("TBPM")):
        tags.delall("TBPM")
        tags.add(TBPM(encoding=3, text=str(int(round(float(bpm))))))
        alterou = True
    if key_text and (overwrite or not tags.get("TKEY")):
        tags.delall("TKEY")
        tags.add(TKEY(encoding=3, text=key_text))
        alterou = True

    if not alterou:
        return {"sucesso": True, "arquivo": path.name, "mensagem": "Sem alterações (campos já preenchidos)", "gravado": False}

    try:
        from journal import record_id3_before_change
        record_id3_before_change(str(path), action="analise_bpm_tom")
    except Exception as e:
        return {"sucesso": False, "erro": "Journal indisponível; escrita cancelada por segurança: %s" % e}

    try:
        tags.save(str(path), v2_version=3)
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}
    return {"sucesso": True, "arquivo": path.name, "mensagem": "BPM/Tom gravados", "gravado": True}


def analyze_batch(folder, limit=50, write=False, only_missing=True, emit=True):
    """Analisa arquivos de uma pasta. Emite progresso em JSON por linha quando emit=True."""
    root = Path(os.path.expanduser(folder))
    files = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        for f in filenames:
            if f.startswith('.') or Path(f).suffix.lower() != ".mp3":
                continue
            files.append(Path(dirpath) / f)
    files.sort()

    if only_missing and mutagen is not None:
        pending = []
        for p in files:
            try:
                t = ID3(str(p))
                if t.get("TBPM") and t.get("TKEY"):
                    continue
            except Exception:
                pass
            pending.append(p)
        files = pending

    files = files[: max(1, int(limit))]
    total = len(files)
    resultados = []
    for idx, p in enumerate(files, 1):
        res = analyze_file(p)
        item = {"arquivo": str(p), "nome": p.name}
        if res.get("sucesso"):
            item.update({k: res[k] for k in ("bpm", "bpm_confianca", "tom", "camelot", "tom_confianca")})
            if write:
                w = write_analysis_tags(str(p), bpm=res["bpm"], key_text=res["camelot"], overwrite=False)
                item["gravado"] = bool(w.get("gravado"))
                if not w.get("sucesso"):
                    item["erro"] = w.get("erro")
        else:
            item["erro"] = res.get("erro")
        resultados.append(item)
        if emit:
            print(json.dumps({"tipo": "progresso", "processados": idx, "total": total,
                              "faixa": p.name, "resultado": item}, ensure_ascii=False), flush=True)

    final = {"tipo": "fim", "sucesso": True, "total": total,
             "analisadas": sum(1 for r in resultados if "bpm" in r),
             "gravadas": sum(1 for r in resultados if r.get("gravado")),
             "erros": sum(1 for r in resultados if r.get("erro"))}
    if emit:
        print(json.dumps(final, ensure_ascii=False), flush=True)
    return final


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Análise de BPM e Tom")
    parser.add_argument("--analyze", type=str, default="", help="Analisa BPM/Tom de um arquivo (não grava)")
    parser.add_argument("--analyze-batch", type=str, default="", help="Analisa uma pasta de MP3")
    parser.add_argument("--limit", type=int, default=50, help="Máximo de faixas no lote")
    parser.add_argument("--write", action="store_true", help="Grava TBPM/TKEY (apenas MP3, com journal)")
    parser.add_argument("--include-filled", action="store_true", help="Inclui faixas que já têm BPM e tom")
    args = parser.parse_args()

    if args.analyze:
        res = analyze_file(args.analyze)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0 if res.get("sucesso") else 1)

    if args.analyze_batch:
        final = analyze_batch(args.analyze_batch, limit=args.limit, write=args.write,
                              only_missing=not args.include_filled, emit=True)
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
