#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - TAXONOMY CLEANER (taxonomy_cleaner.py)
================================================================================
Normalização inteligente de Gêneros (TCON) e Artistas (TPE1):
  - Funde variações ortográficas de gêneros (ex: tech-house -> Tech House)
  - Padroniza colaborações de artistas (feat., vs., pres.)
================================================================================
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import mutagen
    from mutagen.id3 import ID3, TCON, TPE1
except ImportError:
    mutagen = None

GENRE_CANONICAL_MAP = {
    "tech house": "Tech House", "tech-house": "Tech House", "techhouse": "Tech House",
    "deep house": "Deep House", "deep-house": "Deep House", "deephouse": "Deep House",
    "afro house": "Afro House", "afro-house": "Afro House", "afrohouse": "Afro House",
    "progressive house": "Progressive House", "prog house": "Progressive House",
    "melodic house & techno": "Melodic House & Techno", "melodic techno": "Melodic Techno",
    "drum and bass": "Drum & Bass", "drum & bass": "Drum & Bass", "dnb": "Drum & Bass",
    "hip hop": "Hip-Hop", "hip-hop": "Hip-Hop", "hiphop": "Hip-Hop",
    "r&b": "R&B", "rnb": "R&B", "r and b": "R&B",
    "funk": "Funk", "funk carioca": "Funk Carioca", "brazilian funk": "Funk Carioca",
    "sertanejo": "Sertanejo", "sertanejo universitario": "Sertanejo Universitário",
    "axe": "Axé", "axé": "Axé", "pagode": "Pagode", "samba": "Samba"
}


class TaxonomyCleaner:
    """Higienizador de taxonomia musical (Gênero e Artista)."""

    @staticmethod
    def clean_genre(raw_genre: str) -> str:
        """Normaliza uma string de gênero para o formato canônico da indústria."""
        if not raw_genre:
            return ""
        clean = raw_genre.strip().lower()
        clean = re.sub(r'[\/\\;]+', ' / ', clean)
        
        # Checa mapeamento direto
        if clean in GENRE_CANONICAL_MAP:
            return GENRE_CANONICAL_MAP[clean]

        # Se tiver múltiplos gêneros separados por barra
        if ' / ' in clean:
            parts = [TaxonomyCleaner.clean_genre(p.strip()) for p in clean.split(' / ')]
            return " / ".join(filter(None, parts))

        # Capitaliza palavras normalmente se não houver regra específica
        return " ".join(word.capitalize() for word in clean.split())

    @staticmethod
    def clean_artist(raw_artist: str) -> str:
        """Padroniza marcadores de colaboração no nome do artista."""
        if not raw_artist:
            return ""
        artist = raw_artist.strip()

        # BUG FIX #2: padrões anteriores como r'\b(feat\.?)\b' casavam apenas 'feat'
        # (com \.? consumindo zero caracteres), deixando o ponto original no lugar e
        # produzindo duplicação "feat.. " quando o input já era "feat.".
        # O \b final falha após '.' (não é word-char), então o engine retrocede e casa
        # só 'feat', deixando o '.' solto. Solução: lookahead (?=\s|\Z) em vez de \b
        # no final, garantindo que o \.? opcional sempre consuma o ponto trailing.
        artist = re.sub(r'\b(?:ft|feat|featuring)\.?(?=\s|\Z)', 'feat.', artist, flags=re.IGNORECASE)
        # Padroniza vs., versus -> vs.
        artist = re.sub(r'\b(?:versus|vs)\.?(?=\s|\Z)', 'vs.', artist, flags=re.IGNORECASE)
        # Padroniza presents -> pres.
        artist = re.sub(r'\b(?:presents|pres)\.?(?=\s|\Z)', 'pres.', artist, flags=re.IGNORECASE)

        # Espaçamento limpo
        artist = re.sub(r'\s+', ' ', artist)
        return artist.strip()

    @staticmethod
    def process_file(filepath: str, update_genre: bool = True, update_artist: bool = True, dry_run: bool = False) -> Dict[str, Any]:
        """Inspeciona e opcionalmente aplica a limpeza nas tags do arquivo."""
        path = Path(filepath).resolve()
        if not path.is_file():
            return {"sucesso": False, "erro": "Arquivo não encontrado"}

        if not mutagen:
            return {"sucesso": False, "erro": "Mutagen não disponível"}

        try:
            audio = ID3(str(path))
            old_genre = str(audio["TCON"]) if "TCON" in audio else ""
            old_artist = str(audio["TPE1"]) if "TPE1" in audio else ""

            new_genre = TaxonomyCleaner.clean_genre(old_genre) if update_genre else old_genre
            new_artist = TaxonomyCleaner.clean_artist(old_artist) if update_artist else old_artist

            changed = (old_genre != new_genre) or (old_artist != new_artist)

            if changed and not dry_run:
                if update_genre and new_genre:
                    audio["TCON"] = TCON(encoding=3, text=new_genre)
                if update_artist and new_artist:
                    audio["TPE1"] = TPE1(encoding=3, text=new_artist)
                audio.save(str(path), v2_version=3)

            return {
                "sucesso": True,
                "filepath": str(path),
                "changed": changed,
                "old_genre": old_genre,
                "new_genre": new_genre,
                "old_artist": old_artist,
                "new_artist": new_artist
            }
        except Exception as e:
            return {"sucesso": False, "erro": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Taxonomy Cleaner Engine")
    parser.add_argument("--genre", type=str, help="Normaliza string de gênero")
    parser.add_argument("--artist", type=str, help="Normaliza string de artista")
    parser.add_argument("--file", type=str, help="Arquivo a ser processado")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula alterações")

    args = parser.parse_args()

    if args.genre:
        print(json.dumps({"original": args.genre, "cleaned": TaxonomyCleaner.clean_genre(args.genre)}, ensure_ascii=False))
        return

    if args.artist:
        print(json.dumps({"original": args.artist, "cleaned": TaxonomyCleaner.clean_artist(args.artist)}, ensure_ascii=False))
        return

    if args.file:
        res = TaxonomyCleaner.process_file(args.file, dry_run=args.dry_run)
        print(json.dumps(res, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
