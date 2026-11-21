#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - HARMONIC KEY CONVERTER (key_converter.py)
================================================================================
Conversor bidirecional entre sistemas de notação harmônica para DJs:
  - Camelot (1A..12A, 1B..12B)
  - Musical / Tradicional (Am, C, F#m, Eb...)
  - OpenKey (1d..12d, 1m..12m)
================================================================================
"""

import sys
import os
import json
import argparse
from pathlib import Path
from typing import Dict, Any, Optional

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import mutagen
    from mutagen.id3 import ID3, TKEY
except ImportError:
    mutagen = None

# Mapeamentos bidirecionais
CAMELOT_TO_MUSICAL = {
    "1A": "Abm", "1B": "B",
    "2A": "Ebm", "2B": "F#",
    "3A": "Bbm", "3B": "Db",
    "4A": "Fm",  "4B": "Ab",
    "5A": "Cm",  "5B": "Eb",
    "6A": "Gm",  "6B": "Bb",
    "7A": "Dm",  "7B": "F",
    "8A": "Am",  "8B": "C",
    "9A": "Em",  "9B": "G",
    "10A": "Bm", "10B": "D",
    "11A": "F#m", "11B": "A",
    "12A": "C#m", "12B": "E"
}

MUSICAL_ALIASES = {
    "g#m": "1A", "abm": "1A", "b": "1B", "bmaj": "1B", "b major": "1B",
    "d#m": "2A", "ebm": "2A", "f#": "2B", "f#maj": "2B", "gb": "2B", "gbmaj": "2B",
    "a#m": "3A", "bbm": "3A", "c#": "3B", "c#maj": "3B", "db": "3B", "dbmaj": "3B",
    "fm": "4A", "fmin": "4A", "g#": "4B", "ab": "4B", "abmaj": "4B",
    "cm": "5A", "cmin": "5A", "d#": "5B", "eb": "5B", "ebmaj": "5B",
    "gm": "6A", "gmin": "6A", "a#": "6B", "bb": "6B", "bbmaj": "6B",
    "dm": "7A", "dmin": "7A", "f": "7B", "fmaj": "7B",
    "am": "8A", "amin": "8A", "c": "8B", "cmaj": "8B",
    "em": "9A", "emin": "9A", "g": "9B", "gmaj": "9B",
    "bm": "10A", "bmin": "10A", "d": "10B", "dmaj": "10B",
    "f#m": "11A", "gbm": "11A", "a": "11B", "amaj": "11B",
    "c#m": "12A", "dbm": "12A", "e": "12B", "emaj": "12B"
}


class KeyConverter:
    """Conversor harmônico de chaves musicais."""

    @staticmethod
    def normalize_to_camelot(key_str: str) -> Optional[str]:
        """Converte qualquer string de chave (Musical, OpenKey, Camelot) para Camelot."""
        if not key_str:
            return None
        clean = key_str.strip().upper()

        # Já é Camelot? (ex: 8A, 11B)
        if clean in CAMELOT_TO_MUSICAL:
            return clean

        # OpenKey: 1d..12d (menor -> A), 1m..12m (maior -> B)
        if clean.endswith("D") and clean[:-1].isdigit():
            num = int(clean[:-1])
            if 1 <= num <= 12:
                return f"{num}A"
        if clean.endswith("M") and clean[:-1].isdigit():
            num = int(clean[:-1])
            if 1 <= num <= 12:
                return f"{num}B"

        # Musical
        lower = key_str.strip().lower()
        if lower in MUSICAL_ALIASES:
            return MUSICAL_ALIASES[lower]

        return None

    @staticmethod
    def convert(key_str: str, target_format: str = "camelot") -> str:
        """
        Converte uma chave para o formato desejado: 'camelot', 'musical' ou 'openkey'.
        """
        camelot = KeyConverter.normalize_to_camelot(key_str)
        if not camelot:
            return key_str

        fmt = target_format.lower()
        if fmt == "camelot":
            return camelot
        elif fmt == "musical":
            return CAMELOT_TO_MUSICAL.get(camelot, camelot)
        elif fmt == "openkey":
            num = camelot[:-1]
            letter = "d" if camelot.endswith("A") else "m"
            return f"{num}{letter}"

        return camelot

    @staticmethod
    def update_file_key(filepath: str, target_format: str = "camelot") -> Dict[str, Any]:
        """Lê a tag TKEY do arquivo, converte e regrava no formato selecionado."""
        path = Path(filepath).resolve()
        if not path.is_file():
            return {"sucesso": False, "erro": "Arquivo não encontrado"}

        if not mutagen:
            return {"sucesso": False, "erro": "Mutagen não disponível"}

        try:
            audio = ID3(str(path))
            old_key = str(audio["TKEY"]) if "TKEY" in audio else ""
            if not old_key:
                return {"sucesso": False, "erro": "Nenhuma tag TKEY encontrada no arquivo"}

            new_key = KeyConverter.convert(old_key, target_format)
            audio["TKEY"] = TKEY(encoding=3, text=new_key)
            audio.save(str(path), v2_version=3)

            return {
                "sucesso": True,
                "filepath": str(path),
                "old_key": old_key,
                "new_key": new_key,
                "format": target_format
            }
        except Exception as e:
            return {"sucesso": False, "erro": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Harmonic Key Converter")
    parser.add_argument("--key", type=str, help="Chave musical a converter (ex: 8A, Am, 8d)")
    parser.add_argument("--to", type=str, choices=["camelot", "musical", "openkey"], default="camelot")
    parser.add_argument("--file", type=str, help="Arquivo MP3 para converter tag TKEY")

    args = parser.parse_args()

    if args.key:
        converted = KeyConverter.convert(args.key, args.to)
        print(json.dumps({"original": args.key, "target_format": args.to, "converted": converted}, ensure_ascii=False))
        return

    if args.file:
        res = KeyConverter.update_file_key(args.file, args.to)
        print(json.dumps(res, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
