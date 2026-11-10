#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E2E Test Harness & Fixtures for SeratoLib.
Ensures 100% isolated sandbox execution (Requirement R2) with zero modifications
to real user files or production code.

Provides backward-compatible E2ESandboxTestCase powered by SeratoSandbox,
and re-exports all synthetic, acoustic, and isolation fixtures.
"""

import os
import sys
import math
import struct
import unittest
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Add project root and vendor
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
VENDOR_DIR = PROJECT_ROOT / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))
bad_mutagen_dir = str(PROJECT_ROOT / "vendor" / "mutagen")
if bad_mutagen_dir in sys.path:
    sys.path.remove(bad_mutagen_dir)

# Re-export all fixtures from tests.fixtures
from tests.fixtures.synthetic_library import (
    MPEG1_L3_128K_44K_HEADER,
    MPEG_FRAME_SIZE,
    MPEG_PAYLOAD_SIZE,
    SAMPLES_PER_FRAME,
    SAMPLE_RATE,
    FRAME_DURATION_SEC,
    CANONICAL_VRSN_HEADER,
    LEGACY_ASCII_VRSN_HEADER,
    SyntheticTrack,
    to_synchsafe,
    from_synchsafe,
    make_id3_frame,
    build_id3v23_tag,
    build_mpeg_frames,
    create_synthetic_mp3 as lib_create_synthetic_mp3,
    criar_tag_tlv,
    make_otrk_chunk,
    create_crate_binary,
    write_crate_file,
    build_neworder_pref,
    write_neworder_pref,
    read_crate_paths as lib_read_crate_paths,
    generate_standard_dj_library,
)

from tests.fixtures.acoustic_fixtures import (
    AcousticFixtureGenerator,
    EdgeCaseFixtureGenerator,
)

from tests.fixtures.sandbox_runner import (
    SeratoSandbox,
    SandboxResult,
    parse_sandbox_output,
    HOST_HOME,
)


class E2ESandboxTestCase(unittest.TestCase):
    """
    Base test case providing isolated sandbox environment, environment patching,
    and synthetic audio/crate generators with zero-leak verification.
    """

    def setUp(self):
        # 1. Initialize hermetic sandbox
        self.sandbox = SeratoSandbox(clean_on_exit=True)
        self.sandbox.start()

        # 2. Expose directory references for test convenience
        self.sandbox_path = self.sandbox.sandbox_root
        self.sandbox_dir = str(self.sandbox_path)
        self.fake_home = self.sandbox.fake_home
        self.tmp_dir = self.sandbox.tmp_dir
        self.mp3_dir = self.sandbox.mp3_dir
        self.serato_dir = self.sandbox.serato_dir
        self.subcrates_dir = self.sandbox.subcrates_dir
        self.logs_dir = self.sandbox.logs_dir
        self.exports_dir = self.sandbox.exports_dir
        self.quarantine_dir = self.sandbox.quarantine_dir
        self.backups_dir = self.sandbox.backups_dir
        self.serato_app_support = self.sandbox.serato_app_support
        self.desktop_dir = self.sandbox.desktop_dir
        self.trash_dir = self.sandbox.trash_dir

        # 3. Explicitly verify/set journal and auto_cue paths to sandbox
        try:
            import journal
            journal.JOURNAL_PATH = self.fake_home / ".serato_sync_journal.sqlite"
        except Exception:
            pass
        try:
            import auto_cue
            auto_cue.BACKUP_DB_PATH = self.fake_home / ".serato_sync_cues_backup.sqlite"
        except Exception:
            pass

    def tearDown(self):
        # Close sandbox, restore all patched constants, and assert zero leaks
        if hasattr(self, "sandbox") and self.sandbox:
            self.sandbox.close()

    def create_synthetic_mp3(
        self,
        filepath: Union[str, Path],
        title: str = "Test Title",
        artist: str = "Test Artist",
        album: str = "Test Album",
        bpm: str = "124.0",
        key: str = "8A",
        duration_frames: int = 500,
        audio_content: bytes = b"",
        extra_tags: Optional[Dict[str, str]] = None,
        tag_version: int = 3,
        **kwargs
    ) -> Path:
        """
        Creates an MPEG 1 Layer 3 MP3 file with valid ID3v2.3 tags and valid MPEG frames.
        """
        duration_sec = kwargs.get("duration_sec")
        if duration_sec is None:
            duration_sec = duration_frames * FRAME_DURATION_SEC

        track = SyntheticTrack(
            title=title,
            artist=artist,
            album=album,
            bpm=str(bpm) if bpm is not None else "",
            key=str(key) if key is not None else "",
            genre=kwargs.get("genre", "House"),
            year=str(kwargs.get("year", "2024")),
            comment=kwargs.get("comment", ""),
            duration_sec=float(duration_sec),
            track_id=int(kwargs.get("track_id", 1)),
            custom_tags=extra_tags or kwargs.get("custom_tags") or {},
        )
        return lib_create_synthetic_mp3(filepath, track=track)

    def create_corrupt_mp3(
        self,
        filepath: Union[str, Path],
        corrupt_type: str = "truncated"
    ) -> Path:
        """Creates various corrupted audio files for boundary & negative testing."""
        if corrupt_type == "empty":
            return EdgeCaseFixtureGenerator.create_zero_byte_file(filepath)
        elif corrupt_type == "truncated":
            target = Path(filepath)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x0a\xff\xfb")
            return target
        elif corrupt_type == "bad_synchsafe":
            return EdgeCaseFixtureGenerator.create_bad_synchsafe_id3(filepath)
        elif corrupt_type == "garbage":
            target = Path(filepath)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"NOT_AN_MP3_AT_ALL_JUST_RANDOM_TEXT_DATA_FOR_TESTING")
            return target
        else:
            return EdgeCaseFixtureGenerator.create_zero_byte_file(filepath)

    def create_synthetic_crate(
        self,
        crate_path: Union[str, Path],
        track_paths: List[Union[str, Path]],
        custom_chunks: Optional[List[Any]] = None
    ) -> Path:
        """
        Creates a binary Serato .crate file matching Serato ScratchLive Crate specifications.
        """
        rel_paths = [str(tp) for tp in track_paths]
        return write_crate_file(crate_path, rel_paths, custom_blocks=custom_chunks)

    def read_crate_paths(self, crate_path: Union[str, Path]) -> List[str]:
        """Parses all 'ptrk' track paths from a Serato .crate file."""
        return lib_read_crate_paths(crate_path)

    def write_wav(
        self,
        filepath: Union[str, Path],
        seconds: float = 2.0,
        sr: int = 44100,
        freq: float = 440.0
    ) -> Path:
        """Writes a standard 16-bit PCM mono WAV file with a pure sine wave."""
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        num_samples = int(sr * seconds)
        samples = [int(math.sin(2 * math.pi * freq * i / sr) * 16000) for i in range(num_samples)]
        with wave.open(str(target), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        return target

    # FFmpeg Acoustic Signal Helpers
    def create_click_track(
        self,
        filepath: Union[str, Path],
        bpm: float = 120.0,
        duration_sec: float = 15.0
    ) -> Path:
        return AcousticFixtureGenerator.generate_click_track(filepath, bpm=bpm, duration_sec=duration_sec)

    def create_chord_track(
        self,
        filepath: Union[str, Path],
        chord: str = "C_major",
        duration_sec: float = 10.0
    ) -> Path:
        return AcousticFixtureGenerator.generate_chord_audio(filepath, chord=chord, duration_sec=duration_sec)

    def create_transient_track(
        self,
        filepath: Union[str, Path],
        silence_sec: float = 2.0,
        audio_sec: float = 8.0
    ) -> Path:
        return AcousticFixtureGenerator.generate_transient_audio(filepath, silence_sec=silence_sec, audio_sec=audio_sec)

    def create_spectral_cutoff_track(
        self,
        filepath: Union[str, Path],
        is_fake: bool = True,
        duration_sec: float = 20.0
    ) -> Path:
        return AcousticFixtureGenerator.generate_spectral_cutoff_audio(filepath, is_fake=is_fake, duration_sec=duration_sec)
