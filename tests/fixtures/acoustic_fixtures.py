#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/fixtures/acoustic_fixtures.py
FFmpeg Acoustic Signal & Edge-Case Fixture Generator for Serato 4 Sync Pro.

Provides:
1. AcousticFixtureGenerator:
   - Isochronous click tracks (120, 126, 130 BPM) for music_analysis BPM detection.
   - Camelot harmonic chord audio (C Major -> 8B, A Minor -> 8A) for key detection.
   - Silence + transient phase alignment audio for auto_cue silencedetect.
   - Spectral brickwall cutoff audio (True 320k vs Fake 320k) for audio_health audit.
2. EdgeCaseFixtureGenerator:
   - 0-byte corrupt files.
   - Truncated audio (< 10s).
   - Malformed/non-synchsafe ID3v2 headers.
   - Corrupted non-vrsn .crate files.
   - Extreme BPM tracks (40 BPM, 240 BPM).
   - Path traversal and illegal character fixtures.
"""

import os
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Optional, Union

from tests.fixtures.synthetic_library import (
    MPEG1_L3_128K_44K_HEADER,
    MPEG_PAYLOAD_SIZE,
    FRAME_DURATION_SEC,
    create_crate_binary,
)


class AcousticFixtureGenerator:
    """
    Synthesizes authentic acoustic audio signals via FFmpeg lavfi filters.
    All outputs are generated strictly within sandboxed temporary paths.
    """

    @staticmethod
    def get_ffmpeg() -> str:
        """
        Resolves system FFmpeg binary path or raises unittest.SkipTest.
        """
        candidates = [
            "/opt/homebrew/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            shutil.which("ffmpeg") or "",
        ]
        for p in candidates:
            if p and os.path.exists(p) and os.access(p, os.X_OK):
                return p
        raise unittest.SkipTest("FFmpeg não disponível no ambiente para geração de fixtures acústicas.")

    @classmethod
    def generate_click_track(
        cls,
        out_path: Union[str, Path],
        bpm: float = 120.0,
        duration_sec: float = 15.0
    ) -> Path:
        """
        Synthesizes an isochronous click track at precise BPM (e.g. 120.0, 126.0, 130.0).
        Uses a 1000 Hz sine burst of 35 ms every (60.0 / bpm) seconds.
        """
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = cls.get_ffmpeg()
        interval = 60.0 / float(bpm)
        expr = f"sin(2*PI*1000*t)*gt(mod(t\\,{interval:.6f})\\,0)*lt(mod(t\\,{interval:.6f})\\,0.035)"
        cmd = [
            ffmpeg, "-y", "-f", "lavfi",
            "-i", f"aevalsrc=exprs={expr}:s=44100:d={duration_sec}",
            "-c:a", "libmp3lame", "-b:a", "128k", str(target)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return target

    @classmethod
    def generate_chord_audio(
        cls,
        out_path: Union[str, Path],
        chord: str = "C_major",
        duration_sec: float = 10.0
    ) -> Path:
        """
        Synthesizes harmonic chord audio for Camelot key testing:
        - 'C_major' / '8B': 261.63 Hz (C4) + 329.63 Hz (E4) + 392.00 Hz (G4) -> Camelot '8B'
        - 'A_minor' / '8A': 220.00 Hz (A3) + 261.63 Hz (C4) + 329.63 Hz (E4) -> Camelot '8A'
        """
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = cls.get_ffmpeg()

        c_upper = chord.upper()
        if c_upper in ("C_MAJOR", "8B", "C"):
            expr = "0.3*(sin(2*PI*261.63*t)+sin(2*PI*329.63*t)+sin(2*PI*392.00*t))"
        elif c_upper in ("A_MINOR", "8A", "AM"):
            expr = "0.3*(sin(2*PI*220.00*t)+sin(2*PI*261.63*t)+sin(2*PI*329.63*t))"
        else:
            raise ValueError(f"Acorde não suportado: {chord} (suportados: C_major, A_minor)")

        cmd = [
            ffmpeg, "-y", "-f", "lavfi",
            "-i", f"aevalsrc=exprs={expr}:s=44100:d={duration_sec}",
            "-c:a", "libmp3lame", "-b:a", "128k", str(target)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return target

    @classmethod
    def generate_transient_audio(
        cls,
        out_path: Union[str, Path],
        silence_sec: float = 2.0,
        audio_sec: float = 8.0
    ) -> Path:
        """
        Synthesizes an audio track with initial silence followed by a sharp audio tone.
        Tests auto_cue.py silencedetect phase alignment and beatgrid positioning.
        """
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = cls.get_ffmpeg()
        filter_str = (
            f"anullsrc=r=44100:cl=mono:d={silence_sec}[s1];"
            f"sine=f=1000:d={audio_sec}[s2];"
            f"[s1][s2]concat=n=2:v=0:a=1[out]"
        )
        cmd = [
            ffmpeg, "-y", "-filter_complex", filter_str,
            "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "128k", str(target)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return target

    @classmethod
    def generate_spectral_cutoff_audio(
        cls,
        out_path: Union[str, Path],
        is_fake: bool = True,
        duration_sec: float = 20.0
    ) -> Path:
        """
        Synthesizes 320 kbps MP3 files with or without high-frequency spectral brickwall cutoff.
        - is_fake=False: Full-spectrum broadband noise up to 20 kHz encoded at 320 kbps.
        - is_fake=True: Cascaded 4-stage 12 kHz lowpass filtered noise encoded at 320 kbps.
        """
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = cls.get_ffmpeg()

        if is_fake:
            filter_str = (
                f"anoisesrc=d={duration_sec}:c=white:r=44100:a=0.1,"
                f"lowpass=f=12000,lowpass=f=12000,lowpass=f=12000,lowpass=f=12000[out]"
            )
            cmd = [
                ffmpeg, "-y", "-filter_complex", filter_str,
                "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "320k", str(target)
            ]
        else:
            cmd = [
                ffmpeg, "-y", "-f", "lavfi",
                "-i", f"anoisesrc=d={duration_sec}:c=white:r=44100:a=0.5",
                "-c:a", "libmp3lame", "-b:a", "320k", str(target)
            ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return target


class EdgeCaseFixtureGenerator:
    """
    Constructs edge-case corruptions, extreme values, and adversarial path fixtures.
    """

    @staticmethod
    def create_zero_byte_file(filepath: Union[str, Path]) -> Path:
        """Creates an empty 0-byte file."""
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")
        return target

    @staticmethod
    def create_truncated_audio(filepath: Union[str, Path], duration_sec: float = 3.0) -> Path:
        """
        Creates truncated audio (<10s) with valid MPEG frames but short duration.
        """
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        frame = MPEG1_L3_128K_44K_HEADER + b"\x00" * MPEG_PAYLOAD_SIZE
        total_frames = max(1, int(duration_sec / FRAME_DURATION_SEC))
        with open(target, "wb") as f:
            for _ in range(total_frames):
                f.write(frame)
        return target

    @staticmethod
    def create_bad_synchsafe_id3(filepath: Union[str, Path]) -> Path:
        """
        Creates an MP3 file with invalid synchsafe integer in ID3 header
        (Byte 6 has bit 7 set: 0x80), followed by valid MPEG frames.
        """
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        bad_header = b"ID3\x03\x00\x00\x80\x00\x00\x01\x00\x00"
        audio_frame = MPEG1_L3_128K_44K_HEADER + b"\x00" * MPEG_PAYLOAD_SIZE
        target.write_bytes(bad_header + audio_frame * 50)
        return target

    @staticmethod
    def create_corrupted_crate(filepath: Union[str, Path]) -> Path:
        """
        Creates a corrupted Serato .crate file starting with 'CORR' instead of 'vrsn'.
        """
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        corrupt_payload = b"CORR\x00\x00\x00\x08InvalidCrateHeaderPayloadData"
        target.write_bytes(corrupt_payload)
        return target

    @staticmethod
    def create_extreme_bpm_track(
        filepath: Union[str, Path],
        bpm: float = 40.0,
        duration_sec: float = 15.0
    ) -> Path:
        """
        Generates extreme BPM click tracks (e.g. 40 BPM or 240 BPM).
        """
        return AcousticFixtureGenerator.generate_click_track(filepath, bpm=bpm, duration_sec=duration_sec)

    @staticmethod
    def create_traversal_path_crate(
        filepath: Union[str, Path],
        traversal_path: str = "../../outside_root.mp3"
    ) -> Path:
        """
        Creates a Serato .crate file containing path traversal or illegal path tokens.
        """
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = create_crate_binary([traversal_path])
        target.write_bytes(data)
        return target
