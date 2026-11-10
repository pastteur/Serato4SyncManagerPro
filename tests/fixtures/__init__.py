#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/fixtures package for SeratoLib.
Hermetic Sandbox Environment & Test Fixture Generators.
"""

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
    create_synthetic_mp3,
    criar_tag_tlv,
    make_otrk_chunk,
    create_crate_binary,
    write_crate_file,
    build_neworder_pref,
    write_neworder_pref,
    read_crate_paths,
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

__all__ = [
    # Synthetic Library
    "MPEG1_L3_128K_44K_HEADER",
    "MPEG_FRAME_SIZE",
    "MPEG_PAYLOAD_SIZE",
    "SAMPLES_PER_FRAME",
    "SAMPLE_RATE",
    "FRAME_DURATION_SEC",
    "CANONICAL_VRSN_HEADER",
    "LEGACY_ASCII_VRSN_HEADER",
    "SyntheticTrack",
    "to_synchsafe",
    "from_synchsafe",
    "make_id3_frame",
    "build_id3v23_tag",
    "build_mpeg_frames",
    "create_synthetic_mp3",
    "criar_tag_tlv",
    "make_otrk_chunk",
    "create_crate_binary",
    "write_crate_file",
    "build_neworder_pref",
    "write_neworder_pref",
    "read_crate_paths",
    "generate_standard_dj_library",
    # Acoustic & Edge-Case Fixtures
    "AcousticFixtureGenerator",
    "EdgeCaseFixtureGenerator",
    # Sandbox Runner
    "SeratoSandbox",
    "SandboxResult",
    "parse_sandbox_output",
    "HOST_HOME",
]
