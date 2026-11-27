#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 4 SYNC MANAGER PRO - SMART TAGS / MYTAGS (smart_tags.py)
================================================================================
Injeção e gerenciamento de MyTags estruturadas através do campo ID3 COMM (Comment)
utilizando formato padronizado com hashtags (#PeakTime, #Vocal, #WarmUp).
Permite filtragem instantânea pela barra de busca nativa do Serato DJ Pro.
================================================================================
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Set, Optional

sys.dont_write_bytecode = True

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import mutagen
    from mutagen.id3 import ID3, COMM
except ImportError:
    mutagen = None

DEFAULT_CATEGORIES = {
    "Energia": ["#WarmUp", "#BuildUp", "#PeakTime", "#AfterHours"],
    "Vibe": ["#Dark", "#Happy", "#Melodic", "#Groove", "#Tribal", "#Banger"],
    "Formato": ["#Vocal", "#Dub", "#Instrumental", "#Acapella", "#Extended"],
    "Situação": ["#IntroSet", "#PistaCheia", "#Transição", "#FimDeFesta"]
}


class SmartTagManager:
    """Gerencia tags com hashtag no campo Comment de arquivos de áudio."""

    @staticmethod
    def parse_comments(filepath: str) -> Dict[str, Any]:
        """Extrai texto livre e lista de tags (#Tag) do campo Comment."""
        path = Path(filepath).resolve()
        if not path.is_file():
            return {"sucesso": False, "erro": "Arquivo não encontrado"}

        if not mutagen:
            return {"sucesso": False, "erro": "Mutagen não instalado"}

        try:
            audio = ID3(str(path))
            raw_comment = ""
            for frame in audio.values():
                if frame.FrameID == "COMM":
                    # BUG FIX #3: str(frame) em frames COMM do mutagen produz uma
                    # representação com null bytes (\x00) no estilo "<lang>\x00<desc>\x00<text>",
                    # o que corrompe o campo free_text ao concatenar conteúdo duplicado.
                    # Correção: acessa frame.text[0] diretamente (string limpa da tag).
                    raw_comment = frame.text[0] if frame.text else ""
                    break

            # Extrai hashtags
            tags = re.findall(r'#\w+', raw_comment)
            clean_text = re.sub(r'#\w+', '', raw_comment).strip()
            clean_text = re.sub(r'\s+', ' ', clean_text)

            return {
                "sucesso": True,
                "filepath": str(path),
                "raw_comment": raw_comment,
                "free_text": clean_text,
                "tags": tags
            }
        except Exception as e:
            return {"sucesso": False, "erro": str(e)}

    @staticmethod
    def update_tags(filepath: str, tags_to_add: List[str] = None, tags_to_remove: List[str] = None, replace_all: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Adiciona, remove ou substitui tags #Tag no comentário do arquivo,
        preservando anotações livres pré-existentes do DJ.
        """
        path = Path(filepath).resolve()
        if not path.is_file():
            return {"sucesso": False, "erro": "Arquivo não encontrado"}

        parsed = SmartTagManager.parse_comments(str(path))
        if not parsed.get("sucesso"):
            return parsed

        free_text = parsed.get("free_text", "")
        current_tags = set(parsed.get("tags", []))

        if replace_all is not None:
            new_tags = set(t if t.startswith("#") else f"#{t}" for t in replace_all if t.strip())
        else:
            new_tags = set(current_tags)
            if tags_to_add:
                for t in tags_to_add:
                    clean = t.strip()
                    if clean:
                        new_tags.add(clean if clean.startswith("#") else f"#{clean}")
            if tags_to_remove:
                for t in tags_to_remove:
                    clean = t.strip()
                    tag_norm = clean if clean.startswith("#") else f"#{clean}"
                    new_tags.discard(tag_norm)

        # Monta novo comentário mantendo texto livre
        sorted_tags = " ".join(sorted(new_tags))
        new_comment = f"{free_text} {sorted_tags}".strip() if free_text else sorted_tags

        try:
            import shutil
            import uuid
            from journal import record_id3_before_change, record_operation_after

            tmp_path = path.with_name(f".tmp_st_{path.name}_{uuid.uuid4().hex[:8]}")
            try:
                shutil.copy2(str(path), str(tmp_path))
                try:
                    audio = ID3(str(tmp_path))
                except Exception:
                    audio = ID3()

                audio["COMM"] = COMM(encoding=3, lang="eng", desc="", text=new_comment)
                audio.save(str(tmp_path), v2_version=3)

                op_id = record_id3_before_change(str(path), action="smart_tags")
                os.replace(str(tmp_path), str(path))
                record_operation_after(op_id, str(path))
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass

            return {
                "sucesso": True,
                "filepath": str(path),
                "new_comment": new_comment,
                "tags": sorted(list(new_tags))
            }
        except Exception as e:
            return {"sucesso": False, "erro": f"Falha ao salvar tags no arquivo: {e}"}


def main():
    parser = argparse.ArgumentParser(description="Smart Tags / MyTags Manager")
    parser.add_argument("--read", type=str, help="Lê tags do arquivo")
    parser.add_argument("--add", nargs="+", help="Tags para adicionar (ex: #PeakTime #Vocal)")
    parser.add_argument("--remove", nargs="+", help="Tags para remover")
    parser.add_argument("--file", type=str, help="Arquivo a ser modificado")
    parser.add_argument("--categories", action="store_true", help="Lista categorias padrão de MyTags")

    args = parser.parse_args()

    if args.categories:
        print(json.dumps(DEFAULT_CATEGORIES, ensure_ascii=False))
        return

    if args.read:
        print(json.dumps(SmartTagManager.parse_comments(args.read), ensure_ascii=False))
        return

    if args.file and (args.add or args.remove):
        res = SmartTagManager.update_tags(args.file, tags_to_add=args.add, tags_to_remove=args.remove)
        print(json.dumps(res, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
