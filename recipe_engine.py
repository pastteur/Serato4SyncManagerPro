#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - RECIPE ENGINE WITH UNDO (recipe_engine.py)
================================================================================
Executa receitas, transformadores de metadados e Smart Fixes de biblioteca
com histórico transacional e suporte completo a rollback (Undo).
================================================================================
"""

import sys
import os
import re
import html
import json
import uuid
import sqlite3
import argparse
import unicodedata
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import mutagen
    from mutagen.id3 import ID3, TIT2, TPE1, TPE4
except ImportError:
    mutagen = None

DEFAULT_UNDO_DB = Path.home() / ".serato_recipe_history.sqlite"

# Regras e vocabulário para Smart Casing (DJ Friendly)
UPPERCASE_TOKENS = {
    "DJ", "MC", "VIP", "EP", "LP", "BPM", "ID", "PT", "BR", "UK", "USA", "NYC", "LA",
    "DJS", "MCS", "KBPS", "HQ", "HD", "OG", "VS", "II", "III", "IV"
}

LOWERCASE_ARTICLES = {
    "de", "da", "do", "dos", "das", "e", "em", "no", "na", "nos", "nas", "por", "para",
    "com", "in", "on", "the", "a", "an", "at", "by", "for", "of", "and", "or", "vs",
    "ft", "feat", "del", "la", "el", "los", "las"
}

PROMO_PATTERNS = [
    re.compile(r'\[\s*(?:kondzilla|kond\s*zilla|dj\s*pool|exclusive|megapack|fdm|release\s*date[^\]]*)\s*\]', re.IGNORECASE),
    re.compile(r'\(\s*(?:kondzilla|dj\s*pool|exclusive|megapack)\s*\)', re.IGNORECASE),
    re.compile(r'[\(\[]\s*(?:clipe|vídeo|video|áudio|audio|webclipe|lyric\s*video|music\s*video|official\s*(?:video|audio|music\s*video|lyric\s*video)?)\s*(?:oficial)?(?:\s*\(?[0-9]{3,4}p\)?|\s*\(?hd\)?|\s*\(?4k\)?)?\s*[\)\]]', re.IGNORECASE),
    re.compile(r'\b(?:clipe|vídeo|video|áudio|audio|webclipe)\s*oficial\b', re.IGNORECASE),
    re.compile(r'[\(\[]\s*(?:hd|hq|4k|1080p|720p)\s*[\)\]]', re.IGNORECASE),
    re.compile(r'[\(\[]\s*\d{2,3}\s*kbps\s*[\)\]]', re.IGNORECASE),
    re.compile(r'\b\d{2,3}\s*kbps\b', re.IGNORECASE),
    re.compile(r'\s*-\s*cópia(?:\s*\d+)?\b', re.IGNORECASE),
    re.compile(r'\s*-\s*copy(?:\s*\d+)?\b', re.IGNORECASE),
    re.compile(r'\s*\(\d+\)\s*$'),
]

URL_PATTERNS = [
    re.compile(r'\[\s*(?:www|http)[^\]]*\]?', re.IGNORECASE),
    re.compile(r'\b(?:https?://)?(?:www\.)[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)*\.(?:com|net|org|website|site|top|ru|io|co|me|vip|cc|club|online|link|info|ws|biz|fm|dj|mp3s?)(?=[A-Z\s\-_]|$)', re.IGNORECASE),
    re.compile(r'\b(?:myfreemp3|123savemp3|spotidown|mp3clan|convert2mp3|y2mate|savefrom|360ytmp3)\.[a-z]{2,5}\b', re.IGNORECASE),
    re.compile(r'\bRadioFLy\s*ws\b', re.IGNORECASE),
    re.compile(r'(?:^|\s)www[\.\-_/]*(?:\s|$)', re.IGNORECASE),
]

LEADING_TRACK_NUM = re.compile(r'^\d{1,3}(?:\s*[-–.]\s*|\s+)(?=[A-Za-zÀ-ÿ])')

GENERIC_ARTISTS = {
    "unknown", "desconhecido", "sem artista", "artista desconhecido",
    "various", "various artists", "va", "v.a.", "diversos", "vários", "varios"
}


# ==============================================================================
# FUNÇÕES DE TRANSFORMAÇÃO DE TEXTO (SMART FIXES)
# ==============================================================================

def smart_fix_casing(text: str) -> str:
    """Capitalização inteligente que respeita siglas de DJ, artigos e inícios de frase."""
    if not text:
        return ""
    words = re.split(r'(\s+|[-–—()\[\]:])', text)
    processed = []
    
    last_delim = True  # Início de texto conta como início de frase
    
    for i, token in enumerate(words):
        if not token or token.isspace():
            processed.append(token)
            continue
        if token in '-–—()[]:':
            processed.append(token)
            last_delim = True
            continue
            
        base = token.strip(".:;,\"")
        base_upper = base.upper()
        base_lower = base.lower()
        
        # Reconhece pontuação de fechamento (ex: "feat." -> base="feat", suffix=".")
        suffix = token[len(base):] if token.startswith(base) else ""
        prefix = token[:token.find(base)] if base and base in token else ""

        if base_upper in UPPERCASE_TOKENS:
            processed.append(f"{prefix}{base_upper}{suffix}")
        elif base_lower in ("feat", "ft"):
            processed.append(f"{prefix}{base_lower}{suffix}")
        elif not last_delim and base_lower in LOWERCASE_ARTICLES and i < len(words) - 1:
            processed.append(f"{prefix}{base_lower}{suffix}")
        else:
            processed.append(f"{prefix}{base.capitalize()}{suffix}")
            
        last_delim = False
            
    res = "".join(processed)
    return re.sub(r'\s+', ' ', res).strip()


def smart_replace_with_space(text: str) -> str:
    """Substitui underscores, pontos soltos e %20 por espaços limpos."""
    if not text:
        return ""
    t = text.replace('_', ' ').replace('%20', ' ')
    # Substitui pontos entre palavras (ex: Artist.Track -> Artist Track), exceto extensões ou ft.
    t = re.sub(r'(?<=[a-zA-Z0-9])\.(?=[a-zA-Z0-9])', ' ', t)
    t = re.sub(r'\s*-\s*-\s*', ' - ', t)
    return re.sub(r'\s+', ' ', t).strip()


def smart_fix_encoded(text: str) -> str:
    """Decodifica entidades HTML e corrige Mojibake comum (UTF-8 lido como Latin-1)."""
    if not text:
        return ""
    t = html.unescape(text)
    t = unicodedata.normalize('NFC', t)
    
    # Tentativa de conserto de Mojibake comum
    if any(m in t for m in ['Ã£', 'Ã¡', 'Ã©', 'Ã³', 'Ã§', 'Ã', 'Ãº', 'Â']):
        try:
            fixed = t.encode('latin1').decode('utf-8')
            t = fixed
        except Exception:
            pass
            
    return t.strip()


def smart_extract_artist(title: str, artist: str) -> Tuple[str, str]:
    """Extrai Artista do Título caso haja delimitador ' - ' e o artista esteja vago."""
    if not title:
        return title, artist
        
    art_clean = (artist or "").strip().lower()
    is_generic = not art_clean or art_clean in GENERIC_ARTISTS
    
    if ' - ' in title:
        parts = title.split(' - ', 1)
        p_artist = parts[0].strip()
        p_title = parts[1].strip()
        if is_generic and p_artist and p_title:
            return p_title, p_artist
            
    return title, artist


def smart_extract_remixer(title: str) -> Tuple[str, Optional[str]]:
    """Extrai o nome do remixer do título mantendo o título limpo."""
    if not title:
        return title, None
        
    m = re.search(r'[\(\[]([^\)\]]+?)\s+(?:Remix|Mix|Edit|Bootleg|VIP|Rework|Dub)[\)\]]', title, re.IGNORECASE)
    if m:
        remixer_candidate = m.group(1).strip()
        # Se for apenas 'Extended' ou 'Club', não é um remixer nomeado
        if remixer_candidate.lower() not in {"extended", "original", "club", "radio", "vip", "dub", "live"}:
            return title, remixer_candidate
            
    return title, None


def smart_extract_mix(title: str) -> str:
    """Padroniza descritores de versão (ex: Extended Mix) com parênteses."""
    if not title:
        return ""
    # Padrão: "Track Name Extended Mix" -> "Track Name (Extended Mix)"
    pattern = re.compile(r'\b(Extended Mix|Original Mix|Club Mix|Radio Edit|VIP Mix|Acoustic Version|Dub Mix|Instrumental|Acapella)\b(?!\))', re.IGNORECASE)
    if pattern.search(title) and not re.search(r'[\(\[][^\)\]]*mix[^\)\]]*[\)\]]', title, re.IGNORECASE):
        title = pattern.sub(r'(\1)', title)
    return re.sub(r'\s+', ' ', title).strip()


def smart_remove_garbage(text: str) -> str:
    """Remove caracteres lixo, colchetes vazios e traços residuais."""
    if not text:
        return ""
    t = text
    t = re.sub(r'\[\s*\]|\(\s*\)', '', t)
    t = re.sub(r'\s*-\s*-\s*', ' - ', t)
    t = re.sub(r'[\u2013\u2014]', '-', t)
    t = re.sub(r'["\']{2,}', '', t)
    t = re.sub(r'\s*-\s*cópia(?:\s*\d+)?\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*-\s*copy(?:\s*\d+)?\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*\(\d+\)\s*$', '', t)
    t = re.sub(r'^\s*[-–.]\s*', '', t)
    t = re.sub(r'\s*[-–.]\s*$', '', t)
    return re.sub(r'\s+', ' ', t).strip()


def smart_remove_promo(text: str) -> str:
    """Remove propagandas de canais, sites e pools."""
    if not text:
        return ""
    t = text
    for pat in PROMO_PATTERNS:
        t = pat.sub(' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def smart_remove_number_prefix(text: str) -> str:
    """Remove numerações de início como '01 - ', '02. '."""
    if not text:
        return ""
    return LEADING_TRACK_NUM.sub('', text).strip()


def smart_remove_urls(text: str) -> str:
    """Remove URLs e domínios da web."""
    if not text:
        return ""
    t = text
    for pat in URL_PATTERNS:
        t = pat.sub(' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def smart_add_mix_parentheses(text: str) -> str:
    """Garante que versões como Extended Mix estejam entre parênteses."""
    return smart_extract_mix(text)


def smart_remove_common_text(text: str, to_remove: str) -> str:
    """Remove uma palavra ou frase arbitrária especificada pelo usuário."""
    if not text or not to_remove:
        return text
    pattern = re.compile(re.escape(to_remove), re.IGNORECASE)
    res = pattern.sub('', text)
    return re.sub(r'\s+', ' ', res).strip()


# ==============================================================================
# MOTOR DE EXECUÇÃO DE RECEITAS COM HISTÓRICO TRANSACIONAL
# ==============================================================================

class RecipeEngine:
    """Motor de execução de receitas em lote com snapshot e histórico de Undo."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path:
            self.db_path = Path(db_path).resolve()
        else:
            try:
                candidate = DEFAULT_UNDO_DB.resolve()
                candidate.parent.mkdir(parents=True, exist_ok=True)
                with open(candidate.parent / ".perm_check", "w") as f:
                    f.write("ok")
                (candidate.parent / ".perm_check").unlink()
                self.db_path = candidate
            except (PermissionError, OSError):
                self.db_path = (Path(__file__).resolve().parent / ".serato_recipe_history.sqlite").resolve()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recipe_sessions (
                    session_id TEXT PRIMARY KEY,
                    recipe_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    affected_count INTEGER NOT NULL,
                    is_undone INTEGER DEFAULT 0
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recipe_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    old_state_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES recipe_sessions(session_id)
                );
            """)
            conn.commit()

    def apply_recipe(self, recipe_name: str, filepaths: List[str], params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Aplica a receita em lote registrando snapshot de cada arquivo para desfazer."""
        session_id = str(uuid.uuid4())[:12]
        now_str = datetime.now().isoformat()
        params = params or {}

        snapshots = []
        processed_count = 0
        errors = []

        for f_path in filepaths:
            path = Path(f_path).resolve()
            if not path.is_file():
                continue

            try:
                audio = ID3(str(path))
            except Exception:
                continue

            old_state = {
                "title": str(audio["TIT2"]) if "TIT2" in audio else path.stem,
                "artist": str(audio["TPE1"]) if "TPE1" in audio else "",
                "remixer": str(audio["TPE4"]) if "TPE4" in audio else ""
            }

            new_title = old_state["title"]
            new_artist = old_state["artist"]
            new_remixer = old_state["remixer"]

            # ------------------------------------------------------------------
            # Roteamento dos Smart Fixes e Receitas
            # ------------------------------------------------------------------
            if recipe_name == "swap_artist_title":
                new_title, new_artist = old_state["artist"], old_state["title"]

            elif recipe_name in ("title_case", "fix_casing", "smart_casing"):
                new_title = smart_fix_casing(old_state["title"])
                if new_artist:
                    new_artist = smart_fix_casing(old_state["artist"])

            elif recipe_name == "uppercase":
                new_title = old_state["title"].upper()
                if new_artist:
                    new_artist = old_state["artist"].upper()

            elif recipe_name == "strip_brackets":
                new_title = re.sub(r'\[.*?\]', '', old_state["title"]).strip()
                new_title = re.sub(r'\s+', ' ', new_title)

            elif recipe_name == "strip_parentheses":
                new_title = re.sub(r'\(.*?\)', '', old_state["title"]).strip()
                new_title = re.sub(r'\s+', ' ', new_title)

            elif recipe_name == "replace_with_space":
                new_title = smart_replace_with_space(old_state["title"])
                if new_artist:
                    new_artist = smart_replace_with_space(old_state["artist"])

            elif recipe_name == "fix_encoded":
                new_title = smart_fix_encoded(old_state["title"])
                if new_artist:
                    new_artist = smart_fix_encoded(old_state["artist"])

            elif recipe_name == "extract_artist_from_title":
                new_title, new_artist = smart_extract_artist(old_state["title"], old_state["artist"])

            elif recipe_name == "extract_remixer":
                clean_title, extracted_rem = smart_extract_remixer(old_state["title"])
                if extracted_rem:
                    new_remixer = extracted_rem

            elif recipe_name in ("extract_mix", "add_mix_parentheses"):
                new_title = smart_add_mix_parentheses(old_state["title"])

            elif recipe_name == "remove_garbage":
                new_title = smart_remove_garbage(old_state["title"])
                if new_artist:
                    new_artist = smart_remove_garbage(old_state["artist"])

            elif recipe_name == "remove_promo":
                new_title = smart_remove_promo(old_state["title"])
                if new_artist:
                    new_artist = smart_remove_promo(old_state["artist"])

            elif recipe_name == "remove_number_prefix":
                new_title = smart_remove_number_prefix(old_state["title"])

            elif recipe_name == "remove_urls":
                new_title = smart_remove_urls(old_state["title"])
                if new_artist:
                    new_artist = smart_remove_urls(old_state["artist"])

            elif recipe_name == "remove_common_text":
                txt = params.get("text", "")
                if txt:
                    new_title = smart_remove_common_text(old_state["title"], txt)
                    if new_artist:
                        new_artist = smart_remove_common_text(old_state["artist"], txt)

            else:
                errors.append(f"Receita desconhecida: {recipe_name}")
                break

            # Se não houve modificação de fato, não reescreve
            if new_title == old_state["title"] and new_artist == old_state["artist"] and new_remixer == old_state["remixer"]:
                continue

            # Grava alteração atômica em ID3v2.3
            try:
                audio["TIT2"] = TIT2(encoding=3, text=new_title)
                if new_artist:
                    audio["TPE1"] = TPE1(encoding=3, text=new_artist)
                if new_remixer:
                    audio["TPE4"] = TPE4(encoding=3, text=new_remixer)

                audio.save(str(path), v2_version=3)
                snapshots.append((session_id, str(path), json.dumps(old_state)))
                processed_count += 1
            except Exception as e:
                errors.append(f"Erro ao salvar {path.name}: {e}")

        # Salva a sessão de Undo se pelo menos um arquivo foi processado
        if snapshots:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO recipe_sessions (session_id, recipe_name, timestamp, affected_count, is_undone)
                    VALUES (?, ?, ?, ?, 0);
                """, (session_id, recipe_name, now_str, len(snapshots)))
                cursor.executemany("""
                    INSERT INTO recipe_snapshots (session_id, filepath, old_state_json)
                    VALUES (?, ?, ?);
                """, snapshots)
                conn.commit()

        return {
            "sucesso": processed_count > 0 or len(errors) == 0,
            "session_id": session_id,
            "recipe_name": recipe_name,
            "affected_count": processed_count,
            "errors": errors
        }

    def undo_last(self) -> Dict[str, Any]:
        """Desfaz a última sessão de receita ativa restaurando o estado original."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT session_id, recipe_name FROM recipe_sessions
                WHERE is_undone = 0
                ORDER BY timestamp DESC LIMIT 1;
            """)
            row = cursor.fetchone()
            if not row:
                return {"sucesso": False, "erro": "Nenhuma ação recente para desfazer"}

            session_id = row["session_id"]
            recipe_name = row["recipe_name"]

            cursor.execute("SELECT filepath, old_state_json FROM recipe_snapshots WHERE session_id = ?;", (session_id,))
            snaps = cursor.fetchall()

            restored_count = 0
            errors = []

            for s in snaps:
                path = Path(s["filepath"])
                if not path.is_file():
                    continue

                old_state = json.loads(s["old_state_json"])
                try:
                    audio = ID3(str(path))
                    audio["TIT2"] = TIT2(encoding=3, text=old_state.get("title", ""))
                    if old_state.get("artist"):
                        audio["TPE1"] = TPE1(encoding=3, text=old_state["artist"])
                    if "remixer" in old_state:
                        if old_state["remixer"]:
                            audio["TPE4"] = TPE4(encoding=3, text=old_state["remixer"])
                        elif "TPE4" in audio:
                            del audio["TPE4"]

                    audio.save(str(path), v2_version=3)
                    restored_count += 1
                except Exception as e:
                    errors.append(f"Erro ao restaurar {path.name}: {e}")

            # Marca como revertida
            cursor.execute("UPDATE recipe_sessions SET is_undone = 1 WHERE session_id = ?;", (session_id,))
            conn.commit()

            return {
                "sucesso": restored_count > 0,
                "session_id": session_id,
                "recipe_name": recipe_name,
                "restored_count": restored_count,
                "errors": errors
            }


def main():
    parser = argparse.ArgumentParser(description="Recipe Engine with Undo - Smart Fixes & Transformers")
    parser.add_argument("--recipe", type=str, help="Nome da receita a aplicar")
    parser.add_argument("--files", nargs="+", help="Arquivos para aplicar a receita")
    parser.add_argument("--param", type=str, default="", help="Parâmetro textual opcional (ex: texto a remover)")
    parser.add_argument("--undo", action="store_true", help="Desfaz a última receita aplicada")

    args = parser.parse_args()
    engine = RecipeEngine()

    if args.undo:
        res = engine.undo_last()
        print(json.dumps(res, ensure_ascii=False))
        return

    if args.recipe and args.files:
        params = {}
        if args.param:
            params["text"] = args.param
        res = engine.apply_recipe(args.recipe, args.files, params)
        print(json.dumps(res, ensure_ascii=False))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
