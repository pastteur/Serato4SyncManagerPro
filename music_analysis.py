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
from typing import Optional, Dict, Any, List

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

try:
    import mutagen
    from mutagen.id3 import ID3, TBPM, TKEY, TIT1, COMM
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
    str(Path(__file__).resolve().parent / "bin" / "ffmpeg"),
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


def estimate_energy(samples, onsets=None):
    """
    Calcula nível de energia de pista (1 a 10) combinando Loudness RMS
    e densidade de transientes/onsets.
    """
    if not samples or len(samples) < 512:
        return {"energy": 5, "rms_db": -18.0, "confianca": 0.0}

    # 1. RMS Loudness
    acc = 0.0
    for s in samples:
        acc += s * s
    rms = math.sqrt(acc / len(samples))
    ratio = max(1e-6, rms / 32767.0)
    rms_db = 20.0 * math.log10(ratio)

    # 2. Onset Density & Transients
    if onsets is None:
        onsets, _ = _onset_envelope(samples)

    avg_onset = sum(onsets) / max(1, len(onsets)) if onsets else 0.0

    # 3. Escala calibrada 1-10 (Loudness RMS entre -28 dB e -6 dB)
    norm_rms = (rms_db - (-28.0)) / ((-6.0) - (-28.0))
    norm_rms = max(0.0, min(1.0, norm_rms))

    transient_bonus = min(0.25, avg_onset * 0.5)
    raw_score = 1.0 + (norm_rms * 8.0) + (transient_bonus * 4.0)
    energy = int(round(max(1.0, min(10.0, raw_score))))

    return {
        "energy": energy,
        "rms_db": round(rms_db, 1),
        "confianca": round(min(1.0, norm_rms + 0.2), 2)
    }


def analyze_file(filepath, seconds=BPM_SECONDS):
    """Analisa BPM, tom e energia de um arquivo. Não grava nada."""
    samples = decode_mono_pcm(filepath, seconds=seconds)
    if not samples or len(samples) < ANALYSIS_SR:
        return {"sucesso": False, "erro": "Não foi possível decodificar o áudio (FFmpeg ausente ou arquivo inválido)"}

    bpm, bpm_conf = estimate_bpm(samples)
    key = estimate_key(samples) or {"tom": "", "camelot": "", "confianca": 0.0}
    energy_data = estimate_energy(samples)

    return {
        "sucesso": True,
        "arquivo": Path(filepath).name,
        "bpm": round(bpm, 1),
        "bpm_confianca": bpm_conf,
        "tom": key["tom"],
        "camelot": key["camelot"],
        "tom_confianca": key["confianca"],
        "energy": energy_data["energy"],
        "rms_db": energy_data["rms_db"],
        "energy_confianca": energy_data["confianca"],
    }


def write_energy_tag(filepath, energy: int, target_tag: str = "grouping", overwrite: bool = True):
    """
    Grava Energy (1-10) em tags ID3v2.3 preservando integralmente frames ID3 não envolvidos,
    comentários adicionais de terceiros/Serato/iTunes, com journal obrigatório e rollback em caso de falha.
    target_tag='grouping': Coluna Grouping do Serato (TIT1: "Energy 7")
    target_tag='comment': Prefixa na coluna Comment padrão do Serato (COMM: "[Energy 7]")
    target_tag='both': Grava em ambos
    """
    if ID3 is None:
        return {"sucesso": False, "erro": "Mutagen não instalado"}
    path = Path(filepath)
    if path.suffix.lower() != ".mp3":
        return {"sucesso": False, "erro": "Apenas MP3 suportado para tags ID3"}

    if not path.is_file():
        return {"sucesso": False, "erro": f"Arquivo não encontrado: {path}"}

    try:
        tags = ID3(str(path))
    except Exception:
        tags = ID3()

    energy_val = max(1, min(10, int(energy)))
    alterou = False

    # 1. Atualização estrita de TIT1 (Grouping) preservando Grouping manual pré-existente
    if target_tag in ("grouping", "both"):
        import re as _re
        existing_grouping = str(tags["TIT1"]) if "TIT1" in tags else ""
        # Remove eventuais prefixos ou sufixos de Energy anteriores sem destruir texto manual
        cleaned_grouping = _re.sub(r'Energy\s*\d+\s*[-|/]?\s*', '', existing_grouping, flags=_re.IGNORECASE).strip()
        cleaned_grouping = _re.sub(r'[-|/]?\s*Energy\s*\d+', '', cleaned_grouping, flags=_re.IGNORECASE).strip()

        if cleaned_grouping:
            new_grouping = f"Energy {energy_val} - {cleaned_grouping}"
        else:
            new_grouping = f"Energy {energy_val}"

        tags.delall("TIT1")
        tags.add(TIT1(encoding=3, text=new_grouping))
        alterou = True

    # 2. Atualização estrita de COMM (Comment) preservando comentários de outras tags/descrições
    if target_tag in ("comment", "both"):
        import re as _re
        comm_frames = tags.getall("COMM")
        target_comm_frame = None
        for frame in comm_frames:
            if getattr(frame, 'desc', '') in ("", "Comment"):
                target_comm_frame = frame
                break

        existing_comm_text = ""
        if target_comm_frame and target_comm_frame.text:
            existing_comm_text = str(target_comm_frame.text[0])

        cleaned_comm = _re.sub(r'\[Energy \d+\]\s*', '', existing_comm_text).strip()
        new_comm = f"[Energy {energy_val}] {cleaned_comm}".strip()

        # Remove APENAS o frame padrão específico a atualizar, preservando todos os demais comentários
        if target_comm_frame:
            remaining_comm = [f for f in comm_frames if f is not target_comm_frame]
            tags.delall("COMM")
            for f in remaining_comm:
                tags.add(f)

        tags.add(COMM(encoding=3, lang='eng', desc='', text=[new_comm]))
        alterou = True

    if not alterou:
        return {"sucesso": True, "gravado": False}

    # 3. Registro mandatório no Journal (fail-closed: se falhar o journal, aborta a escrita)
    try:
        from journal import record_id3_before_change, record_operation_after, undo_operation
        op_id = record_id3_before_change(str(path), action="gravacao_energy")
    except Exception as j_err:
        return {
            "sucesso": False,
            "erro": f"Cancelado por segurança: Falha obrigatória no Journal de auditoria: {j_err}"
        }

    # 4. Gravação física em ID3v2.3
    try:
        tags.save(str(path), v2_version=3)
    except Exception as e:
        return {"sucesso": False, "erro": f"Erro de I/O ao salvar tags ID3: {e}"}

    # 5. Validação pós-escrita e integridade
    try:
        check_tags = ID3(str(path))
        if target_tag in ("grouping", "both") and not check_tags.get("TIT1"):
            raise IOError("Frame TIT1 (Grouping) não foi encontrado após a gravação.")
        if target_tag in ("comment", "both") and not check_tags.getall("COMM"):
            raise IOError("Frame COMM (Comment) não foi encontrado após a gravação.")
        # Sela no journal com hash final
        record_operation_after(op_id, str(path))
        return {"sucesso": True, "gravado": True, "energy": energy_val, "target": target_tag}
    except Exception as v_err:
        # Rollback automático restaurando estado prévio
        try:
            undo_operation(op_id)
        except Exception:
            pass
        return {
            "sucesso": False,
            "erro": f"Validação pós-escrita falhou ({v_err}). Rollback automático executado."
        }


def analyze_energy_batch(folder, limit=50, write=True, target_tag="grouping", emit=True,
                         serato_dir="", crate_name=""):
    """Analisa e opcionalmente grava Energy para lote de arquivos (biblioteca ou crate específica)."""
    files = []
    if serato_dir and crate_name:
        from crate_ops import get_crate_path, library_root_for
        from serato_macos_app import parse_crate_binary
        serato = Path(os.path.expanduser(str(serato_dir))).resolve()
        crate_path = get_crate_path(serato / "Subcrates", crate_name)
        if not crate_path.exists():
            err = {"tipo": "fim", "sucesso": False, "total": 0, "analisadas": 0, "gravadas": 0,
                   "erros": 1, "resultados": [], "erro": f"Crate não encontrada: {crate_name}"}
            if emit:
                print(json.dumps(err, ensure_ascii=False), flush=True)
            return err
        _, rel_paths, _, _ = parse_crate_binary(crate_path.read_bytes())
        lib_root = library_root_for(serato)
        for rel in rel_paths:
            p = lib_root / rel
            if p.is_file() and p.suffix.lower() == ".mp3":
                files.append(p)
    else:
        root = Path(os.path.expanduser(folder))
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            for f in filenames:
                if f.startswith('.') or Path(f).suffix.lower() != ".mp3":
                    continue
                files.append(Path(dirpath) / f)
        files.sort()

    if limit and int(limit) > 0:
        files = files[: int(limit)]
    total = len(files)
    resultados = []

    for idx, p in enumerate(files, 1):
        res = analyze_file(p)
        item = {"arquivo": str(p), "nome": p.name}
        if res.get("sucesso"):
            item["energy"] = res.get("energy", 5)
            item["rms_db"] = res.get("rms_db", -18.0)
            if write:
                w = write_energy_tag(str(p), energy=res["energy"], target_tag=target_tag)
                item["gravado"] = bool(w.get("gravado"))
                if not w.get("sucesso"):
                    item["erro"] = w.get("erro")
        else:
            item["erro"] = res.get("erro")
        resultados.append(item)
        if emit:
            print(json.dumps({"tipo": "progresso", "processados": idx, "total": total,
                              "faixa": p.name, "resultado": item}, ensure_ascii=False), flush=True)

    import uuid
    final = {"tipo": "fim", "sucesso": True, "total": total,
             "analisadas": sum(1 for r in resultados if "energy" in r),
             "gravadas": sum(1 for r in resultados if r.get("gravado")),
             "erros": sum(1 for r in resultados if r.get("erro")),
             "resultados": resultados,
             "operacao_id": str(uuid.uuid4())}
    if emit:
        print(json.dumps(final, ensure_ascii=False), flush=True)
    return final


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

    if limit and int(limit) > 0:
        files = files[: int(limit)]
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


def camelot_compatibility_score(c1: str, c2: str) -> float:
    """
    Calcula pontuação de compatibilidade harmônica (0.0 a 1.0) entre duas chaves Camelot.
    Ex: 8A e 8A -> 1.0 (mesma chave)
        8A e 7A / 9A -> 0.9 (adjacente)
        8A e 8B -> 0.85 (relativo maior/menor)
        8A e 10A -> 0.75 (energy boost +2)
    """
    if not c1 or not c2:
        return 0.5
    c1, c2 = c1.strip().upper(), c2.strip().upper()
    if c1 == c2:
        return 1.0

    try:
        num1 = int(c1[:-1])
        letter1 = c1[-1]
        num2 = int(c2[:-1])
        letter2 = c2[-1]
    except Exception:
        return 0.5

    if letter1 == letter2:
        diff = abs(num1 - num2)
        if diff in (1, 11):
            return 0.9
        if (num2 - num1) % 12 == 2:
            return 0.75  # Energy boost
        if diff in (2, 10):
            return 0.6
    else:
        if num1 == num2:
            return 0.85  # Relativo maior/menor
        diff = abs(num1 - num2)
        if diff in (1, 11):
            return 0.65

    return 0.2


def generate_curated_set(serato_dir: str, crate_name: str, profile: str = "warmup",
                         max_tracks: int = 20, start_track: Optional[str] = None,
                         dry_run: bool = False, exclude_incomplete: bool = False) -> Dict[str, Any]:
    """
    Ghost Curator / Set Curator:
    Ordena faixas de forma harmônica com controle de BPM e curva de energia.
    Não presume dados ausentes como reais, identifica campos faltantes,
    calcula nível de confiança por faixa e suporta modo dry-run para prévia.
    """
    import uuid
    from crate_ops import get_crate_path, write_crate_atomic, library_root_for
    from serato_macos_app import parse_crate_binary

    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    crate_path = get_crate_path(subcrates, crate_name)

    if not crate_path.exists():
        return {"sucesso": False, "erro": f"Crate de origem não encontrada: {crate_name}"}

    try:
        data = crate_path.read_bytes()
        header_antigo, existentes, _, outros_blocos = parse_crate_binary(data)
    except Exception as e:
        return {"sucesso": False, "erro": f"Erro ao ler crate: {e}"}

    if not existentes:
        return {"sucesso": False, "erro": "A crate de origem não possui faixas."}

    root = library_root_for(serato)
    candidates = []
    faixas_incompletas = 0

    for rel in existentes:
        full_p = root / rel
        bpm = None
        camelot = None
        energy = None
        artist = ""

        if full_p.exists() and mutagen is not None:
            try:
                t = ID3(str(full_p))
                if t.get("TBPM"):
                    try:
                        bpm = float(str(t["TBPM"]).split()[0])
                    except Exception:
                        bpm = None
                if t.get("TKEY"):
                    k = str(t["TKEY"]).strip()
                    if k:
                        camelot = k
                if t.get("TIT1"):
                    tit1_str = str(t["TIT1"])
                    import re as _re
                    m = _re.search(r'\d+', tit1_str)
                    if m:
                        energy = int(m.group(0))
                if t.get("TPE1"):
                    artist = str(t["TPE1"]).strip().lower()
            except Exception:
                pass

        # Identifica campos ausentes sem assumir dados fictícios
        ausentes = []
        if bpm is None:
            ausentes.append("BPM")
        if camelot is None:
            ausentes.append("Camelot")
        if energy is None:
            ausentes.append("Energy")

        is_completo = (len(ausentes) == 0)
        if not is_completo:
            faixas_incompletas += 1

        if exclude_incomplete and not is_completo:
            continue

        if len(ausentes) >= 3:
            confianca = 0.0
        else:
            confianca = max(0.0, 1.0 - (len(ausentes) / 3.0))

        candidates.append({
            "rel": rel,
            "filename": full_p.name,
            "bpm": bpm,
            "bpm_efetivo": bpm if bpm is not None else 126.0,
            "camelot": camelot,
            "camelot_efetivo": camelot if camelot else "8A",
            "energy": energy,
            "energy_efetivo": energy if energy is not None else 5,
            "artist": artist,
            "completo": is_completo,
            "campos_ausentes": ausentes,
            "confianca": round(confianca, 2),
            "status_metadados": "medido" if is_completo else ("parcial" if len(ausentes) < 3 else "desconhecido")
        })

    if not candidates:
        msg = "Nenhuma faixa com análise musical completa encontrada." if exclude_incomplete else "Nenhuma faixa válida encontrada na crate."
        return {"sucesso": False, "erro": msg}

    total_needed = min(len(candidates), max(1, int(max_tracks)))
    curated = []
    available = list(candidates)

    current = None
    if start_track:
        for c in available:
            if start_track.lower() in c["filename"].lower() or start_track.lower() in c["rel"].lower():
                current = c
                break

    if current is None:
        if profile == "warmup":
            current = min(available, key=lambda x: x["energy_efetivo"])
        else:
            current = available[0]

    curated.append(current)
    available.remove(current)

    for step in range(1, total_needed):
        if not available:
            break

        if profile == "warmup":
            target_energy = 3.0 + (step / max(1, total_needed - 1)) * 5.5
        elif profile == "peak":
            target_energy = 8.0 + (step % 2) * 1.5
        elif profile == "rollercoaster":
            target_energy = 6.0 + 3.0 * math.sin(step * math.pi / 4.0)
        else:
            target_energy = current["energy_efetivo"]

        best_cand = None
        best_score = -999.0

        for cand in available:
            harm_score = camelot_compatibility_score(current["camelot_efetivo"], cand["camelot_efetivo"])
            bpm_diff = abs(current["bpm_efetivo"] - cand["bpm_efetivo"]) / max(1.0, current["bpm_efetivo"])
            bpm_score = max(0.0, 1.0 - (bpm_diff / 0.08))
            energy_score = max(0.0, 1.0 - (abs(cand["energy_efetivo"] - target_energy) / 10.0))
            artist_penalty = 0.4 if (current["artist"] and current["artist"] == cand["artist"]) else 0.0

            # Pontuação ponderada incluindo confiabilidade dos metadados
            confidence_weight = cand["confianca"]
            total_score = ((harm_score * 0.45) + (bpm_score * 0.35) + (energy_score * 0.20) - artist_penalty) * (0.7 + 0.3 * confidence_weight)
            if total_score > best_score:
                best_score = total_score
                best_cand = cand

        if best_cand:
            curated.append(best_cand)
            available.remove(best_cand)
            current = best_cand
        else:
            cand = available.pop(0)
            curated.append(cand)
            current = cand

    safe_target = f"[Set] {crate_name}".replace('/', '%%')
    new_crate_path = get_crate_path(subcrates, safe_target)
    final_rel_paths = [c["rel"] for c in curated]
    operacao_id = str(uuid.uuid4())

    summary_tracks = [
        {
            "nome": c["filename"],
            "caminho_rel": c["rel"],
            "bpm": c["bpm"],
            "camelot": c["camelot"],
            "energy": c["energy"],
            "confianca": c["confianca"],
            "status_metadados": c["status_metadados"],
            "campos_ausentes": c["campos_ausentes"]
        }
        for c in curated
    ]

    # MODO PRÉVIA (DRY RUN)
    if dry_run:
        return {
            "sucesso": True,
            "dry_run": True,
            "operacao_id": operacao_id,
            "crate_alvo": new_crate_path.stem,
            "caminho_crate": str(new_crate_path),
            "total_curated": len(curated),
            "total_origem": len(existentes),
            "faixas_incompletas": faixas_incompletas,
            "profile": profile,
            "mensagem": f"Prévia da crate [{new_crate_path.stem}] calculada com {len(curated)} faixas. Nenhuma alteração gravada.",
            "curated_tracks": summary_tracks
        }

    # EXECUÇÃO FÍSICA
    res = write_crate_atomic(new_crate_path, final_rel_paths, header_antigo, outros_blocos, action_name="ghost_curator")
    if res["sucesso"]:
        res["operacao_id"] = operacao_id
        res["crate_name"] = new_crate_path.stem
        res["total_curated"] = len(curated)
        res["faixas_incompletas"] = faixas_incompletas
        res["mensagem"] = f"Crate curada [{new_crate_path.stem}] gravada com {len(curated)} faixas (Perfil: {profile})."
        res["curated_tracks"] = summary_tracks

    return res


def main():
    parser = argparse.ArgumentParser(description="Serato 4 Sync Manager Pro - Análise de BPM, Tom e Energia")
    parser.add_argument("--analyze", type=str, default="", help="Analisa BPM/Tom/Energy de um arquivo (não grava)")
    parser.add_argument("--analyze-batch", type=str, default="", help="Analisa uma pasta de MP3")
    parser.add_argument("--energy-batch", type=str, default="", help="Analisa e grava energia para lote de faixas")
    parser.add_argument("--target-tag", type=str, default="grouping", choices=["grouping", "comment", "both"],
                        help="Campo onde a Energy será gravada (grouping = TIT1, comment = COMM)")
    parser.add_argument("--curate-set", action="store_true", help="Gera uma crate curada (Ghost Curator)")
    parser.add_argument("--commit", action="store_true", help="Executa a gravação física (por padrão gera apenas prévia dry-run)")
    parser.add_argument("--exclude-incomplete", action="store_true", help="Descarta faixas com análise incompleta")
    parser.add_argument("--serato", type=str, default="", help="Diretório _Serato_")
    parser.add_argument("--crate", type=str, default="", help="Nome da Crate para curadoria")
    parser.add_argument("--profile", type=str, default="warmup", choices=["warmup", "peak", "rollercoaster", "harmonic"])
    parser.add_argument("--max-tracks", type=int, default=20, help="Máximo de faixas para a crate curada")
    parser.add_argument("--start-track", type=str, default="", help="Faixa inicial opcional")
    parser.add_argument("--limit", type=int, default=50, help="Máximo de faixas no lote")
    parser.add_argument("--write", action="store_true", help="Grava TBPM/TKEY (apenas MP3, com journal)")
    parser.add_argument("--include-filled", action="store_true", help="Inclui faixas que já têm BPM e tom")
    args = parser.parse_args()

    if args.curate_set:
        if not args.serato or not args.crate:
            print(json.dumps({"sucesso": False, "erro": "--serato e --crate são obrigatórios para curadoria"}))
            sys.exit(1)
        res = generate_curated_set(args.serato, args.crate, profile=args.profile,
                                   max_tracks=args.max_tracks, start_track=args.start_track,
                                   dry_run=not args.commit, exclude_incomplete=args.exclude_incomplete)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

    if args.energy_batch:
        final = analyze_energy_batch(args.energy_batch, limit=args.limit, write=args.write,
                                     target_tag=args.target_tag, emit=True,
                                     serato_dir=args.serato, crate_name=args.crate)
        sys.exit(0)

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
