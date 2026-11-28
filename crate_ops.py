#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SERATO 5 SYNC MANAGER PRO - CRATE OPERATIONS & PLAYLIST TOOLS (crate_ops.py)
================================================================================
Manipulação binária de arquivos .crate do Serato DJ Pro em _Serato_/Subcrates/
com atomicidade, preservação de cabeçalho vrsn, validação estrutural e backup.

Suporta:
- add_paths_to_crate: Adição de faixas relativas/absolutas
- prefix_crates: Adiciona prefixo no nome da crate ou subcrate
- capitalize_crates: Normaliza nomes de crates em Title Case
- sort_crate_tracks: Ordenação das faixas na crate (A-Z, Z-A, Shuffle)
- merge_crates: Fusão de múltiplas crates sem duplicatas
- rewrite_crate_order: Reordenação manual persistida na crate
================================================================================
"""

import os
import sys
import json
import uuid
import random
import shutil
import struct
import hashlib
import argparse
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

sys.dont_write_bytecode = True

_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from serato_macos_app import (
    parse_crate_binary, parse_neworder_pref, criar_tag_tlv, ler_faixas_crate_binaria, normalizar_nfc,
)


def library_root_for(serato_dir):
    """Resolve de forma unificada a raiz relativa usada pelo Serato para faixas."""
    p = Path(os.path.expanduser(str(serato_dir))).resolve()
    if str(p).startswith("/Volumes/"):
        return p.parent
    try:
        home = Path.home().resolve()
        if p == home or p.is_relative_to(home):
            return home
    except Exception:
        pass
    return p.parent


def get_crate_path(subcrates_dir: Path, crate_name: str) -> Path:
    """Retorna o caminho seguro para o arquivo .crate em Subcrates."""
    safe = crate_name.replace('/', '%%').replace('\\', '%%')
    if not safe.endswith('.crate'):
        safe += '.crate'
    return subcrates_dir / safe


def calc_crate_sha256(filepath: Path) -> str:
    """Calcula o hash SHA-256 de um arquivo de crate."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def read_and_validate_crate_full(crate_path: Path) -> Tuple[bytes, List[str], List[Tuple[str, bytes]], List[bytes]]:
    """
    Lê e valida estruturalmente um arquivo binário .crate existente,
    retornando também os blocos 'otrk' originais completos para preservação de sub-blocos.
    """
    if not crate_path.exists():
        raise FileNotFoundError(f"Crate não encontrada: {crate_path.name}")
    try:
        data = crate_path.read_bytes()
    except Exception as e:
        raise IOError(f"Falha de I/O ao ler crate [{crate_path.name}]: {e}")

    if len(data) == 0:
        raise ValueError(f"Crate corrompida: arquivo vazio (0 bytes) [{crate_path.name}]")

    header, tracks, blocos_otrk, outros_blocos = parse_crate_binary(data, strict=True)
    if header is None:
        raise ValueError(f"Crate corrompida ou estrutura inválida (vrsn ausente/inválido) [{crate_path.name}]")

    return header, tracks, blocos_otrk, outros_blocos


def read_and_validate_crate(crate_path: Path) -> Tuple[bytes, List[str], List[bytes]]:
    """
    Lê e valida estruturalmente um arquivo binário .crate existente.
    Nunca interpreta falha de leitura como crate vazia.
    Lança ValueError ou IOError se a crate estiver corrompida, truncada ou ilegível.
    """
    if not crate_path.exists():
        raise FileNotFoundError(f"Crate não encontrada: {crate_path.name}")
    try:
        data = crate_path.read_bytes()
    except Exception as e:
        raise IOError(f"Falha de I/O ao ler crate [{crate_path.name}]: {e}")

    if len(data) == 0:
        raise ValueError(f"Crate corrompida: arquivo vazio (0 bytes) [{crate_path.name}]")

    header, tracks, _, outros_blocos = parse_crate_binary(data)
    if header is None:
        raise ValueError(f"Crate corrompida ou estrutura inválida (vrsn ausente/inválido) [{crate_path.name}]")

    return header, tracks, outros_blocos


def _build_otrk_preserving_subblocks(rel: str, raw_otrk_block: Optional[bytes] = None) -> bytes:
    """
    Constrói um bloco 'otrk' para a faixa `rel` preservando integralmente quaisquer
    sub-blocos adicionais (além de 'ptrk') presentes no bloco `otrk` original.
    """
    if not raw_otrk_block or len(raw_otrk_block) < 8 or raw_otrk_block[:4] != b'otrk':
        ptrk = criar_tag_tlv('ptrk', rel)
        return b'otrk' + struct.pack('>I', len(ptrk)) + ptrk

    try:
        otrk_len = struct.unpack('>I', raw_otrk_block[4:8])[0]
        if 8 + otrk_len != len(raw_otrk_block):
            ptrk = criar_tag_tlv('ptrk', rel)
            return b'otrk' + struct.pack('>I', len(ptrk)) + ptrk

        payload = raw_otrk_block[8:]
        expected_ptrk_bytes = rel.encode('utf-16-be')
        p_idx = 0
        rebuilt_parts = []
        replaced_ptrk = False

        while p_idx < len(payload):
            if p_idx + 8 > len(payload):
                ptrk = criar_tag_tlv('ptrk', rel)
                return b'otrk' + struct.pack('>I', len(ptrk)) + ptrk
            p_tag = payload[p_idx:p_idx+4]
            p_len = struct.unpack('>I', payload[p_idx+4:p_idx+8])[0]
            p_end = p_idx + 8 + p_len
            if p_end > len(payload):
                ptrk = criar_tag_tlv('ptrk', rel)
                return b'otrk' + struct.pack('>I', len(ptrk)) + ptrk
            sub_raw = payload[p_idx:p_end]
            if p_tag == b'ptrk' and not replaced_ptrk:
                if payload[p_idx+8:p_end] == expected_ptrk_bytes and len(rebuilt_parts) == 0 and p_end == len(payload):
                    return raw_otrk_block
                if payload[p_idx+8:p_end] == expected_ptrk_bytes:
                    rebuilt_parts.append(sub_raw)
                else:
                    rebuilt_parts.append(criar_tag_tlv('ptrk', rel))
                replaced_ptrk = True
            else:
                rebuilt_parts.append(sub_raw)
            p_idx = p_end

        if not replaced_ptrk:
            rebuilt_parts.insert(0, criar_tag_tlv('ptrk', rel))

        new_payload = b''.join(rebuilt_parts)
        return b'otrk' + struct.pack('>I', len(new_payload)) + new_payload
    except Exception:
        ptrk = criar_tag_tlv('ptrk', rel)
        return b'otrk' + struct.pack('>I', len(ptrk)) + ptrk


def restore_crate_from_backup_atomic(crate_path: Path, backup_path: Path, expected_hash: Optional[str] = None) -> Tuple[bool, str]:
    """
    Restaura uma crate a partir de seu backup com validação SHA-256 pré e pós-restauração
    e substituição atômica via arquivo temporário + fsync + os.replace.
    Preserva sempre o arquivo de backup original.
    """
    crate_path = Path(crate_path)
    backup_path = Path(backup_path)

    if not backup_path.exists():
        return (
            False,
            f"ALERTA CRÍTICO: Backup não encontrado em [{backup_path}]. Recuperação manual necessária."
        )

    try:
        if backup_path.stat().st_size < 16:
            return (
                False,
                f"ALERTA CRÍTICO: Backup [{backup_path.name}] está vazio ou truncado. Recuperação manual necessária."
            )

        bak_hash = calc_crate_sha256(backup_path)
        if expected_hash and bak_hash != expected_hash:
            return (
                False,
                f"ALERTA CRÍTICO: SHA-256 do backup [{backup_path.name}] diverge do original ({bak_hash} != {expected_hash}). Recuperação manual necessária."
            )

        bak_bytes = backup_path.read_bytes()
        val_header, _, _, _ = parse_crate_binary(bak_bytes)
        if val_header is None:
            return (
                False,
                f"ALERTA CRÍTICO: Estrutura binária do backup [{backup_path.name}] é inválida. Recuperação manual necessária."
            )
    except Exception as e_pre:
        return (
            False,
            f"ALERTA CRÍTICO: Falha ao validar backup [{backup_path.name}] antes da restauração: {e_pre}. Recuperação manual necessária."
        )

    tmp_rb = crate_path.with_name(f".tmp_rb_{crate_path.name}_{uuid.uuid4().hex[:8]}")
    try:
        with open(backup_path, 'rb') as src, open(tmp_rb, 'wb') as dst:
            shutil.copyfileobj(src, dst, 65536)
            dst.flush()
            os.fsync(dst.fileno())

        if not tmp_rb.exists() or calc_crate_sha256(tmp_rb) != bak_hash:
            raise IOError("Hash SHA-256 do arquivo temporário de restauração diverge do backup.")

        os.replace(tmp_rb, crate_path)

        if not crate_path.exists():
            raise IOError("Arquivo restaurado ausente após substituição atômica.")

        restored_hash = calc_crate_sha256(crate_path)
        if restored_hash != bak_hash or (expected_hash and restored_hash != expected_hash):
            raise IOError("SHA-256 do arquivo restaurado diverge do backup após substituição.")

        restored_header, _, _, _ = parse_crate_binary(crate_path.read_bytes())
        if restored_header is None:
            raise IOError("Estrutura binária do arquivo restaurado inválida após substituição.")

        return (
            True,
            f"Rollback atômico confirmado (SHA-256 verificado; backup preservado em {backup_path.name})."
        )
    except Exception as e_rb:
        if tmp_rb.exists():
            try:
                tmp_rb.unlink()
            except Exception:
                pass
        return (
            False,
            f"ALERTA CRÍTICO: Falha no rollback atômico de [{crate_path.name}]: {e_rb}. "
            f"Recuperação manual necessária usando o backup preservado em: {backup_path}"
        )


def write_crate_atomic(crate_path: Path, track_rel_list: List[str],
                       header_antigo: Optional[bytes] = None,
                       outros_blocos: Optional[List[bytes]] = None,
                       action_name: str = "write_crate",
                       track_blocks: Optional[List[Tuple[str, bytes]]] = None) -> Dict[str, Any]:
    """
    Grava uma lista de caminhos relativos em arquivo binário .crate com substituição
    atômica (UUID temp), fsync, backup validado por SHA-256, journal e rollback automático,
    preservando blocos desconhecidos no nível raiz e sub-blocos internos de 'otrk'.
    """
    crate_path.parent.mkdir(parents=True, exist_ok=True)
    crate_ja_existia = crate_path.exists()
    bak = crate_path.with_suffix('.bak')
    versioned_bak = None
    orig_hash = None
    otrk_check: List[Tuple[str, bytes]] = []

    if crate_ja_existia:
        # 1. Valida se a crate original é íntegra antes de qualquer alteração
        try:
            orig_data = crate_path.read_bytes()
            if len(orig_data) == 0:
                return {
                    "sucesso": False,
                    "erro": f"Crate original [{crate_path.name}] está vazia (0 bytes / inválida). Substituição silenciosa cancelada."
                }
            h_check, _, otrk_check, ob_check = parse_crate_binary(orig_data)
            if h_check is None:
                return {
                    "sucesso": False,
                    "erro": f"Crate original [{crate_path.name}] está corrompida ou ilegível. Gravação cancelada para evitar perda de dados."
                }
            if header_antigo is None:
                header_antigo = h_check
            if outros_blocos is None:
                outros_blocos = ob_check
        except Exception as e_check:
            return {
                "sucesso": False,
                "erro": f"Falha ao validar crate original [{crate_path.name}]: {e_check}"
            }

        # 2. Cria backup com validação de hash SHA-256
        try:
            orig_hash = calc_crate_sha256(crate_path)
            shutil.copy2(crate_path, bak)
            bak_hash = calc_crate_sha256(bak)
            if bak_hash != orig_hash:
                if bak.exists():
                    bak.unlink()
                return {
                    "sucesso": False,
                    "erro": "Falha na validação de integridade do backup (.bak) por SHA-256."
                }
            # Backup versionado com timestamp para preservação histórica
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            versioned_bak = crate_path.with_name(f"{crate_path.name}.bak_{stamp}")
            shutil.copy2(bak, versioned_bak)
        except Exception as e_bak:
            return {
                "sucesso": False,
                "erro": f"Impossível criar backup seguro da crate antes da alteração: {e_bak}"
            }

    # Monta mapa de preservação de blocos 'otrk' originais por caminho normalizado
    otrk_map: Dict[str, deque] = {}
    for src_blocks in (track_blocks or [], otrk_check):
        for b_path, b_raw in src_blocks:
            norm_k = normalizar_nfc(b_path)
            if norm_k not in otrk_map:
                otrk_map[norm_k] = deque([b_raw])
            elif b_raw not in otrk_map[norm_k]:
                otrk_map[norm_k].append(b_raw)

    outros_blocos = outros_blocos or []
    tmp = crate_path.with_name(f".tmp_{crate_path.name}_{uuid.uuid4().hex[:8]}")

    try:
        with open(tmp, 'wb') as f:
            f.write(header_antigo if header_antigo and len(header_antigo) >= 8
                    else b'vrsn\x00\x00\x00\x08\x001\x00.\x000\x000')
            for b in outros_blocos:
                f.write(b)
            for rel in track_rel_list:
                norm_rel = normalizar_nfc(rel)
                raw_otrk = None
                if norm_rel in otrk_map and otrk_map[norm_rel]:
                    raw_otrk = otrk_map[norm_rel].popleft()
                f.write(_build_otrk_preserving_subblocks(rel, raw_otrk))
            f.flush()
            os.fsync(f.fileno())

        # 3. Validação estrutural do temporário
        if not tmp.exists() or tmp.stat().st_size < 16:
            raise IOError("Arquivo temporário da crate incompleto ou vazio.")

        tmp_bytes = tmp.read_bytes()
        val_header, val_tracks, _, _ = parse_crate_binary(tmp_bytes)
        if val_header is None:
            raise IOError("Estrutura da crate no arquivo temporário é inválida (vrsn ausente ou corrompido).")

        if len(val_tracks) != len(track_rel_list):
            raise IOError(f"Divergência estrutural de faixas ({len(val_tracks)} vs {len(track_rel_list)} esperadas).")

        # 4. Substituição atômica
        os.replace(tmp, crate_path)

        # 5. Validação pós-gravação
        post_bytes = crate_path.read_bytes()
        post_header, post_tracks, _, _ = parse_crate_binary(post_bytes)
        if post_header is None or len(post_tracks) != len(track_rel_list):
            raise IOError("Falha na validação pós-escrita do arquivo definitivo.")

        post_hash = calc_crate_sha256(crate_path)

        # 6. Registro obrigatório no Journal
        try:
            import journal
            journal.record_crate_operation(
                crate_path=str(crate_path),
                acao=action_name,
                hash_anterior=orig_hash,
                hash_posterior=post_hash,
                backup_path=str(versioned_bak or bak) if crate_ja_existia else None,
                total_tracks=len(track_rel_list)
            )
        except Exception as e_journal:
            raise IOError(f"Falha ao registrar operação no Journal: {e_journal}")

    except Exception as e:
        # Rollback automático restaurando backup se existia, ou removendo arquivo recém-criado
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        rollback_ok = False
        rollback_msg = "Rollback não aplicável."
        if crate_ja_existia and bak.exists():
            rollback_ok, rollback_msg = restore_crate_from_backup_atomic(
                crate_path, bak, expected_hash=orig_hash
            )
        elif crate_ja_existia and not bak.exists():
            rollback_ok = False
            rollback_msg = (
                f"ALERTA CRÍTICO: Backup [{bak}] ausente para rollback de [{crate_path.name}]. "
                "Recuperação manual necessária."
            )
        elif not crate_ja_existia:
            if crate_path.exists():
                try:
                    crate_path.unlink()
                    rollback_ok = True
                    rollback_msg = "Rollback executado: arquivo recém-criado removido."
                except Exception as e_rm:
                    rollback_ok = False
                    rollback_msg = (
                        f"ALERTA CRÍTICO: Falha ao remover crate recém-criada [{crate_path.name}] "
                        f"({e_rm}). Recuperação manual necessária."
                    )
            else:
                rollback_ok = True
                rollback_msg = "Rollback não necessário: arquivo destino não havia sido criado."
        return {
            "sucesso": False,
            "rollback_confirmado": rollback_ok,
            "backup": str(bak) if crate_ja_existia else None,
            "erro": f"Falha na gravação/validação da crate [{crate_path.name}]: {e}. {rollback_msg}"
        }

    return {
        "sucesso": True,
        "crate": crate_path.name,
        "caminho": str(crate_path),
        "backup": str(bak) if crate_ja_existia else None,
        "backup_versionado": str(versioned_bak) if crate_ja_existia and versioned_bak else None,
        "hash_anterior": orig_hash,
        "sobrescrita": crate_ja_existia,
        "hash": post_hash,
        "total": len(track_rel_list)
    }


def add_paths_to_crate(serato_dir: str, crate_name: str, abs_paths: List[str]) -> Dict[str, Any]:
    """Adiciona faixas (caminhos absolutos) a uma crate mantendo faixas existentes com validação estrita."""
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    crate_path = get_crate_path(subcrates, crate_name)
    root = library_root_for(serato)

    relativos = []
    rejeitados = []
    for raw in abs_paths:
        p = Path(os.path.expanduser(str(raw)))
        try:
            rel = str(p.resolve().relative_to(root.resolve()))
        except ValueError:
            rejeitados.append({"arquivo": str(raw), "motivo": f"fora da raiz da biblioteca ({root})"})
            continue
        if not p.exists():
            rejeitados.append({"arquivo": str(raw), "motivo": "arquivo não encontrado"})
            continue
        relativos.append(normalizar_nfc(rel))

    if not relativos:
        return {"sucesso": False, "erro": "Nenhum caminho válido dentro da raiz da biblioteca",
                "raiz": str(root), "rejeitados": rejeitados}

    header_antigo = None
    existentes = []
    outros_blocos = []

    if crate_path.exists():
        try:
            header_antigo, existentes, outros_blocos = read_and_validate_crate(crate_path)
        except Exception as e_crate:
            return {
                "sucesso": False,
                "erro": f"Operação interrompida: crate de destino [{crate_name}] existe mas é inválida ou ilegível: {e_crate}",
                "rejeitados": rejeitados
            }

    final = list(existentes)
    adicionados = 0
    for rel in relativos:
        if rel not in final:
            final.append(rel)
            adicionados += 1

    res = write_crate_atomic(crate_path, final, header_antigo, outros_blocos, action_name="add_paths")
    if not res["sucesso"]:
        return res

    res.update({
        "adicionados": adicionados,
        "raiz": str(root),
        "rejeitados": rejeitados,
        "mensagem": f"{adicionados} faixa(s) adicionada(s) à crate [{crate_path.stem}] ({len(final)} no total)."
    })
    return res


def _resolve_target_crate_paths(subcrates: Path, crate_name: str, target: str = "subcrate") -> List[Path]:
    """
    Resolve os arquivos .crate alvo de uma operação.
    Quando target='master' (ou quando o nome informado representa um grupo Master sem arquivo .crate isolado),
    inclui <master>.crate (se existir) e todas as subcrates <master>%%*.crate.
    """
    direct = get_crate_path(subcrates, crate_name)
    clean = direct.stem
    if target == "master" or (not direct.exists() and "%%" not in clean):
        matches: List[Path] = []
        if direct.exists():
            matches.append(direct)
        prefix_pattern = f"{clean}%%*.crate"
        for sub_path in sorted(subcrates.glob(prefix_pattern)):
            if sub_path.is_file() and not sub_path.name.startswith("._") and sub_path not in matches:
                matches.append(sub_path)
        return matches
    return [direct] if direct.exists() else []


def sort_crate_tracks(serato_dir: str, crate_name: str, sort_mode: str = "az", target: str = "subcrate") -> Dict[str, Any]:
    """
    Ordena as faixas dentro de uma crate (ou grupo Master) e reescreve o binário com validação integral.
    sort_mode: 'az' (A-Z pelo nome do arquivo), 'za' (Z-A), 'shuffle' (aleatório).
    """
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    crate_paths = _resolve_target_crate_paths(subcrates, crate_name, target=target)

    if not crate_paths:
        return {"sucesso": False, "erro": f"Crate não encontrada: {crate_name}"}

    if sort_mode not in ("az", "za", "shuffle", "path"):
        return {"sucesso": False, "erro": f"Modo de ordenação inválido: {sort_mode}"}

    updated_crates = 0
    total_tracks_sorted = 0
    for crate_path in crate_paths:
        try:
            header_antigo, existentes, outros_blocos = read_and_validate_crate(crate_path)
        except Exception as e:
            return {"sucesso": False, "erro": f"Erro ao ler crate [{crate_path.stem}]: {e}"}

        if not existentes:
            continue

        sorted_tracks = list(existentes)
        if sort_mode == "az":
            sorted_tracks.sort(key=lambda p: Path(p).name.lower())
        elif sort_mode == "za":
            sorted_tracks.sort(key=lambda p: Path(p).name.lower(), reverse=True)
        elif sort_mode == "shuffle":
            random.shuffle(sorted_tracks)
        elif sort_mode == "path":
            sorted_tracks.sort(key=lambda p: p.lower())

        res = write_crate_atomic(crate_path, sorted_tracks, header_antigo, outros_blocos, action_name=f"sort_{sort_mode}")
        if not res.get("sucesso"):
            return res
        updated_crates += 1
        total_tracks_sorted += len(sorted_tracks)

    if updated_crates == 0:
        return {"sucesso": True, "crate": crate_name, "total": 0, "mensagem": "Crate vazia."}

    return {
        "sucesso": True,
        "crate": crate_name,
        "crates_atualizadas": updated_crates,
        "total": total_tracks_sorted,
        "mensagem": f"Crate [{crate_name}] reordenada com sucesso ({sort_mode.upper()} - {total_tracks_sorted} faixas em {updated_crates} crate(s)).",
    }


def _update_neworder_pref_crate_name(serato: Path, old_clean_name: str, new_clean_name: str) -> None:
    """Atualiza o nome da crate em neworder.pref preservando integralmente o formato binário TLV."""
    pref_path = serato / "neworder.pref"
    if not pref_path.exists():
        return
    try:
        raw = pref_path.read_bytes()
        header, ordered_crates, outros_blocos = parse_neworder_pref(raw, strict=True)
        if header is None:
            return

        old_nfc = normalizar_nfc(old_clean_name)
        new_nfc = normalizar_nfc(new_clean_name)

        updated_crates: List[str] = []
        changed = False
        for name in ordered_crates:
            norm_name = normalizar_nfc(name)
            if norm_name == old_nfc:
                candidate = new_nfc
                changed = True
            else:
                candidate = norm_name
            if candidate and candidate not in updated_crates:
                updated_crates.append(candidate)

        if not changed:
            return

        blocos_nior = []
        for item in updated_crates:
            nior = criar_tag_tlv('tvcn', normalizar_nfc(item))
            blocos_nior.append(b'nior' + struct.pack('>I', len(nior)) + nior)

        new_bytes = header + b''.join(outros_blocos) + b''.join(blocos_nior)
        tmp_pref = pref_path.with_name(f".tmp_neworder_{uuid.uuid4().hex[:8]}")
        try:
            with open(tmp_pref, 'wb') as f:
                f.write(new_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp_pref), str(pref_path))
        finally:
            if tmp_pref.exists():
                try:
                    tmp_pref.unlink()
                except Exception:
                    pass
    except Exception:
        pass


def prefix_crate(serato_dir: str, crate_name: str, prefix: str, target: str = "subcrate") -> Dict[str, Any]:
    """
    Adiciona um prefixo no nome da crate ou subcrate (ou em todo o grupo Master).
    Ex: 'Sertanejo%%41' com prefixo '01. ' e target='subcrate' -> 'Sertanejo%%01. 41.crate'.
    """
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    crate_paths = _resolve_target_crate_paths(subcrates, crate_name, target=target)

    if not crate_paths:
        return {"sucesso": False, "erro": f"Crate original não encontrada: {crate_name}"}

    # Planeja todos os novos nomes e valida colisões antes de mover qualquer arquivo
    rename_plan = []
    for old_crate_path in crate_paths:
        clean_name = old_crate_path.stem
        parts = clean_name.split('%%')
        if target == "master" or len(parts) == 1:
            parts[0] = f"{prefix.strip()} {parts[0]}".strip()
        else:
            parts[-1] = f"{prefix.strip()} {parts[-1]}".strip()
        new_clean_name = '%%'.join(parts)
        new_crate_path = subcrates / f"{new_clean_name}.crate"
        if new_crate_path.exists() and not (
            new_crate_path == old_crate_path
            or (old_crate_path.exists() and os.path.samefile(new_crate_path, old_crate_path))
        ):
            return {"sucesso": False, "erro": f"Já existe uma crate com o nome de destino: {new_clean_name}"}
        rename_plan.append((old_crate_path, clean_name, new_crate_path, new_clean_name))

    last_old, last_new, last_path = "", "", ""
    try:
        for old_crate_path, clean_name, new_crate_path, new_clean_name in rename_plan:
            orig_hash = calc_crate_sha256(old_crate_path)
            bak = old_crate_path.with_suffix('.bak')
            shutil.copy2(old_crate_path, bak)
            if calc_crate_sha256(bak) != orig_hash:
                return {"sucesso": False, "erro": f"Falha ao validar backup SHA-256 antes de renomear {clean_name}."}
            _, tracks_cur, _ = read_and_validate_crate(old_crate_path)
            shutil.move(old_crate_path, new_crate_path)
            _update_neworder_pref_crate_name(serato, clean_name, new_clean_name)
            try:
                import journal
                journal.record_crate_operation(
                    crate_path=str(new_crate_path),
                    acao="prefix_crate",
                    hash_anterior=orig_hash,
                    hash_posterior=calc_crate_sha256(new_crate_path),
                    backup_path=str(bak),
                    total_tracks=len(tracks_cur),
                )
            except Exception:
                pass
            last_old, last_new, last_path = clean_name, new_clean_name, str(new_crate_path)
    except Exception as e:
        return {"sucesso": False, "erro": f"Falha ao renomear crate: {e}"}

    msg = (
        f"Grupo Master [{crate_name}] prefixado em {len(rename_plan)} crate(s)."
        if len(rename_plan) > 1
        else f"Crate renomeada de [{last_old}] para [{last_new}]."
    )
    return {
        "sucesso": True,
        "old_name": last_old,
        "new_name": last_new,
        "caminho": last_path,
        "crates_atualizadas": len(rename_plan),
        "mensagem": msg,
    }


def capitalize_crate(serato_dir: str, crate_name: str, target: str = "subcrate") -> Dict[str, Any]:
    """Capitaliza (Title Case) as partes do nome da crate (ou grupo Master) e renomeia o(s) arquivo(s)."""
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    crate_paths = _resolve_target_crate_paths(subcrates, crate_name, target=target)

    if not crate_paths:
        return {"sucesso": False, "erro": f"Crate não encontrada: {crate_name}"}

    rename_plan = []
    for old_crate_path in crate_paths:
        clean_name = old_crate_path.stem
        parts = clean_name.split('%%')
        if target == "master" and len(parts) > 1:
            parts[0] = parts[0].strip().title()
            new_clean_name = '%%'.join(parts)
        else:
            new_clean_name = '%%'.join(p.strip().title() for p in parts)
        if new_clean_name == clean_name:
            continue
        new_crate_path = subcrates / f"{new_clean_name}.crate"
        if new_crate_path.exists() and not (
            new_crate_path == old_crate_path
            or (old_crate_path.exists() and os.path.samefile(new_crate_path, old_crate_path))
        ):
            return {"sucesso": False, "erro": f"Já existe uma crate com o nome: {new_clean_name}"}
        rename_plan.append((old_crate_path, clean_name, new_crate_path, new_clean_name))

    if not rename_plan:
        return {"sucesso": True, "old_name": crate_name, "new_name": crate_name, "mensagem": "Nome já estava capitalizado."}

    last_old, last_new = "", ""
    try:
        for old_crate_path, clean_name, new_crate_path, new_clean_name in rename_plan:
            orig_hash = calc_crate_sha256(old_crate_path)
            bak = old_crate_path.with_suffix('.bak')
            shutil.copy2(old_crate_path, bak)
            if calc_crate_sha256(bak) != orig_hash:
                return {"sucesso": False, "erro": f"Falha ao validar backup SHA-256 antes de capitalizar {clean_name}."}
            _, tracks_cur, _ = read_and_validate_crate(old_crate_path)
            shutil.move(old_crate_path, new_crate_path)
            _update_neworder_pref_crate_name(serato, clean_name, new_clean_name)
            try:
                import journal
                journal.record_crate_operation(
                    crate_path=str(new_crate_path),
                    acao="capitalize_crate",
                    hash_anterior=orig_hash,
                    hash_posterior=calc_crate_sha256(new_crate_path),
                    backup_path=str(bak),
                    total_tracks=len(tracks_cur),
                )
            except Exception:
                pass
            last_old, last_new = clean_name, new_clean_name
    except Exception as e:
        return {"sucesso": False, "erro": f"Falha ao capitalizar crate: {e}"}

    msg = (
        f"Grupo Master [{crate_name}] capitalizado em {len(rename_plan)} crate(s)."
        if len(rename_plan) > 1
        else f"Crate [{last_old}] capitalizada para [{last_new}]."
    )
    return {
        "sucesso": True,
        "old_name": last_old,
        "new_name": last_new,
        "crates_atualizadas": len(rename_plan),
        "mensagem": msg,
    }


def merge_crates(serato_dir: str, source_crates: List[str], target_crate: str) -> Dict[str, Any]:
    """
    Funde múltiplas crates de origem em uma crate de destino sem duplicatas.
    Interrompe a operação imediatamente se QUALQUER crate de origem ou de destino
    for ilegível ou inválida, garantindo que não ocorram omissões silenciosas.
    """
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    target_path = get_crate_path(subcrates, target_crate)

    if not source_crates:
        return {"sucesso": False, "erro": "Nenhuma crate de origem informada para fusão."}

    all_tracks = []
    collected_otrk_blocks: List[Tuple[str, bytes]] = []
    header_antigo = None
    outros_blocos = []

    # 1. Lê faixas já existentes na target (se houver). Se target for ilegível, aborta!
    if target_path.exists():
        try:
            header_antigo, existentes, tgt_otrk, outros_blocos = read_and_validate_crate_full(target_path)
            all_tracks.extend(existentes)
            collected_otrk_blocks.extend(tgt_otrk)
        except Exception as e_tgt:
            return {
                "sucesso": False,
                "erro": f"Operação de fusão cancelada: crate de destino [{target_crate}] está corrompida ou ilegível ({e_tgt}). Nenhuma alteração realizada."
            }

    # 2. Lê faixas de CADA source_crate. Se QUALQUER uma falhar, aborta a operação inteira!
    for sc_name in source_crates:
        sc_path = get_crate_path(subcrates, sc_name)
        try:
            _, sc_tracks, sc_otrk, _ = read_and_validate_crate_full(sc_path)
        except Exception as e_sc:
            return {
                "sucesso": False,
                "erro": f"Operação de fusão cancelada: crate de origem [{sc_name}] não pôde ser interpretada ({e_sc}). Nenhuma alteração foi realizada."
            }
        otrk_by_sc_track = {normalizar_nfc(p): b for p, b in sc_otrk}
        for t in sc_tracks:
            if t not in all_tracks:
                all_tracks.append(t)
                norm_t = normalizar_nfc(t)
                if norm_t in otrk_by_sc_track:
                    collected_otrk_blocks.append((norm_t, otrk_by_sc_track[norm_t]))

    res = write_crate_atomic(
        target_path,
        all_tracks,
        header_antigo,
        outros_blocos,
        action_name="merge_crates",
        track_blocks=collected_otrk_blocks,
    )
    if res["sucesso"]:
        res["mensagem"] = f"{len(source_crates)} crate(s) fundida(s) em [{target_crate}] com sucesso ({len(all_tracks)} faixas)."
    return res


def rewrite_crate_order(serato_dir: str, crate_name: str, ordered_tracks: List[str]) -> Dict[str, Any]:
    """Reescreve a ordem das faixas na crate com validação estrutural prévia e posterior."""
    serato = Path(os.path.expanduser(str(serato_dir))).resolve()
    subcrates = serato / "Subcrates"
    crate_path = get_crate_path(subcrates, crate_name)

    header_antigo = None
    outros_blocos = []
    if crate_path.exists():
        try:
            header_antigo, _, outros_blocos = read_and_validate_crate(crate_path)
        except Exception as e_order:
            return {
                "sucesso": False,
                "erro": f"Operação cancelada: crate [{crate_name}] está ilegível ou corrompida ({e_order})."
            }

    clean_tracks = [normalizar_nfc(t) for t in ordered_tracks if t]
    res = write_crate_atomic(crate_path, clean_tracks, header_antigo, outros_blocos, action_name="rewrite_order")
    if res["sucesso"]:
        res["mensagem"] = f"Ordem manual da crate [{crate_name}] persistida com sucesso ({len(clean_tracks)} faixas)."
    return res


def list_crates_tree(serato_dir: str) -> Dict[str, Any]:
    """Varre todas as crates de Subcrates e retorna o mapa completo no formato crates_arvore."""
    s_path = Path(os.path.expanduser(serato_dir)).resolve()
    subcrates_dir = s_path / "Subcrates" if (s_path / "Subcrates").exists() else s_path
    if not subcrates_dir.exists():
        return {"sucesso": False, "erro": f"Pasta Subcrates não encontrada em: {serato_dir}", "crates_arvore": {}}

    tree = {}
    corrupt_crates = []
    total_tracks = 0

    for f in sorted(subcrates_dir.glob("*.crate")):
        if f.name.startswith("._") or f.name.startswith("."):
            continue
        crate_name = f.stem
        try:
            _, tracks, _ = read_and_validate_crate(f)
        except Exception as e_crate:
            corrupt_crates.append({"crate": f.name, "erro": str(e_crate)})
            continue

        parts = crate_name.split("%%")
        master = parts[0]
        subcrate = " -> ".join(parts[1:]) if len(parts) > 1 else ""
        nome_exibicao = " -> ".join(parts)

        faixas_lista = []
        for t in tracks:
            total_tracks += 1
            filename = t.split('/')[-1] if '/' in t else t.split('\\')[-1]
            ext = Path(filename).suffix.upper().replace('.', '') or "MP3"
            faixas_lista.append({
                "nome": filename,
                "caminho_rel": t,
                "formato": ext
            })

        tree[crate_name] = {
            "nome_crate": crate_name,
            "nome_exibicao": nome_exibicao,
            "master": master,
            "subcrate": subcrate,
            "total_faixas": len(faixas_lista),
            "faixas": faixas_lista
        }

    return {
        "sucesso": True,
        "total_crates": len(tree),
        "total_faixas": total_tracks,
        "crates_arvore": tree,
        "crates_corrompidas": corrupt_crates,
    }


def main():
    parser = argparse.ArgumentParser(description="Serato Crate Operations & Playlist Tools")
    parser.add_argument("--action", type=str, default="add_paths",
                        choices=["add_paths", "sort", "prefix", "capitalize", "merge", "rewrite_order", "list_tree"],
                        help="Ação a executar na crate")
    parser.add_argument("--serato", required=True, help="Diretório _Serato_")
    parser.add_argument("--crate", default="", help="Nome da crate")
    parser.add_argument("--paths", nargs="*", default=[], help="Caminhos para add_paths ou rewrite_order")
    parser.add_argument("--paths-file", type=str, default="", help="Arquivo contendo lista de caminhos em JSON")
    parser.add_argument("--sources", nargs="*", default=[], help="Crates de origem para merge")
    parser.add_argument("--prefix", type=str, default="", help="Prefixo a adicionar")
    parser.add_argument("--sort-mode", type=str, default="az", choices=["az", "za", "shuffle", "path"])
    parser.add_argument("--target", type=str, default="subcrate", choices=["subcrate", "master"])
    parser.add_argument("--list-tree", action="store_true", help="Lista a árvore completa de crates e faixas")

    args = parser.parse_args()

    paths_list = list(args.paths) if args.paths else []
    if args.paths_file:
        pf = Path(args.paths_file)
        if pf.is_file():
            try:
                with open(pf, 'r', encoding='utf-8') as f:
                    extra = json.load(f)
                    if isinstance(extra, list):
                        paths_list.extend(extra)
            except Exception as e:
                print(json.dumps({"sucesso": False, "erro": f"Falha ao ler --paths-file: {e}"}, ensure_ascii=False))
                return

    if args.list_tree or args.action == "list_tree":
        res = list_crates_tree(args.serato)
    elif args.action == "add_paths":
        res = add_paths_to_crate(args.serato, args.crate, paths_list)
    elif args.action == "sort":
        res = sort_crate_tracks(args.serato, args.crate, args.sort_mode, args.target)
    elif args.action == "prefix":
        res = prefix_crate(args.serato, args.crate, args.prefix, args.target)
    elif args.action == "capitalize":
        res = capitalize_crate(args.serato, args.crate, args.target)
    elif args.action == "merge":
        res = merge_crates(args.serato, args.sources, args.crate)
    elif args.action == "rewrite_order":
        res = rewrite_crate_order(args.serato, args.crate, paths_list)
    else:
        res = {"sucesso": False, "erro": f"Ação desconhecida: {args.action}"}

    print(json.dumps(res, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
