#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 5 SYNC MANAGER PRO - AUTO-CUE GENERATOR & REPAIR (auto_cue.py)
macOS Tahoe / Apple Silicon & Intel
================================================================================
Gera, grava e repara marcadores oficiais de Hot Cues para o Serato DJ Pro 4
(Intro, Drop 1, Breakdown, Drop 2, Outro) nas tags GEOB:Serato Markers2.
Suporta varredura, aplicação por Crate/Subcrate e reparação de tags em lote
com streaming de progresso e backup de segurança blindado contra sobrescritas.
================================================================================
"""

import sys
import os

sys.dont_write_bytecode = True
import json
import math
import base64
import struct
import sqlite3
import shutil
import subprocess
import argparse
from array import array
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Garante flushing imediato
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

# Vendor fallback: permite carregar dependências empacotadas sem exigir pip local
_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if _VENDOR_DIR.is_dir() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

try:
    import mutagen
    from mutagen.id3 import ID3, GEOB
except ImportError:
    mutagen = None

AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.aif', '.aiff', '.m4a', '.mp4', '.aac', '.ogg')

CUE_COLORS = {
    "red": b'\xcc\x00\x00',
    "blue": b'\x00\x66\xcc',
    "yellow": b'\xcc\xcc\x00',
    "green": b'\x00\xcc\x00',
    "orange": b'\xcc\x66\x00',
    "purple": b'\x99\x00\xcc'
}

BACKUP_DB_PATH = Path.home() / ".serato_sync_cues_backup.sqlite"


def get_backup_db():
    """Conecta e inicializa o banco SQLite de backups de segurança de Hot Cues."""
    conn = sqlite3.connect(str(BACKUP_DB_PATH), timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cues_backup (
            filepath TEXT PRIMARY KEY,
            filename TEXT,
            markers2_blob BLOB,
            markers1_blob BLOB,
            cues_json TEXT,
            created_at TEXT
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_backup_created ON cues_backup(created_at);")
    conn.commit()
    return conn


def list_cue_backups(limit: int = 300, search: str = ""):
    """
    Lista os backups de cues disponíveis para restauração, do mais recente ao mais antigo.
    Cada linha traz também se o arquivo original ainda existe no disco.
    """
    if not BACKUP_DB_PATH.exists():
        return {"sucesso": True, "total": 0, "items": []}
    try:
        conn = get_backup_db()
        conn.row_factory = sqlite3.Row
        query = "SELECT filepath, filename, cues_json, created_at FROM cues_backup"
        params = []
        if search.strip():
            query += " WHERE filename LIKE ? OR filepath LIKE ?"
            termo = f"%{search.strip()}%"
            params = [termo, termo]
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))

        items = []
        for row in conn.execute(query, params).fetchall():
            try:
                qtd_cues = len(json.loads(row["cues_json"] or "[]"))
            except Exception:
                qtd_cues = 0
            items.append({
                "filepath": row["filepath"],
                "filename": row["filename"],
                "quantidade_cues": qtd_cues,
                "created_at": row["created_at"],
                "arquivo_existe": Path(row["filepath"]).exists(),
            })
        conn.close()
        return {"sucesso": True, "total": len(items), "items": items}
    except Exception as e:
        return {"sucesso": False, "erro": str(e), "total": 0, "items": []}


def restore_track_cues(filepath_str: str):
    """
    Restaura o payload de cues exatamente como estava antes da primeira alteração.
    Se não existia cue algum antes, remove as tags GEOB:Serato Markers2/Markers_ que
    tenham sido gravadas, devolvendo a faixa ao estado original.
    """
    if not mutagen:
        return {"sucesso": False, "erro": "Mutagen não instalado"}
    if not BACKUP_DB_PATH.exists():
        return {"sucesso": False, "erro": "Nenhum backup de cues disponível"}

    file_p = Path(filepath_str)
    if not file_p.exists():
        return {"sucesso": False, "erro": "Arquivo não encontrado no disco"}

    try:
        conn = get_backup_db()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT markers2_blob, markers1_blob FROM cues_backup WHERE filepath = ?",
            (str(file_p),)
        ).fetchone()
        conn.close()

        if row is None:
            return {"sucesso": False, "erro": "Esta faixa não possui backup de cues registrado"}

        audio = mutagen.File(str(file_p))
        if audio is None:
            return {"sucesso": False, "erro": "Formato de áudio não suportado"}
        if audio.tags is None:
            audio.add_tags()

        m2_bytes = row["markers2_blob"]
        m1_bytes = row["markers1_blob"]

        if m2_bytes:
            audio.tags['GEOB:Serato Markers2'] = GEOB(
                encoding=0,
                mime='application/octet-stream',
                desc='Serato Markers2',
                data=bytes(m2_bytes)
            )
        else:
            audio.tags.delall('GEOB:Serato Markers2')

        if m1_bytes:
            audio.tags['GEOB:Serato Markers_'] = GEOB(
                encoding=0,
                mime='application/octet-stream',
                desc='Serato Markers_',
                data=bytes(m1_bytes)
            )
        else:
            audio.tags.delall('GEOB:Serato Markers_')

        audio.save(v2_version=3)

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "mensagem": "Cues restaurados ao estado anterior às alterações.",
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def backup_track_cues(filepath: str, audio) -> bool:
    """
    Salva uma cópia exata das tags de cues antes de qualquer modificação.
    Garante persistência verificada inclusive quando a faixa não possui tags ou cues existentes.
    """
    if audio is None:
        return False
    try:
        m2_bytes = None
        m1_bytes = None
        cues = []
        if hasattr(audio, 'tags') and audio.tags is not None:
            m2 = audio.tags.get('GEOB:Serato Markers2')
            m1 = audio.tags.get('GEOB:Serato Markers_')
            m2_bytes = m2.data if m2 else None
            m1_bytes = m1.data if m1 else None
            cues = extract_cues_from_raw_tag(m2_bytes) if m2_bytes else []

        cues_json = json.dumps(cues, ensure_ascii=False)

        conn = get_backup_db()
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO cues_backup
                (filepath, filename, markers2_blob, markers1_blob, cues_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                str(filepath),
                Path(filepath).name,
                m2_bytes,
                m1_bytes,
                cues_json,
                datetime.now().isoformat()
            ))
            # Verificação obrigatória de persistência no banco SQLite
            row = conn.execute("SELECT 1 FROM cues_backup WHERE filepath = ?", (str(filepath),)).fetchone()
            if not row:
                raise IOError("Verificação de persistência do backup de cues falhou.")
        conn.close()
        return True
    except Exception as e:
        print(f"Erro ao salvar backup de cues para {filepath}: {e}", file=sys.stderr)
        return False


def build_serato_markers2_tag(cues: list, color_rgb: bytes = b'\xff\xff\xff', bpmlock: bool = False) -> bytes:
    """
    Gera o payload binário GEOB:Serato Markers2 100% em conformidade com as especificações do Serato DJ Pro.
    Estrutura:
      1. Header mágico: \x01\x01
      2. Bloco COLOR: 'COLOR\x00' + >I len (4) + \x00 + 3-byte RGB
      3. Blocos CUE (0..7): 'CUE\x00' + >I len + (>cBIc3s2s + label\\x00)
      4. Bloco BPMLOCK: 'BPMLOCK\x00' + >I len (1) + 1 byte (\\x00 ou \\x01) — CRÍTICO: DEVE vir no final
      5. Empacotamento em Base64 com substituição obrigatória de '=' por 'A' (especificação Serato)
      6. Inserção de \\n (0x0A) a cada 72 caracteres
      7. \\x01\\x01 + base64_bytes, preenchido até 470 bytes mínimos com \\x00
    """
    entries = []

    # 1. COLOR entry
    color_data = b'\x00' + color_rgb[:3]
    entries.append(b'COLOR\x00' + struct.pack('>I', len(color_data)) + color_data)

    # 2. CUE entries
    for c in cues:
        label = c.get("label", "")
        label_bytes = label.encode('utf-8') + b'\x00'
        cue_color = c.get("color", b'\xcc\x00\x00')
        if isinstance(cue_color, str):
            cue_color = CUE_COLORS.get(cue_color, b'\xcc\x00\x00')

        # FMT = '>cBIc3s2s' (12 bytes de cabeçalho do cue + label null-terminated)
        cue_data = struct.pack(
            '>cBIc3s2s',
            b'\x00',
            int(c['index']) & 0x07,
            int(c['pos_ms']),
            b'\x00',
            cue_color[:3],
            b'\x00\x00'
        ) + label_bytes

        entries.append(b'CUE\x00' + struct.pack('>I', len(cue_data)) + cue_data)

    # 3. BPMLOCK entry (obrigatoriamente o último elemento)
    bpm_data = b'\x01' if bpmlock else b'\x00'
    entries.append(b'BPMLOCK\x00' + struct.pack('>I', len(bpm_data)) + bpm_data)

    # Monta payload binário completo
    payload = struct.pack('BB', 0x01, 0x01) + b''.join(entries)

    # Converte para base64 com substituição do padding '=' por 'A'
    b64_bytes = bytearray(base64.b64encode(payload).replace(b'=', b'A'))

    # Quebra de linha oficial a cada 72 caracteres
    i = 72
    while i < len(b64_bytes):
        b64_bytes.insert(i, 0x0A)
        i += 73

    # Empacota no frame final com cabeçalho \x01\x01 e preenchimento de 470 bytes
    tag_data = struct.pack('BB', 0x01, 0x01) + bytes(b64_bytes)
    if len(tag_data) < 470:
        tag_data = tag_data.ljust(470, b'\x00')

    return tag_data


def extract_cues_from_raw_tag(raw_data: bytes) -> list:
    """
    Extrai com segurança quaisquer Hot Cues já gravados no payload binário do Serato Markers2,
    mesmo que o payload tenha a anomalia do BPMLOCK ou ordenação truncada.
    """
    cues = []
    if not raw_data or len(raw_data) < 4:
        return cues

    try:
        null_pos = raw_data.find(b'\x00', 2)
        b64 = raw_data[2:null_pos] if null_pos != -1 else raw_data[2:]
        b64 = b64.replace(b'\n', b'').replace(b'\r', b'')
        
        # Ajusta padding do Base64 do Serato que substitui '=' por 'A'
        rem = len(b64) % 4
        if rem == 2:
            b64_to_decode = b64 + b'=='
        elif rem == 3:
            b64_to_decode = b64 + b'='
        elif rem == 1:
            b64_to_decode = b64[:-1] + b'=='
        else:
            b64_to_decode = b64

        try:
            payload = base64.b64decode(b64_to_decode)
        except Exception:
            # Fallback caso a substituição de 'A' necessite conversão manual
            b64_clean = b64
            while b64_clean.endswith(b'A') and len(b64_clean) % 4 != 0:
                b64_clean = b64_clean[:-1]
            b64_to_decode = b64_clean + (b'=' * (-len(b64_clean) % 4))
            payload = base64.b64decode(b64_to_decode)

        pos = 2
        while pos < len(payload):
            null_idx = payload.find(b'\x00', pos)
            if null_idx == -1:
                break
            name = payload[pos:null_idx].decode('utf-8', errors='ignore')
            if not name:
                pos = null_idx + 1
                continue
            pos = null_idx + 1
            if pos + 4 > len(payload):
                break
            entry_len = struct.unpack('>I', payload[pos:pos+4])[0]
            pos += 4
            entry_data = payload[pos:pos+entry_len]
            pos += entry_len

            if name == 'CUE' and len(entry_data) >= 12:
                _, idx, ms, _, col, _ = struct.unpack('>cBIc3s2s', entry_data[:12])
                lbl = entry_data[12:].rstrip(b'\x00').decode('utf-8', errors='ignore')
                # BUG FIX #1: col é bytes brutos (3 bytes RGB do Serato) —
                # converte para string hex para garantir serialização JSON e
                # interoperabilidade com build_serato_markers2_tag (aceita str via CUE_COLORS
                # mas também bytes diretos; o formato "#rrggbb" é passado pelo frontend).
                col_hex = "#" + col.hex() if isinstance(col, (bytes, bytearray)) else str(col)
                cues.append({
                    "index": idx,
                    "pos_ms": ms,
                    "label": lbl,
                    "color": col_hex
                })
    except Exception:
        pass

    return cues


def get_ffmpeg_bin():
    bundled = str(Path(__file__).resolve().parent / "bin" / "ffmpeg")
    candidates = [
        bundled,
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        shutil.which("ffmpeg") or ""
    ]
    for p in candidates:
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def detect_audio_transients(filepath_str: str, duration_sec: float) -> dict:
    """
    Analisa os transientes reais de áudio (onsets) via decodificação PCM mono pelo FFmpeg,
    separando claramente a detecção de silêncio da detecção de beat/onset e calculando
    um score de confiança objetivo (0.0 a 1.0).
    """
    if not filepath_str or not os.path.exists(filepath_str) or duration_sec < 1.0:
        return {
            "first_beat_ms": None,
            "silence_end_ms": None,
            "has_transient": False,
            "confiavel": False,
            "confianca": 0.0,
            "motivo": "arquivo_ou_duracao_invalida",
        }

    ffmpeg_bin = get_ffmpeg_bin()
    if not ffmpeg_bin:
        return {
            "first_beat_ms": None,
            "silence_end_ms": None,
            "has_transient": False,
            "confiavel": False,
            "confianca": 0.0,
            "motivo": "ffmpeg_indisponivel",
        }

    sr = 10000
    hop = 100  # 10 ms exatos por quadro
    window_sec = min(20.0, max(1.0, float(duration_sec)))

    try:
        cmd = [
            ffmpeg_bin,
            "-v", "error",
            "-ss", "0",
            "-t", f"{window_sec:.2f}",
            "-i", str(filepath_str),
            "-ac", "1",
            "-ar", str(sr),
            "-f", "s16le",
            "-",
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
        if proc.returncode != 0 or not isinstance(proc.stdout, (bytes, bytearray)) or len(proc.stdout) < hop * 2:
            return {
                "first_beat_ms": None,
                "silence_end_ms": None,
                "has_transient": False,
                "confiavel": False,
                "confianca": 0.0,
                "motivo": "ffmpeg_falhou_decodificacao",
            }

        samples = array('h')
        usable = len(proc.stdout) - (len(proc.stdout) % 2)
        samples.frombytes(proc.stdout[:usable])
        if sys.byteorder == 'big':
            samples.byteswap()

        num_frames = len(samples) // hop
        if num_frames < 5:
            return {
                "first_beat_ms": None,
                "silence_end_ms": None,
                "has_transient": False,
                "confiavel": False,
                "confianca": 0.0,
                "motivo": "audio_insuficiente",
            }

        rms_list = []
        db_list = []
        log_e_list = []
        for idx in range(num_frames):
            start = idx * hop
            seg = samples[start:start + hop]
            mean_sq = sum(v * v for v in seg) / float(hop)
            rms = math.sqrt(mean_sq)
            db = 20.0 * math.log10(max(1e-6, rms / 32767.0))
            rms_list.append(rms)
            db_list.append(db)
            log_e_list.append(math.log1p(mean_sq))

        # 1. Estágio separado: detecção de silêncio / piso de ruído
        silence_db_threshold = -40.0
        active_frames = [i for i, db in enumerate(db_list) if db > silence_db_threshold]
        if not active_frames:
            return {
                "first_beat_ms": None,
                "silence_end_ms": None,
                "has_transient": False,
                "confiavel": False,
                "confianca": 0.0,
                "motivo": "silencio_continuo",
            }

        has_initial_silence = db_list[0] <= silence_db_threshold
        silence_end_ms = active_frames[0] * 10 if has_initial_silence else 0

        # 2. Estágio separado: detecção real de onset/transiente (salto brusco de energia)
        # Rejeita fade-ins lentos, ruído plano ou fundo ambiente sem ataque percussivo.
        best_onset_idx = None
        best_onset_score = 0.0

        # Primeiro verifica se há ataque abrupto na janela de saltos (i >= 1)
        for i in range(1, num_frames):
            if db_list[i] < -30.0:
                continue
            pre_start = max(0, i - 5)  # 50 ms anteriores
            pre_rms = sum(rms_list[pre_start:i]) / float(i - pre_start)
            pre_log_e = sum(log_e_list[pre_start:i]) / float(i - pre_start)

            log_jump = log_e_list[i] - pre_log_e
            rms_ratio = rms_list[i] / max(1.0, pre_rms)

            if log_jump >= 2.0 and rms_ratio >= 2.5:
                # Primeiro onset claro e forte encontrado após o silêncio/intro suave
                best_onset_idx = i
                best_onset_score = min(1.0, 0.55 + min(0.45, log_jump / 15.0))
                break

        # Caso o áudio já comece com ataque forte imediato no quadro 0 (sem fade-in)
        if best_onset_idx is None:
            if not has_initial_silence and db_list[0] >= -26.0:
                # Verifica que não é apenas ruído contínuo muito baixo e que mantém energia real
                avg_early_db = sum(db_list[:min(5, num_frames)]) / float(min(5, num_frames))
                if avg_early_db >= -26.0:
                    conf = min(1.0, round(0.70 + max(0.0, (db_list[0] + 26.0) / 40.0), 3))
                    return {
                        "first_beat_ms": 100,
                        "silence_end_ms": silence_end_ms,
                        "has_transient": True,
                        "confiavel": conf >= 0.60,
                        "confianca": conf,
                        "motivo": "ataque_imediato",
                    }

            return {
                "first_beat_ms": None,
                "silence_end_ms": silence_end_ms,
                "has_transient": False,
                "confiavel": False,
                "confianca": 0.25 if active_frames else 0.0,
                "motivo": "sem_transiente_confiavel",
            }

        onset_ms = best_onset_idx * 10
        beat_ms = max(50, int(onset_ms))
        conf = round(best_onset_score, 3)
        return {
            "first_beat_ms": beat_ms,
            "silence_end_ms": silence_end_ms,
            "has_transient": True,
            "confiavel": conf >= 0.60,
            "confianca": conf,
            "motivo": "onset_detectado",
        }

    except Exception as e:
        return {
            "first_beat_ms": None,
            "silence_end_ms": None,
            "has_transient": False,
            "confiavel": False,
            "confianca": 0.0,
            "motivo": f"erro_analise: {e}",
        }


def calculate_smart_cues_detailed(duration_sec: float, bpm_float: float = 0.0, filepath_str: str = "") -> dict:
    """
    Calcula os 5 pontos de Hot Cue com validação estrita da confiança da análise de transientes.
    Quando filepath_str é informado e a análise não for confiável, retorna sucesso=False e cues=[].
    """
    duration_ms = float(duration_sec or 0.0) * 1000.0
    if duration_ms <= 0:
        return {
            "sucesso": False,
            "confiavel": False,
            "confianca": 0.0,
            "motivo": "duracao_invalida",
            "transiente": None,
            "cues": [],
        }

    # Tempo por compasso (4 tempos)
    if bpm_float > 0:
        bar_ms = (60.0 / bpm_float) * 4 * 1000
    else:
        bar_ms = 2000.0  # ~120 BPM padrão

    trans = None
    confiavel = True
    confianca = 0.5
    motivo = "estimativa_matematica_sem_arquivo"

    if filepath_str:
        trans = detect_audio_transients(filepath_str, duration_sec)
        confiavel = bool(trans.get("confiavel", False))
        confianca = float(trans.get("confianca", 0.0))
        motivo = str(trans.get("motivo", "analise_inconclusiva"))
        first_beat_ms = trans.get("first_beat_ms")
        if not confiavel or not trans.get("has_transient") or first_beat_ms is None:
            return {
                "sucesso": False,
                "confiavel": False,
                "confianca": confianca,
                "motivo": motivo,
                "transiente": trans,
                "cues": [],
            }
    else:
        first_beat_ms = 500

    # 1. Intro: Primeiro beat real
    pos_cue1 = int(max(0, min(first_beat_ms, max(0, int(duration_ms) - 1000))))

    # Espaçamento mínimo adaptativo (15s/10s em faixas longas, proporcional em faixas curtas >=10s)
    usable_span = max(1000.0, duration_ms - pos_cue1)
    min_gap_mid = min(15000.0, usable_span * 0.16)
    min_gap_end = min(10000.0, usable_span * 0.12)

    # 2. Drop 1: 16 ou 32 compassos alinhados ao primeiro beat
    bars_for_drop1 = 16 if (bar_ms * 16) >= 20000 else 32
    target_drop1 = pos_cue1 + (bar_ms * bars_for_drop1)
    if target_drop1 > duration_ms * 0.35:
        target_drop1 = pos_cue1 + (bar_ms * 16)
    pos_cue2 = int(max(pos_cue1 + min(500.0, usable_span * 0.08), min(target_drop1, duration_ms * 0.30)))

    # 3. Breakdown (Ponte): Alinhado a compasso próximo da metade
    half_time = duration_ms / 2.0
    bars_to_half = max(1, round((half_time - pos_cue1) / bar_ms))
    raw_cue3 = max(pos_cue2 + min_gap_mid, pos_cue1 + ((bars_to_half - 4) * bar_ms))
    pos_cue3 = int(min(raw_cue3, duration_ms * 0.58))
    if pos_cue3 <= pos_cue2:
        pos_cue3 = int(pos_cue2 + max(250, int(usable_span * 0.12)))

    # 4. Drop 2 (Clímax): Meio da música + 8 compassos
    raw_cue4 = pos_cue1 + ((bars_to_half + 8) * bar_ms)
    pos_cue4 = int(min(duration_ms * 0.78, max(pos_cue3 + min_gap_mid * 0.5, raw_cue4)))
    if pos_cue4 <= pos_cue3:
        pos_cue4 = int(pos_cue3 + max(250, int(usable_span * 0.12)))

    # 5. Outro (Mix-out): 16 compassos antes do fim alinhado ao grid (sempre dentro da faixa)
    bars_total = max(1, int((duration_ms - pos_cue1) / bar_ms))
    bars_outro = max(1, bars_total - 16)
    raw_cue5 = max(pos_cue4 + min_gap_end, pos_cue1 + (bars_outro * bar_ms))
    max_cue5 = int(max(pos_cue4 + 200, duration_ms - min(500.0, duration_ms * 0.03)))
    pos_cue5 = int(min(raw_cue5, max_cue5))
    if pos_cue5 <= pos_cue4:
        pos_cue5 = int(min(duration_ms - 50, pos_cue4 + max(200, int(usable_span * 0.10))))

    cues = [
        {"index": 0, "label": "Intro", "pos_ms": int(pos_cue1), "color": "red", "color_hex": "#cc0000"},
        {"index": 1, "label": "Drop 1", "pos_ms": int(pos_cue2), "color": "blue", "color_hex": "#0066cc"},
        {"index": 2, "label": "Break", "pos_ms": int(pos_cue3), "color": "yellow", "color_hex": "#cccc00"},
        {"index": 3, "label": "Drop 2", "pos_ms": int(pos_cue4), "color": "green", "color_hex": "#00cc00"},
        {"index": 4, "label": "Outro", "pos_ms": int(pos_cue5), "color": "orange", "color_hex": "#cc6600"},
    ]
    return {
        "sucesso": True,
        "confiavel": confiavel,
        "confianca": confianca,
        "motivo": motivo,
        "transiente": trans,
        "cues": cues,
    }


def calculate_smart_cues(duration_sec: float, bpm_float: float = 0.0, filepath_str: str = ""):
    """
    Calcula os 5 pontos de Hot Cue ideais com base na métrica musical de DJs e detecção de transientes.
    Retorna lista vazia ([]) se filepath_str for fornecido e a análise de transientes for inconclusiva.
    """
    res = calculate_smart_cues_detailed(duration_sec, bpm_float=bpm_float, filepath_str=filepath_str)
    return res.get("cues", [])


def repair_track_cues(filepath_str: str) -> dict:
    """
    Repara o arquivo MP3 re-encodando a tag GEOB:Serato Markers2 com o layout binário perfeito.
    Restaura instantaneamente a visibilidade de todos os Hot Cues no Serato DJ Pro.
    """
    if not mutagen:
        return {"sucesso": False, "erro": "Mutagen não instalado"}

    file_p = Path(filepath_str)
    if not file_p.exists():
        return {"sucesso": False, "erro": "Arquivo não encontrado"}

    try:
        audio = mutagen.File(str(file_p))
        if audio is None:
            return {"sucesso": False, "erro": "Formato de áudio não suportado"}

        raw_tag = audio.tags.get('GEOB:Serato Markers2') if audio.tags else None
        if not raw_tag or not hasattr(raw_tag, 'data'):
            return {"sucesso": False, "erro": "Arquivo não possui tag Serato Markers2 para reparar"}

        existing_cues = extract_cues_from_raw_tag(raw_tag.data)
        if not existing_cues:
            # Se não conseguiu extrair cues antigos, recalcula usando duração e BPM apenas se análise for confiável
            duration = getattr(audio.info, 'length', 0.0)
            bpm_val = 0.0
            if 'TBPM' in audio:
                try: bpm_val = float(str(audio['TBPM']).strip().replace(',', '.'))
                except Exception: pass
            cue_calc = calculate_smart_cues_detailed(duration, bpm_val, filepath_str=str(file_p))
            if not cue_calc.get("sucesso") or not cue_calc.get("confiavel") or not cue_calc.get("cues"):
                return {
                    "sucesso": False,
                    "confiavel": False,
                    "confianca": cue_calc.get("confianca", 0.0),
                    "motivo": cue_calc.get("motivo", "analise_inconclusiva"),
                    "erro": f"Não foi possível reparar cues automaticamente: análise inconclusiva ({cue_calc.get('motivo', 'baixa confiança')}).",
                }
            existing_cues = cue_calc["cues"]

        # Salva backup de segurança obrigatório antes de qualquer alteração
        if not backup_track_cues(str(file_p), audio):
            return {"sucesso": False, "erro": "Falha na criação ou verificação obrigatória do backup de cues. Gravação abortada por segurança."}

        # Constrói o novo payload perfeito
        new_tag_data = build_serato_markers2_tag(existing_cues)

        audio.tags['GEOB:Serato Markers2'] = GEOB(
            encoding=0,
            mime='application/octet-stream',
            desc='Serato Markers2',
            data=new_tag_data
        )

        # Limpa Markers_ legado conflitante se existir
        if 'GEOB:Serato Markers_' in audio.tags:
            del audio.tags['GEOB:Serato Markers_']

        op_id = None
        try:
            from journal import record_id3_before_change, record_operation_after
            op_id = record_id3_before_change(str(file_p), action="repair_cues")
        except Exception as e:
            return {"sucesso": False, "erro": "Journal indisponível; gravação cancelada: %s" % e}

        # Salva em ID3v2.3 (mandatório Serato)
        audio.save(v2_version=3)
        if op_id:
            try:
                record_operation_after(op_id, str(file_p))
            except Exception:
                pass

        return {
            "sucesso": True,
            "arquivo": file_p.name,
            "cues_reparados": len(existing_cues),
            "mensagem": f"{len(existing_cues)} Hot Cues reparados e ativados com sucesso para o Serato DJ Pro."
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def generate_and_save_serato_cues(filepath_str: str, overwrite_existing: bool = False):
    """
    Gera e aplica os Hot Cues na tag GEOB:Serato Markers2 do arquivo MP3.
    Por padrão protege contra sobrescrita de cues manuais pré-existentes.
    """
    if not mutagen:
        return {"sucesso": False, "erro": "Mutagen não instalado"}

    file_p = Path(filepath_str)
    if not file_p.exists():
        return {"sucesso": False, "erro": "Arquivo não encontrado"}

    try:
        audio = mutagen.File(str(file_p))
        if audio is None:
            return {"sucesso": False, "erro": "Formato de áudio não suportado"}

        # Proteção contra sobrescrita de cues existentes
        has_existing_cues = False
        if audio.tags:
            m2 = audio.tags.get('GEOB:Serato Markers2')
            if m2 and hasattr(m2, 'data'):
                cues_in_file = extract_cues_from_raw_tag(m2.data)
                if cues_in_file:
                    has_existing_cues = True
            m1 = audio.tags.get('GEOB:Serato Markers_')
            if m1 and hasattr(m1, 'data') and len(m1.data) > 0:
                has_existing_cues = True

        if has_existing_cues and not overwrite_existing:
            return {
                "sucesso": True,
                "ignorado": True,
                "arquivo": file_p.name,
                "mensagem": "Faixa já possui Hot Cues gravados. Preservada com segurança."
            }

        duration = getattr(audio.info, 'length', 0.0)
        if duration < 10:
            return {"sucesso": False, "erro": "Áudio muito curto para Hot Cues"}

        bpm_val = 0.0
        if 'TBPM' in audio:
            try:
                bpm_val = float(str(audio['TBPM']).strip().replace(',', '.'))
            except Exception:
                pass

        cue_calc = calculate_smart_cues_detailed(duration, bpm_val, filepath_str=str(file_p))
        if not cue_calc.get("sucesso") or not cue_calc.get("confiavel") or not cue_calc.get("cues"):
            return {
                "sucesso": False,
                "confiavel": bool(cue_calc.get("confiavel", False)),
                "confianca": float(cue_calc.get("confianca", 0.0)),
                "motivo": cue_calc.get("motivo", "analise_inconclusiva"),
                "arquivo": file_p.name,
                "cues": [],
                "erro": (
                    f"Análise de transientes inconclusiva ({cue_calc.get('motivo', 'baixa confiança')}, "
                    f"confiança={cue_calc.get('confianca', 0.0):.2f}). Nenhum cue foi gerado ou gravado."
                ),
            }
        cues = cue_calc["cues"]

        # Salva backup de segurança antes de alterar
        if not backup_track_cues(str(file_p), audio):
            return {"sucesso": False, "erro": "Falha na criação ou verificação obrigatória do backup de cues. Gravação abortada por segurança."}

        # Monta payload binário Serato Markers2 oficial 100% compatível
        serato_data = build_serato_markers2_tag(cues)

        # Grava tag GEOB no arquivo MP3 com ID3v2.3 (obrigatório para Serato DJ Pro)
        if hasattr(audio, 'tags'):
            if audio.tags is None:
                audio.add_tags()

            audio.tags['GEOB:Serato Markers2'] = GEOB(
                encoding=0,
                mime='application/octet-stream',
                desc='Serato Markers2',
                data=serato_data
            )
            # Registra o estado anterior no journal unificado (undo) antes de gravar
            op_id = None
            try:
                from journal import record_id3_before_change, record_operation_after
                op_id = record_id3_before_change(str(file_p), action="auto_cue")
            except Exception as e:
                return {"sucesso": False, "erro": "Journal indisponível; gravação cancelada: %s" % e}
            # CRÍTICO: Serato DJ Pro requer ID3v2.3, NÃO v2.4
            audio.save(v2_version=3)
            if op_id:
                try:
                    record_operation_after(op_id, str(file_p))
                except Exception:
                    pass

        return {
            "sucesso": True,
            "confiavel": bool(cue_calc.get("confiavel", True)),
            "confianca": float(cue_calc.get("confianca", 1.0)),
            "arquivo": file_p.name,
            "cues": cues,
            "mensagem": f"5 Hot Cues oficiais gerados e mapeados para o Serato DJ Pro."
        }
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def _is_standard_autocue_set(cue_list: list, duration_sec: float = 0.0) -> bool:
    """
    Classifica criteriosamente se um conjunto de Hot Cues corresponde exatamente
    ao padrão oficial gerado pelo Auto-Cue:
    - Exatamente 5 marcadores nos índices únicos 0..4
    - Rótulos oficiais por índice (Intro/Início, Drop 1, Break, Drop 2, Outro)
    - Cores padrão exatas por índice (#cc0000, #0066cc, #cccc00, #00cc00, #cc6600)
    - Posições válidas e estritamente crescentes ao longo da faixa
    Qualquer divergência (cores personalizadas, rótulos próprios, índices extras/duplicados,
    ordem/posições fora do padrão) identifica o conjunto como Personalizado DJ (Protegido).
    """
    if not isinstance(cue_list, list) or len(cue_list) != 5:
        return False

    standard_spec = {
        0: {"labels": {"INTRO", "INÍCIO"}, "color": "#cc0000"},
        1: {"labels": {"DROP 1"}, "color": "#0066cc"},
        2: {"labels": {"BREAK"}, "color": "#cccc00"},
        3: {"labels": {"DROP 2"}, "color": "#00cc00"},
        4: {"labels": {"OUTRO"}, "color": "#cc6600"},
    }

    by_index = {}
    for c in cue_list:
        idx = c.get("index")
        if not isinstance(idx, int) or idx not in standard_spec or idx in by_index:
            return False
        lbl = (c.get("label") or "").strip().upper()
        col = (c.get("color") or "").strip().lower()
        pos_ms = c.get("pos_ms")
        if not lbl or lbl not in standard_spec[idx]["labels"]:
            return False
        if col != standard_spec[idx]["color"]:
            return False
        if not isinstance(pos_ms, int) or pos_ms < 0:
            return False
        by_index[idx] = pos_ms

    if set(by_index.keys()) != {0, 1, 2, 3, 4}:
        return False

    positions = [by_index[i] for i in range(5)]
    for i in range(4):
        if positions[i] >= positions[i + 1]:
            return False

    if duration_sec > 0 and positions[4] > (duration_sec * 1000.0 + 500.0):
        return False

    return True


def audit_crate_cues_detailed(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True
):
    """
    Realiza uma auditoria aprofundada de todas as faixas da Crate ou Subcrate,
    detectando Hot Cues gravados, identificando se são os Auto-Cues padrão ou Hot Cues manuais de DJ
    (considerando quantidade, índices únicos, rótulos, cores e posições),
    e listando o que já está implantado vs pendente sem qualquer limite de paginação.
    Falha explicitamente quando Mutagen estiver ausente ou houver diretórios inacessíveis.
    """
    if mutagen is None:
        return {
            "sucesso": False,
            "erro": "Dependência obrigatória 'mutagen' indisponível; auditoria de cues cancelada.",
            "dependencia_ausente": "mutagen",
            "varredura_incompleta": True,
            "erros_diretorio": 0,
            "diretorios_inacessiveis": [],
            "total": 0,
            "gravadas": 0,
            "pendentes": 0,
            "personalizadas": 0,
            "padrao_autocue": 0,
            "erros_leitura": 0,
            "items": []
        }

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
            "varredura_incompleta": False,
            "erros_diretorio": 0,
            "diretorios_inacessiveis": [],
            "total": 0,
            "gravadas": 0,
            "pendentes": 0,
            "personalizadas": 0,
            "padrao_autocue": 0,
            "erros_leitura": 0,
            "items": []
        }

    total_tracks = 0
    total_with_cues = 0
    total_custom = 0
    total_padrao = 0
    total_erros = 0
    items = []
    dir_errors = []

    def _on_walk_error(os_err):
        dir_errors.append(str(os_err))

    for root, dirs, files in os.walk(str(target_dir), onerror=_on_walk_error):
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
            if ext in ('.mp3', '.m4a', '.flac', '.wav', '.aiff'):
                total_tracks += 1
                full_p = Path(root) / f
                has_cues = False
                cue_list = []
                dur = 0.0
                bpm = 0.0
                tipo_cue = "Sem Cues"
                erro_msg = None

                try:
                    audio = mutagen.File(str(full_p))
                    if audio is not None:
                        dur = getattr(audio.info, 'length', 0.0)
                        if 'TBPM' in audio:
                            try:
                                bpm = float(str(audio['TBPM']).strip().replace(',', '.'))
                            except Exception:
                                pass
                        if 'GEOB:Serato Markers2' in audio:
                            raw_m2 = audio['GEOB:Serato Markers2'].data
                            cues_in = extract_cues_from_raw_tag(raw_m2)
                            if cues_in:
                                has_cues = True
                                cue_list = cues_in
                        elif 'GEOB:Serato Markers_' in audio:
                            has_cues = True
                    else:
                        erro_msg = "Formato de arquivo incompatível ou corrompido"
                except Exception as e:
                    erro_msg = str(e)

                if erro_msg:
                    total_erros += 1
                    status_item = "Erro de Leitura"
                    tipo_cue = f"Falha na Análise: {erro_msg}"
                elif has_cues:
                    total_with_cues += 1
                    status_item = "Gravado"

                    is_custom = not _is_standard_autocue_set(cue_list, duration_sec=dur)
                    if is_custom:
                        total_custom += 1
                        tipo_cue = "Personalizado DJ (Protegido)"
                    else:
                        total_padrao += 1
                        tipo_cue = "Auto-Cue Padrão"
                else:
                    status_item = "Pendente"

                crate_parts = [p for p in rel_folder.replace('\\', '/').split('/') if p]
                c_raiz = crate_parts[0] if crate_parts else "Raiz"

                cue_labels_summary = [f"#{c.get('index', i+1)} {c.get('label', '')}".strip() for i, c in enumerate(cue_list)]

                items.append({
                    "id": f"audit-cue-{total_tracks}",
                    "caminho": str(full_p),
                    "arquivo": f,
                    "pasta": rel_folder,
                    "crate": c_raiz,
                    "duracao_seg": round(dur, 1),
                    "bpm": round(bpm),
                    "tem_cues": has_cues,
                    "tipo_cue": tipo_cue,
                    "total_cues": len(cue_list),
                    "cue_labels": cue_labels_summary,
                    "status": status_item,
                    "erro": erro_msg
                })

    pendentes_reais = total_tracks - total_with_cues - total_erros
    varredura_incompleta = len(dir_errors) > 0
    result = {
        "sucesso": not varredura_incompleta,
        "varredura_incompleta": varredura_incompleta,
        "erros_diretorio": len(dir_errors),
        "diretorios_inacessiveis": dir_errors[:20],
        "total": total_tracks,
        "gravadas": total_with_cues,
        "pendentes": max(0, pendentes_reais),
        "personalizadas": total_custom,
        "padrao_autocue": total_padrao,
        "erros_leitura": total_erros,
        "items": items
    }
    if varredura_incompleta:
        result["erro"] = (
            f"Varredura incompleta: {len(dir_errors)} diretório(s) inacessível(is) "
            "durante a auditoria de cues."
        )
    return result


def scan_crate_cues(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True,
    limit: int = 150,
    offset: int = 0
):
    """Varre faixas da Crate ou Subcrate verificando existência de Hot Cues gravados."""
    if mutagen is None:
        return {
            "sucesso": False,
            "erro": "Dependência obrigatória 'mutagen' indisponível; varredura de cues cancelada.",
            "dependencia_ausente": "mutagen",
            "varredura_incompleta": True,
            "erros_diretorio": 0,
            "diretorios_inacessiveis": [],
            "total": 0,
            "gravadas": 0,
            "pendentes": 0,
            "items": []
        }

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
            "varredura_incompleta": False,
            "erros_diretorio": 0,
            "diretorios_inacessiveis": [],
            "total": 0,
            "gravadas": 0,
            "pendentes": 0,
            "items": []
        }

    total_tracks = 0
    total_with_cues = 0
    items = []
    dir_errors = []

    def _on_walk_error(os_err):
        dir_errors.append(str(os_err))

    for root, dirs, files in os.walk(str(target_dir), onerror=_on_walk_error):
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
            if ext in ('.mp3', '.m4a', '.flac', '.wav', '.aiff'):
                total_tracks += 1
                full_p = Path(root) / f
                has_cues = False
                dur = 0.0
                bpm = 0.0

                try:
                    audio = mutagen.File(str(full_p))
                    if audio is not None:
                        dur = getattr(audio.info, 'length', 0.0)
                        if 'TBPM' in audio:
                            try: bpm = float(str(audio['TBPM']).strip().replace(',', '.'))
                            except Exception: pass
                        if 'GEOB:Serato Markers2' in audio:
                            raw_m2 = audio['GEOB:Serato Markers2'].data
                            cues_in = extract_cues_from_raw_tag(raw_m2)
                            if cues_in:
                                has_cues = True
                except Exception:
                    pass

                if has_cues:
                    total_with_cues += 1

                if total_tracks > offset and (not limit or limit <= 0 or len(items) < limit):
                    crate_parts = [p for p in rel_folder.replace('\\', '/').split('/') if p]
                    c_raiz = crate_parts[0] if crate_parts else ""
                    items.append({
                        "id": f"cue-{total_tracks}",
                        "caminho": str(full_p),
                        "arquivo": f,
                        "pasta": rel_folder,
                        "crate": c_raiz,
                        "duracao_seg": round(dur, 1),
                        "bpm": round(bpm),
                        "tem_cues": has_cues,
                        "status": "Gravado" if has_cues else "Pendente"
                    })

    varredura_incompleta = len(dir_errors) > 0
    result = {
        "sucesso": not varredura_incompleta,
        "varredura_incompleta": varredura_incompleta,
        "erros_diretorio": len(dir_errors),
        "diretorios_inacessiveis": dir_errors[:20],
        "total": total_tracks,
        "gravadas": total_with_cues,
        "pendentes": total_tracks - total_with_cues,
        "items": items
    }
    if varredura_incompleta:
        result["erro"] = (
            f"Varredura incompleta: {len(dir_errors)} diretório(s) inacessível(is) "
            "durante o escaneamento."
        )
    return result


def batch_repair_crate_cues(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True
):
    """Varre e repara o layout binário Serato Markers2 de todas as faixas que possuem cues."""
    if mutagen is None:
        print(json.dumps({
            "tipo": "fim",
            "sucesso": False,
            "erro": "Dependência obrigatória 'mutagen' indisponível.",
            "dependencia_ausente": "mutagen",
            "total": 0,
            "atualizados": 0,
            "erros": ["Mutagen não instalado"]
        }, ensure_ascii=False), flush=True)
        return

    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    files_to_process = []
    dir_errors = []

    def _on_walk_error(os_err):
        dir_errors.append(f"Diretório inacessível: {os_err}")

    for root, dirs, files in os.walk(str(target_dir), onerror=_on_walk_error):
        if '/.' in root or '\\.' in root:
            continue
        if crate_raiz and not include_subcrates and not subcrate:
            if root != str(target_dir):
                dirs.clear()
                continue
            dirs.clear()

        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            ext = Path(f).suffix.lower()
            if ext in ('.mp3', '.m4a', '.flac', '.wav', '.aiff'):
                files_to_process.append(Path(root) / f)

    total = len(files_to_process)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    repaired_count = 0
    errors = list(dir_errors)

    for idx, full_p in enumerate(files_to_process, 1):
        try:
            audio = mutagen.File(str(full_p))
            if audio and 'GEOB:Serato Markers2' in audio:
                res = repair_track_cues(str(full_p))
                if res.get("sucesso"):
                    repaired_count += 1
                else:
                    errors.append(f"{full_p.name}: {res.get('erro')}")
        except Exception as e:
            errors.append(f"{full_p.name}: {str(e)}")

        if idx % 25 == 0 or idx == total:
            pct = round((idx / total) * 100, 1)
            print(json.dumps({
                "tipo": "progresso",
                "processados": idx,
                "total": total,
                "percentual": pct,
                "atualizados": repaired_count,
                "faixa_atual": full_p.name
            }, ensure_ascii=False), flush=True)

    has_errors = len(errors) > 0
    print(json.dumps({
        "tipo": "fim",
        "sucesso": not has_errors,
        "sucesso_parcial": (has_errors and repaired_count > 0),
        "varredura_incompleta": len(dir_errors) > 0,
        "erros_diretorio": len(dir_errors),
        "total": total,
        "atualizados": repaired_count,
        "erros": errors[:10]
    }, ensure_ascii=False), flush=True)


def batch_apply_crate_cues(
    mp3_base_dir: str,
    crate_raiz: str = "",
    subcrate: str = "",
    include_subcrates: bool = True,
    only_pending: bool = False,
    overwrite_existing: bool = False
):
    """Gera e aplica Hot Cues para todas as faixas da Crate com streaming de progresso."""
    if mutagen is None:
        print(json.dumps({
            "tipo": "fim",
            "sucesso": False,
            "erro": "Dependência obrigatória 'mutagen' indisponível.",
            "dependencia_ausente": "mutagen",
            "total": 0,
            "atualizados": 0,
            "erros": ["Mutagen não instalado"]
        }, ensure_ascii=False), flush=True)
        return

    base_path = Path(os.path.expanduser(mp3_base_dir)).resolve()
    target_dir = base_path
    if crate_raiz:
        target_dir = base_path / crate_raiz
        if subcrate:
            target_dir = target_dir / subcrate

    files_to_process = []
    dir_errors = []

    def _on_walk_error(os_err):
        dir_errors.append(f"Diretório inacessível: {os_err}")

    for root, dirs, files in os.walk(str(target_dir), onerror=_on_walk_error):
        if '/.' in root or '\\.' in root:
            continue
        if crate_raiz and not include_subcrates and not subcrate:
            if root != str(target_dir):
                dirs.clear()
                continue
            dirs.clear()

        for f in files:
            if f.startswith('._') or f.startswith('.'):
                continue
            ext = Path(f).suffix.lower()
            if ext in ('.mp3', '.m4a', '.flac', '.wav', '.aiff'):
                files_to_process.append(Path(root) / f)

    total = len(files_to_process)
    print(json.dumps({"tipo": "inicio", "total": total}, ensure_ascii=False), flush=True)

    applied_count = 0
    errors = list(dir_errors)

    for idx, full_p in enumerate(files_to_process, 1):
        skipped = False
        if (only_pending or not overwrite_existing) and mutagen:
            try:
                audio = mutagen.File(str(full_p))
                if audio and 'GEOB:Serato Markers2' in audio:
                    cues_in = extract_cues_from_raw_tag(audio['GEOB:Serato Markers2'].data)
                    if cues_in:
                        skipped = True
            except Exception:
                pass

        if not skipped:
            res = generate_and_save_serato_cues(str(full_p), overwrite_existing=overwrite_existing)
            if res.get("sucesso") and not res.get("ignorado"):
                applied_count += 1
            elif res.get("erro"):
                errors.append(f"{full_p.name}: {res.get('erro')}")

        if idx % 15 == 0 or idx == total:
            pct = round((idx / total) * 100, 1)
            print(json.dumps({
                "tipo": "progresso",
                "processados": idx,
                "total": total,
                "percentual": pct,
                "atualizados": applied_count,
                "faixa_atual": full_p.name
            }, ensure_ascii=False), flush=True)

    has_errors = len(errors) > 0
    print(json.dumps({
        "tipo": "fim",
        "sucesso": not has_errors,
        "sucesso_parcial": (has_errors and applied_count > 0),
        "varredura_incompleta": len(dir_errors) > 0,
        "erros_diretorio": len(dir_errors),
        "total": total,
        "atualizados": applied_count,
        "erros": errors[:10]
    }, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Serato 5 Sync Manager Pro - Auto-Cue Generator & Repair")
    parser.add_argument("--preview", type=str, default="", help="Calcula prévia dos cues de uma música")
    parser.add_argument("--apply", type=str, default="", help="Grava Hot Cues no arquivo")
    parser.add_argument("--repair-file", type=str, default="", help="Repara tags de Serato Markers2 em um arquivo")
    parser.add_argument("--repair-batch", action="store_true", help="Repara marcadores de toda a biblioteca/crate")
    parser.add_argument("--apply-batch", type=str, default="", help="JSON de lista de arquivos para aplicar em lote")
    parser.add_argument("--scan-crate", action="store_true", help="Varre Crate/Subcrate para listar faixas e cues")
    parser.add_argument("--audit-crate", action="store_true", help="Audita detalhadamente todas as faixas da Crate para identificar cues existentes vs pendentes")
    parser.add_argument("--batch-crate", action="store_true", help="Gera Hot Cues para toda a Crate")
    parser.add_argument("--list-backups", action="store_true", help="Lista os backups de cues disponíveis para restauração")
    parser.add_argument("--list-backups-search", type=str, default="", help="Filtra a lista de backups por nome ou caminho")
    parser.add_argument("--restore", type=str, default="", help="Restaura os cues de um arquivo a partir do backup")
    parser.add_argument("--mp3", type=str, default="", help="Pasta MP3 base")
    parser.add_argument("--crate-raiz", type=str, default="", help="Crate raiz")
    parser.add_argument("--subcrate", type=str, default="", help="Subcrate")
    parser.add_argument("--no-subcrates", action="store_true", help="Não incluir subcrates")
    parser.add_argument("--only-pending", action="store_true", help="Apenas faixas que ainda não possuem Hot Cues")
    parser.add_argument("--overwrite-existing", action="store_true", help="Sobrescrever cues pré-existentes")
    parser.add_argument("--limit", type=int, default=150, help="Limite de faixas na listagem")
    parser.add_argument("--offset", type=int, default=0, help="Offset de paginação")

    args = parser.parse_args()
    mp3_dir = args.mp3 or str(Path.home() / "Music" / "MP3")

    if args.preview:
        if mutagen is None:
            print(json.dumps({"sucesso": False, "confiavel": False, "confianca": 0.0, "erro": "Mutagen não instalado"}, ensure_ascii=False), flush=True)
            sys.exit(1)
        file_p = Path(args.preview)
        if not file_p.exists():
            print(json.dumps({"sucesso": False, "confiavel": False, "confianca": 0.0, "erro": "Arquivo não encontrado"}, ensure_ascii=False), flush=True)
            sys.exit(1)
        try:
            audio = mutagen.File(str(file_p))
            dur = getattr(audio.info, 'length', 0.0) if audio else 0.0
            bpm = 0.0
            if audio and 'TBPM' in audio:
                bpm = float(str(audio['TBPM']).strip().replace(',', '.'))
            cue_calc = calculate_smart_cues_detailed(dur, bpm, filepath_str=str(file_p))
            payload = {
                "sucesso": bool(cue_calc.get("sucesso")),
                "duracao": dur,
                "bpm": bpm,
                "confiavel": bool(cue_calc.get("confiavel")),
                "confianca": float(cue_calc.get("confianca", 0.0)),
                "motivo": cue_calc.get("motivo", ""),
                "transiente": cue_calc.get("transiente"),
                "cues": cue_calc.get("cues", []),
            }
            if not payload["sucesso"]:
                payload["erro"] = (
                    f"Análise de transientes inconclusiva ({payload['motivo']}, "
                    f"confiança={payload['confianca']:.2f})."
                )
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            sys.exit(0 if payload["sucesso"] else 1)
        except Exception as e:
            print(json.dumps({"sucesso": False, "confiavel": False, "confianca": 0.0, "erro": str(e)}, ensure_ascii=False), flush=True)
            sys.exit(1)

    if args.repair_file:
        res = repair_track_cues(args.repair_file)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    if args.repair_batch:
        batch_repair_crate_cues(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates
        )
        sys.exit(0)

    if args.apply:
        res = generate_and_save_serato_cues(args.apply, overwrite_existing=args.overwrite_existing)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    if args.apply_batch:
        try:
            files = json.loads(args.apply_batch)
            updated = 0
            errors = []

            def process_file(file_path):
                return generate_and_save_serato_cues(file_path, overwrite_existing=args.overwrite_existing)

            # Execução paralela aproveitando múltiplos núcleos do Apple Silicon (4 a 8 threads)
            max_workers = min(8, max(2, (os.cpu_count() or 4)))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {executor.submit(process_file, f): f for f in files}
                for future in as_completed(future_map):
                    fpath = future_map[future]
                    try:
                        r = future.result()
                        if r.get("sucesso") and not r.get("ignorado"):
                            updated += 1
                        elif not r.get("sucesso"):
                            errors.append(f"{Path(str(fpath)).name}: {r.get('erro', 'erro desconhecido')}")
                    except Exception as exc:
                        errors.append(f"{Path(str(fpath)).name}: {exc}")

            has_errors = len(errors) > 0
            print(json.dumps({
                "sucesso": not has_errors,
                "sucesso_parcial": (has_errors and updated > 0),
                "total": len(files),
                "atualizados": updated,
                "erros": errors[:10]
            }, ensure_ascii=False), flush=True)
            sys.exit(0 if not has_errors else 1)
        except Exception as e:
            print(json.dumps({"sucesso": False, "erro": str(e)}, ensure_ascii=False), flush=True)
            sys.exit(1)

    if args.audit_crate:
        res = audit_crate_cues_detailed(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates
        )
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    if args.scan_crate:
        res = scan_crate_cues(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates,
            limit=args.limit,
            offset=args.offset
        )
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    if args.batch_crate:
        batch_apply_crate_cues(
            mp3_dir,
            crate_raiz=args.crate_raiz,
            subcrate=args.subcrate,
            include_subcrates=not args.no_subcrates,
            only_pending=args.only_pending,
            overwrite_existing=args.overwrite_existing
        )
        sys.exit(0)

    if args.list_backups:
        res = list_cue_backups(search=args.list_backups_search)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    if args.restore:
        res = restore_track_cues(args.restore)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        sys.exit(0 if res.get("sucesso") else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
