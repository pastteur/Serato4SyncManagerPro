#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/fixtures/synthetic_library.py
Pure Python High-Speed Synthetic MP3 & Serato .crate Generator for Serato 4 Sync Pro.

Generates:
1. Valid MPEG-1 Layer 3 audio frames (417 bytes/frame, 128kbps, 44.1kHz, ~26.12ms).
2. Dynamic ID3v2.3 headers with synchsafe integer sizing and UTF-8 frames.
3. Binary Serato .crate files and neworder.pref with Big-Endian TLV chunks.
4. Multi-level realistic DJ library folder hierarchies with accented UTF-8 metadata.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import struct
import unicodedata

# -----------------------------------------------------------------------------
# MPEG-1 Layer 3 & Serato Crate Constants
# -----------------------------------------------------------------------------
# MPEG-1 Layer 3, 128 kbps, 44.1 kHz, Stereo, No Padding, No CRC
MPEG1_L3_128K_44K_HEADER = b"\xff\xfb\x90\x00"
MPEG_FRAME_SIZE = 417
MPEG_PAYLOAD_SIZE = 413
SAMPLES_PER_FRAME = 1152
SAMPLE_RATE = 44100
FRAME_DURATION_SEC = SAMPLES_PER_FRAME / SAMPLE_RATE  # ~0.02612245s

# Serato Binary Constants
CANONICAL_VRSN_HEADER = b"vrsn\x00\x00\x00\x08\x001\x00.\x000\x000"
LEGACY_ASCII_VRSN_HEADER = b"vrsn\x00\x00\x00\x1c1.0/Serato ScratchLive Crate"


@dataclass
class SyntheticTrack:
    """Specification of an audio track to generate."""
    title: str = "Synthetic Track"
    artist: str = "Serato Artist"
    album: str = "Synthetic Library"
    bpm: str = "124.0"
    key: str = "8A"
    genre: str = "House"
    year: str = "2024"
    comment: str = ""
    duration_sec: float = 2.0
    track_id: int = 1
    custom_tags: Dict[str, str] = field(default_factory=dict)


# -----------------------------------------------------------------------------
# 1. ID3v2.3 Binary Builders
# -----------------------------------------------------------------------------

def to_synchsafe(size: int) -> bytes:
    """Encodes an integer into a 4-byte ID3v2 synchsafe integer (7 bits per byte)."""
    return bytes([
        (size >> 21) & 0x7F,
        (size >> 14) & 0x7F,
        (size >> 7) & 0x7F,
        size & 0x7F
    ])


def from_synchsafe(data: bytes) -> int:
    """Decodes a 4-byte ID3v2 synchsafe integer."""
    if len(data) < 4:
        return 0
    return ((data[0] & 0x7F) << 21) | ((data[1] & 0x7F) << 14) | ((data[2] & 0x7F) << 7) | (data[3] & 0x7F)


def make_id3_frame(frame_id: str, text: str, encoding: int = 3) -> bytes:
    """
    Builds a single 10-byte ID3v2.3 frame header + payload.
    ID3v2.3: Frame size is a 32-bit big-endian unsigned integer (NOT synchsafe).
    Encoding:
      0x00: ISO-8859-1 (Latin-1)
      0x01: UTF-16 with BOM
      0x02: UTF-16-BE without BOM
      0x03: UTF-8
    """
    fid = frame_id.encode("ascii")[:4].ljust(4, b" ")
    enc_byte = bytes([encoding])

    if fid == b"COMM":
        # COMM payload: encoding (1B) + language (3B) + short description (null-term) + text
        lang = b"eng"
        desc_null = b"\x00"
        body_bytes = text.encode("utf-8" if encoding == 3 else "latin1", errors="replace")
        payload = enc_byte + lang + desc_null + body_bytes
    else:
        # Standard text frame (TIT2, TPE1, TALB, TBPM, TKEY, TCON, TYER, etc.)
        body_bytes = text.encode("utf-8" if encoding == 3 else "latin1", errors="replace")
        payload = enc_byte + body_bytes

    # ID3v2.3 frame header: 4B ID + 4B length uint32 BE + 2B flags
    header = fid + struct.pack(">I", len(payload)) + b"\x00\x00"
    return header + payload


def build_id3v23_tag(frames: Dict[str, str], encoding: int = 3) -> bytes:
    """
    Assembles a complete ID3v2.3 tag block with top-level synchsafe size header.
    Total header is 10 bytes: b'ID3' + \x03\x00 (v2.3.0) + \x00 (flags) + 4B synchsafe size.
    """
    body = bytearray()
    for fid, val in frames.items():
        if val is not None and str(val) != "":
            body.extend(make_id3_frame(fid, str(val), encoding=encoding))

    tag_len = len(body)
    synchsafe_len = to_synchsafe(tag_len)
    return b"ID3\x03\x00\x00" + synchsafe_len + bytes(body)


# -----------------------------------------------------------------------------
# 2. MPEG-1 Layer 3 Audio Stream Builder
# -----------------------------------------------------------------------------

def build_mpeg_frames(duration_sec: float = 2.0, track_id: int = 1) -> bytes:
    """
    Generates syntactically valid MPEG-1 Layer 3 audio frames.
    Injects track_id into the audio payload prefix so that every track possesses
    a genuinely unique pure audio SHA-256 seal (crucial for SoundSeal and TrackMatcher tests).
    """
    frame_count = max(1, round(duration_sec * SAMPLE_RATE / SAMPLES_PER_FRAME))
    payload_prefix = struct.pack(">I", track_id & 0xFFFFFFFF)
    payload_padding = b"\x00" * (MPEG_PAYLOAD_SIZE - len(payload_prefix))
    single_frame = MPEG1_L3_128K_44K_HEADER + payload_prefix + payload_padding
    return single_frame * frame_count


def create_synthetic_mp3(
    target_path: Union[str, Path],
    track: Optional[SyntheticTrack] = None,
    **kwargs
) -> Path:
    """
    Creates a physical MP3 file on disk with ID3v2.3 metadata and valid MPEG-1 L3 frames.
    Accepts a SyntheticTrack instance or arbitrary kwargs (title, artist, album, bpm, key,
    genre, year, comment, duration_sec, track_id, duration_frames, custom_tags).
    """
    out_path = Path(target_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if track is not None:
        t = track
    else:
        # Handle backward compatibility with duration_frames
        duration_sec = kwargs.get("duration_sec")
        if duration_sec is None and "duration_frames" in kwargs:
            duration_sec = kwargs["duration_frames"] * FRAME_DURATION_SEC
        elif duration_sec is None:
            duration_sec = 2.0

        t = SyntheticTrack(
            title=kwargs.get("title", "Synthetic Track"),
            artist=kwargs.get("artist", "Serato Artist"),
            album=kwargs.get("album", "Synthetic Library"),
            bpm=str(kwargs.get("bpm", "124.0")),
            key=str(kwargs.get("key", "8A")),
            genre=kwargs.get("genre", "House"),
            year=str(kwargs.get("year", "2024")),
            comment=kwargs.get("comment", ""),
            duration_sec=float(duration_sec),
            track_id=int(kwargs.get("track_id", 1)),
            custom_tags=kwargs.get("custom_tags") or kwargs.get("extra_tags") or {},
        )

    tag_dict = {
        "TIT2": t.title,
        "TPE1": t.artist,
        "TALB": t.album,
        "TBPM": t.bpm,
        "TKEY": t.key,
        "TCON": t.genre,
        "TYER": t.year,
    }
    if t.comment:
        tag_dict["COMM"] = t.comment
    tag_dict.update(t.custom_tags)

    id3_bytes = build_id3v23_tag(tag_dict, encoding=3)
    audio_bytes = build_mpeg_frames(t.duration_sec, track_id=t.track_id)
    out_path.write_bytes(id3_bytes + audio_bytes)
    return out_path


# -----------------------------------------------------------------------------
# 3. Serato Binary .crate and Preference Builders
# -----------------------------------------------------------------------------

def criar_tag_tlv(tag_str: str, valor_str: str) -> bytes:
    """
    Constructs a Serato TLV chunk with string value encoded in UTF-16-BE without BOM.
    Matches serato_macos_app.py and crate_ops.py specification.
    """
    tag_bytes = tag_str.encode("ascii")[:4].ljust(4, b" ")
    norm_val = unicodedata.normalize("NFC", str(valor_str))
    val_bytes = norm_val.encode("utf-16-be")
    return tag_bytes + struct.pack(">I", len(val_bytes)) + val_bytes


def make_otrk_chunk(relative_track_path: str) -> bytes:
    """
    Constructs an 'otrk' (Outer Track) container chunk encapsulating a 'ptrk' chunk.
    """
    ptrk = criar_tag_tlv("ptrk", relative_track_path)
    return b"otrk" + struct.pack(">I", len(ptrk)) + ptrk


def create_crate_binary(
    track_rel_paths: List[str],
    custom_blocks: Optional[List[bytes]] = None,
    use_legacy_ascii_vrsn: bool = False
) -> bytes:
    """
    Generates binary .crate file content matching Serato DJ specifications.
    Preserves custom blocks (like 'ovct' column views) if provided.
    """
    header = LEGACY_ASCII_VRSN_HEADER if use_legacy_ascii_vrsn else CANONICAL_VRSN_HEADER
    out = bytearray(header)
    if custom_blocks:
        for b in custom_blocks:
            if isinstance(b, tuple) and len(b) == 2:
                # (tag, data) tuple
                tag, data = b
                tag_b = tag.encode("ascii") if isinstance(tag, str) else tag
                out.extend(tag_b[:4].ljust(4, b" ") + struct.pack(">I", len(data)) + data)
            elif isinstance(b, (bytes, bytearray)):
                out.extend(b)
    for p in track_rel_paths:
        out.extend(make_otrk_chunk(str(p)))
    return bytes(out)


def write_crate_file(
    crate_file_path: Union[str, Path],
    track_rel_paths: List[str],
    custom_blocks: Optional[List[bytes]] = None,
    use_legacy_ascii_vrsn: bool = False
) -> Path:
    """Writes a binary .crate file to disk."""
    out_path = Path(crate_file_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(create_crate_binary(track_rel_paths, custom_blocks, use_legacy_ascii_vrsn))
    return out_path


def build_neworder_pref(crate_names: List[str]) -> bytes:
    """
    Builds neworder.pref binary content.
    Header: CANONICAL_VRSN_HEADER
    Items: nior wrapping tvcn with crate name in UTF-16-BE without BOM.
    """
    out = bytearray(CANONICAL_VRSN_HEADER)
    for name in crate_names:
        tvcn = criar_tag_tlv("tvcn", name)
        nior = b"nior" + struct.pack(">I", len(tvcn)) + tvcn
        out.extend(nior)
    return bytes(out)


def write_neworder_pref(pref_file_path: Union[str, Path], crate_names: List[str]) -> Path:
    """Writes a neworder.pref file to disk."""
    out_path = Path(pref_file_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build_neworder_pref(crate_names))
    return out_path


def read_crate_paths(crate_path: Union[str, Path]) -> List[str]:
    """
    Parses all 'ptrk' track paths from a Serato .crate file.
    Decodes UTF-16-BE without BOM and normalizes NFC.
    """
    cpath = Path(crate_path)
    if not cpath.exists():
        return []
    data = cpath.read_bytes()
    if len(data) < 8:
        return []

    # First block is vrsn
    tag = data[:4]
    if tag != b"vrsn":
        return []
    header_len = struct.unpack(">I", data[4:8])[0]
    idx = 8 + header_len
    total_len = len(data)

    paths = []
    while idx + 8 <= total_len:
        block_tag = data[idx : idx + 4]
        try:
            block_len = struct.unpack(">I", data[idx + 4 : idx + 8])[0]
        except Exception:
            break
        block_end = idx + 8 + block_len
        if block_end > total_len:
            break

        if block_tag == b"otrk":
            otrk_payload = data[idx + 8 : block_end]
            p_idx = 0
            while p_idx + 8 <= len(otrk_payload):
                p_tag = otrk_payload[p_idx : p_idx + 4]
                try:
                    p_len = struct.unpack(">I", otrk_payload[p_idx + 4 : p_idx + 8])[0]
                except Exception:
                    break
                p_end = p_idx + 8 + p_len
                if p_end <= len(otrk_payload) and p_tag == b"ptrk":
                    try:
                        raw_path = otrk_payload[p_idx + 8 : p_end].decode("utf-16-be")
                        paths.append(unicodedata.normalize("NFC", raw_path))
                    except Exception:
                        pass
                    break
                p_idx = p_end

        idx = block_end

    return paths


# -----------------------------------------------------------------------------
# 4. Multi-Level Directory Tree & Standard Library Generator
# -----------------------------------------------------------------------------

def generate_standard_dj_library(
    mp3_base_dir: Union[str, Path],
    tracks_per_crate: int = 5,
    accented: bool = True
) -> Dict[str, List[Path]]:
    """
    Generates a realistic multi-level DJ library:
      - House/Deep House (122.0 to 124.0 BPM, 8A/9A)
      - House/Tech House (125.0 to 128.0 BPM, 4A/5A)
      - Techno/Melodic (126.0 to 130.0 BPM, 6A/7A)
      - Techno/Peak Time (130.0 to 135.0 BPM, 11A/12A)
      - Latin/Reggaeton (92.0 to 98.0 BPM, 8B/9B)
      - Latin/Salsa & Merengue (105.0 to 115.0 BPM, 1A/2A)
      - Brasil/Samba & Pagode (100.0 to 112.0 BPM, 7B/8B)
      - Pop/80s Pop (118.0 to 125.0 BPM, 3A/4B)
    Includes accented unicode titles when accented=True.
    Returns: mapping {crate_name: [list of generated file paths]}
    """
    base = Path(mp3_base_dir)
    base.mkdir(parents=True, exist_ok=True)

    genres_specs = [
        ("House/Deep House", 123.0, "8A", "Deep House", "Deep Soul"),
        ("House/Tech House", 126.0, "4A", "Tech House", "Tech Grooves"),
        ("Techno/Melodic", 128.0, "6A", "Melodic Techno", "Astral Realm"),
        ("Techno/Peak Time", 132.0, "11A", "Peak Time Techno", "Warehouse Rave"),
        ("Latin/Reggaeton", 94.0, "8B", "Reggaeton", "Perreo Intenso"),
        ("Latin/Salsa & Merengue", 108.0, "1A", "Latin", "Sabor Latino"),
        ("Brasil/Samba & Pagode", 104.0, "7B", "Samba", "Roda de Samba"),
        ("Pop/80s Pop", 120.0, "3A", "Pop", "Retro Synth"),
    ]

    accented_titles = [
        "Café do Amanhã",
        "Ébano Tropical",
        "Coração de Melodia",
        "Canción del Mar",
        "Batuque & Alegria",
        "Noite de Verão",
        "Sombra & Luz",
        "Ilusão Noturna",
    ]

    out_mapping: Dict[str, List[Path]] = {}
    track_counter = 100

    for folder_rel, base_bpm, base_key, genre_name, album_name in genres_specs:
        crate_name = folder_rel.replace("/", "%%")
        folder_path = base / folder_rel
        folder_path.mkdir(parents=True, exist_ok=True)
        track_list: List[Path] = []

        for i in range(tracks_per_crate):
            track_counter += 1
            if accented and i < len(accented_titles):
                title = f"{accented_titles[i]} (Original Mix)"
            else:
                title = f"{genre_name} Track {i + 1} (Club Mix)"

            bpm = f"{base_bpm + (i * 0.5):.1f}"
            key = base_key

            t = SyntheticTrack(
                title=title,
                artist=f"DJ {genre_name.split()[0]}",
                album=album_name,
                bpm=bpm,
                key=key,
                genre=genre_name,
                year="2024",
                duration_sec=2.5,
                track_id=track_counter,
            )

            file_path = folder_path / f"Track_{i + 1:02d}_{t.title.split()[0]}.mp3"
            create_synthetic_mp3(file_path, track=t)
            track_list.append(file_path)

        out_mapping[crate_name] = track_list

    return out_mapping
