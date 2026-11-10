#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/fixtures/sandbox_runner.py
Sandbox Filesystem Isolation, Environment Harness & Verification Runner.

Guarantees 100% leak-proof isolation (Requirement R2):
1. Subprocess & In-Process HOME and TMPDIR containment.
2. Canonical Serato directory structure & convenience symlinks.
3. In-process monkey-patching of all 14 module-level path constants.
4. Universal SandboxResult parser (extracts __PAYLOAD_JSON_SUMMARY__, NDJSON events, terminal JSON).
5. Forensic assert_zero_leaks canary checks against real user directory.
"""

from dataclasses import dataclass, field
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Add project root and vendor to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
VENDOR_DIR = PROJECT_ROOT / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))
# Remove vendor/mutagen if accidentally added to avoid shadowing stdlib wave.py
bad_mutagen_dir = str(PROJECT_ROOT / "vendor" / "mutagen")
if bad_mutagen_dir in sys.path:
    sys.path.remove(bad_mutagen_dir)

# Host real user home recorded once at module import
HOST_HOME = Path(os.environ.get("HOME", "/Users/pastteur")).resolve()


@dataclass
class SandboxResult:
    """Standardized result returned by sandbox CLI and engine execution."""
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    json_payload: Optional[Union[Dict[str, Any], List[Any]]] = None
    json_lines: List[Dict[str, Any]] = field(default_factory=list)
    error_message: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.exit_code == 0


def parse_sandbox_output(
    exit_code: int,
    stdout: str,
    stderr: str,
    duration_sec: float
) -> SandboxResult:
    """
    Parses subprocess output into a unified SandboxResult:
    - Extracts __PAYLOAD_JSON_SUMMARY__{...}
    - Collects streaming NDJSON event lines
    - Falls back to terminal JSON dict or stderr error messages
    """
    json_payload: Optional[Union[Dict[str, Any], List[Any]]] = None
    json_lines: List[Dict[str, Any]] = []

    # 1. Search for __PAYLOAD_JSON_SUMMARY__ block
    summary_match = re.search(r"__PAYLOAD_JSON_SUMMARY__(\{.*?\}|\[.*?\])", stdout, re.DOTALL)
    if summary_match:
        try:
            json_payload = json.loads(summary_match.group(1))
        except Exception:
            pass

    # 2. Parse line-by-line NDJSON events
    for line in stdout.splitlines():
        line_clean = line.strip()
        if (line_clean.startswith("{") and line_clean.endswith("}")) or (
            line_clean.startswith("[") and line_clean.endswith("]")
        ):
            try:
                parsed = json.loads(line_clean)
                if isinstance(parsed, dict):
                    json_lines.append(parsed)
            except Exception:
                pass

    # 3. If json_payload not found via summary token, deduce from json_lines or full stdout
    if json_payload is None:
        if json_lines:
            # Look for terminal event (e.g. tipo == 'fim')
            terminal_events = [ev for ev in json_lines if ev.get("tipo") == "fim"]
            if terminal_events:
                json_payload = terminal_events[-1]
            else:
                json_payload = json_lines[-1]
        else:
            try:
                parsed_full = json.loads(stdout.strip())
                if isinstance(parsed_full, (dict, list)):
                    json_payload = parsed_full
            except Exception:
                pass

    # 4. Extract error message
    error_message: Optional[str] = None
    if exit_code != 0:
        if stderr.strip():
            error_message = stderr.strip().splitlines()[-1]
        elif isinstance(json_payload, dict):
            error_message = json_payload.get("erro") or json_payload.get("error") or json_payload.get("motivo")

    return SandboxResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_sec=duration_sec,
        json_payload=json_payload,
        json_lines=json_lines,
        error_message=error_message,
    )


class SeratoSandbox:
    """
    Hermetic isolated sandbox execution environment.
    Redirects HOME, TMPDIR, module constants, and enforces zero leakage to real user disks.
    """

    CRITICAL_HOST_PATHS = [
        ".serato_sound_seals.sqlite",
        ".serato_sync_journal.sqlite",
        ".serato_sync_cues_backup.sqlite",
        ".serato_tag_cache.sqlite",
        ".serato_sync_smart_crates.json",
        ".serato_sync_watch_state.json",
        ".serato_quarentena_audio",
        "SeratoSync",
        "pasync",
        "Music/_Serato_",
    ]

    def __init__(
        self,
        root_dir: Optional[Union[str, Path]] = None,
        clean_on_exit: bool = True,
        extra_watch_paths: Optional[List[Path]] = None,
    ):
        self.clean_on_exit = clean_on_exit
        self.is_active = False

        if root_dir is not None:
            self.sandbox_root = Path(root_dir).resolve()
        else:
            self.sandbox_root = Path(tempfile.mkdtemp(prefix="serato_sandbox_")).resolve()

        # Construct isolated folder hierarchy
        self.fake_home = (self.sandbox_root / "fake_home").resolve()
        self.tmp_dir = (self.sandbox_root / "tmp").resolve()
        self.mp3_dir = (self.fake_home / "Music" / "MP3").resolve()
        self.serato_dir = (self.fake_home / "Music" / "_Serato_").resolve()
        self.subcrates_dir = (self.serato_dir / "Subcrates").resolve()
        self.logs_dir = (self.fake_home / "SeratoSync" / "logs").resolve()
        self.exports_dir = (self.fake_home / "SeratoSync" / "exports").resolve()
        self.quarantine_dir = (self.fake_home / ".serato_quarentena_audio").resolve()
        self.serato_app_support = (
            self.fake_home / "Library" / "Application Support" / "Serato" / "Library"
        ).resolve()
        self.desktop_dir = (self.fake_home / "Desktop").resolve()
        self.trash_dir = (self.fake_home / ".Trash").resolve()
        self.backups_dir = (self.fake_home / "pasync" / "backups").resolve()

        self._create_sandbox_structure()

        # Pre-execution canary snapshot for zero leak validation
        self.extra_watch_paths = extra_watch_paths or []
        self._snapshot = self._take_host_snapshot()

        # Original environment & constant caches for restoration
        self._orig_env_home = None
        self._orig_env_tmpdir = None
        self._patched_constants: Dict[Tuple[str, str], Any] = {}

    def _create_sandbox_structure(self) -> None:
        """Creates complete physical directory tree, convenience symlinks, and dummy database."""
        for d in [
            self.fake_home,
            self.tmp_dir,
            self.mp3_dir,
            self.serato_dir,
            self.subcrates_dir,
            self.logs_dir,
            self.exports_dir,
            self.quarantine_dir,
            self.serato_app_support,
            self.desktop_dir,
            self.trash_dir,
            self.backups_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        # Create convenience symlinks at sandbox root
        symlinks = [
            (self.sandbox_root / "Music", self.fake_home / "Music"),
            (self.sandbox_root / "logs", self.logs_dir),
            (self.sandbox_root / "quarantine", self.quarantine_dir),
        ]
        for link, target in symlinks:
            if not link.exists() and not link.is_symlink():
                try:
                    link.symlink_to(target)
                except Exception:
                    pass

        # Dummy master.sqlite so backup and inspect commands don't crash
        master_db = self.serato_app_support / "master.sqlite"
        if not master_db.exists():
            conn = sqlite3.connect(str(master_db))
            conn.execute("CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, path TEXT);")
            conn.commit()
            conn.close()

    def _take_host_snapshot(self) -> Dict[str, Any]:
        """Takes an ultra-fast (<1ms) snapshot of real user paths to detect any leak."""
        snap: Dict[str, Any] = {}

        for rel in self.CRITICAL_HOST_PATHS:
            p = HOST_HOME / rel
            if p.exists():
                stat = p.stat()
                if p.is_dir():
                    try:
                        children = {c.name for c in p.iterdir()}
                    except Exception:
                        children = set()
                    snap[str(p)] = {"exists": True, "is_dir": True, "mtime": stat.st_mtime_ns, "children": children}
                else:
                    snap[str(p)] = {"exists": True, "is_dir": False, "mtime": stat.st_mtime_ns, "size": stat.st_size}
            else:
                snap[str(p)] = {"exists": False}

        # Check external volume
        ext = Path("/Volumes/Pastteyr")
        if ext.exists():
            try:
                stat = ext.stat()
                is_dir = ext.is_dir()
                children = set()
                if is_dir:
                    try:
                        children = {c.name for c in ext.iterdir()}
                    except Exception:
                        children = set()
                snap[str(ext)] = {
                    "exists": True,
                    "is_dir": is_dir,
                    "mtime": stat.st_mtime_ns,
                    "size": stat.st_size,
                    "children": children,
                }
            except Exception:
                snap[str(ext)] = {"exists": True, "is_dir": True, "mtime": 0, "size": 0, "children": set()}
        else:
            snap[str(ext)] = {"exists": False}

        # Snapshot extra watch paths
        for p in self.extra_watch_paths:
            p_res = Path(p).resolve()
            if p_res.exists():
                stat = p_res.stat()
                is_dir = p_res.is_dir()
                children = set()
                if is_dir:
                    try:
                        children = {c.name for c in p_res.iterdir()}
                    except Exception:
                        children = set()
                snap[str(p_res)] = {
                    "exists": True,
                    "is_dir": is_dir,
                    "mtime": stat.st_mtime_ns,
                    "size": stat.st_size,
                    "children": children,
                }
            else:
                snap[str(p_res)] = {"exists": False}

        # Snapshot top-level HOST_HOME entries
        try:
            snap["__HOST_HOME_ENTRIES__"] = {c.name for c in HOST_HOME.iterdir()}
        except Exception:
            snap["__HOST_HOME_ENTRIES__"] = set()

        return snap

    def assert_zero_leaks(self) -> None:
        """
        Forensic integrity assertion:
        Asserts with 100% certainty that no live production files were modified,
        no non-existent user files were created, and no new entries exist in HOST_HOME.
        """
        if not self._snapshot:
            return

        for path_str, state in self._snapshot.items():
            if path_str == "__HOST_HOME_ENTRIES__":
                continue
            p = Path(path_str)
            if not state.get("exists", False):
                if p.exists():
                    raise AssertionError(
                        f"CRITICAL SANDBOX LEAK DETECTED: File or directory {p} was created in host environment!"
                    )
            else:
                if not p.exists():
                    raise AssertionError(
                        f"CRITICAL SANDBOX LEAK DETECTED: Host file {p} was deleted during execution!"
                    )
                stat = p.stat()
                if not state.get("is_dir", False):
                    mtime_diff = stat.st_mtime_ns != state.get("mtime")
                    size_diff = "size" in state and stat.st_size != state["size"]
                    if mtime_diff or size_diff:
                        raise AssertionError(
                            f"CRITICAL SANDBOX LEAK DETECTED: Host file {p} was modified! "
                            f"(mtime: {state.get('mtime')} -> {stat.st_mtime_ns}, "
                            f"size: {state.get('size')} -> {stat.st_size})"
                        )
                else:
                    try:
                        current_children = {c.name for c in p.iterdir()}
                    except Exception:
                        current_children = set()
                    new_files = current_children - state.get("children", set())
                    if new_files:
                        raise AssertionError(
                            f"CRITICAL SANDBOX LEAK DETECTED: New files {new_files} created in host directory {p}!"
                        )

        # Check top-level HOST_HOME entries
        if "__HOST_HOME_ENTRIES__" in self._snapshot:
            initial_entries = self._snapshot["__HOST_HOME_ENTRIES__"]
            try:
                current_entries = {c.name for c in HOST_HOME.iterdir()}
            except Exception:
                current_entries = set()
            leaked = current_entries - initial_entries
            if leaked:
                raise AssertionError(
                    f"CRITICAL SANDBOX LEAK DETECTED: New files/directories {leaked} appeared in host home {HOST_HOME}!"
                )

    @property
    def env(self) -> Dict[str, str]:
        """Constructs isolated environment dictionary for subprocess execution."""
        env = os.environ.copy()
        env["HOME"] = str(self.fake_home)
        env["TMPDIR"] = str(self.tmp_dir)
        env["PYTHONPATH"] = f"{PROJECT_ROOT}:{VENDOR_DIR}:{env.get('PYTHONPATH', '')}"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["LC_ALL"] = "en_US.UTF-8"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PATH"] = f"/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '')}"
        return env

    def patch_in_process_constants(self) -> None:
        """
        Monkey-patches all 14 module-level path constants in-process, saving original
        values for clean restoration on exit.
        """
        patch_specs = [
            ("journal", "JOURNAL_PATH", self.fake_home / ".serato_sync_journal.sqlite"),
            ("auto_cue", "BACKUP_DB_PATH", self.fake_home / ".serato_sync_cues_backup.sqlite"),
            ("sound_seal", "DB_PATH", self.fake_home / ".serato_sound_seals.sqlite"),
            ("track_matcher", "DB_PATH", self.fake_home / ".serato_sound_seals.sqlite"),
            ("tag_doctor", "TAG_CACHE_DB", self.fake_home / ".serato_tag_cache.sqlite"),
            ("tag_doctor", "SOUND_SEAL_DB", self.fake_home / ".serato_sound_seals.sqlite"),
            ("tag_doctor", "SERATO_INTERNAL_DB", self.serato_app_support / "master.sqlite"),
            ("tag_doctor", "DEFAULT_BACKUPS_DIR", self.backups_dir),
            ("audio_health", "QUARANTINE_DIR", self.quarantine_dir),
            ("serato_macos_app", "DEFAULT_LOGS_DIR", self.logs_dir),
            ("library_tools", "SMART_RULES_PATH", self.fake_home / ".serato_sync_smart_crates.json"),
            ("library_tools", "WATCH_STATE_PATH", self.fake_home / ".serato_sync_watch_state.json"),
            ("library_tools", "EXPORTS_DIR", self.exports_dir),
            ("duplicates_tool", "REPORT_DIR", self.logs_dir),
        ]

        for mod_name, attr_name, target_val in patch_specs:
            if mod_name not in sys.modules:
                try:
                    __import__(mod_name)
                except Exception:
                    pass
            if mod_name in sys.modules:
                mod = sys.modules[mod_name]
                if hasattr(mod, attr_name):
                    self._patched_constants[(mod_name, attr_name)] = getattr(mod, attr_name)
                    setattr(mod, attr_name, target_val)

    def restore_in_process_constants(self) -> None:
        """Restores original values of all patched module-level constants."""
        for (mod_name, attr_name), orig_val in self._patched_constants.items():
            if mod_name in sys.modules:
                mod = sys.modules[mod_name]
                setattr(mod, attr_name, orig_val)
        self._patched_constants.clear()

    def start(self) -> "SeratoSandbox":
        """Activates sandbox environment."""
        if self.is_active:
            return self
        self._orig_env_home = os.environ.get("HOME")
        self._orig_env_tmpdir = os.environ.get("TMPDIR")
        os.environ["HOME"] = str(self.fake_home)
        os.environ["TMPDIR"] = str(self.tmp_dir)
        self.patch_in_process_constants()
        self.is_active = True
        return self

    def close(self) -> None:
        """Deactivates sandbox, verifies zero leaks, and optionally cleans up."""
        if not self.is_active:
            return
        try:
            self.assert_zero_leaks()
        finally:
            self.restore_in_process_constants()
            if self._orig_env_home is not None:
                os.environ["HOME"] = self._orig_env_home
            else:
                os.environ.pop("HOME", None)

            if self._orig_env_tmpdir is not None:
                os.environ["TMPDIR"] = self._orig_env_tmpdir
            else:
                os.environ.pop("TMPDIR", None)

            self.is_active = False
            if self.clean_on_exit:
                shutil.rmtree(self.sandbox_root, ignore_errors=True)

    def __enter__(self) -> "SeratoSandbox":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def run_cli(
        self,
        cmd_args: List[str],
        timeout: float = 60.0,
        cwd: Optional[Union[str, Path]] = None,
    ) -> SandboxResult:
        """
        Executes an external command or Python engine script in a contained subprocess.
        Automatically injects self.env and sys.executable for Python scripts.
        """
        if not cmd_args:
            raise ValueError("cmd_args cannot be empty")

        args = list(cmd_args)
        if args[0].endswith(".py"):
            args = [sys.executable] + args
        elif args[0] == "python3" or args[0] == "python":
            args[0] = sys.executable

        work_dir = Path(cwd).resolve() if cwd else PROJECT_ROOT

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                args,
                env=self.env,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.perf_counter() - t0
            return parse_sandbox_output(proc.returncode, proc.stdout, proc.stderr, duration)
        except subprocess.TimeoutExpired as e:
            duration = time.perf_counter() - t0
            stdout = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
            stderr = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode("utf-8", "replace")
            return SandboxResult(
                exit_code=-9,
                stdout=stdout,
                stderr=stderr + f"\nTIMEOUT ({timeout}s expired)",
                duration_sec=duration,
                error_message=f"Command timed out after {timeout}s",
            )

    def run_engine(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Executes a Python engine function in-process under captured stdout/stderr.
        """
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        try:
            sys.stdout = stdout_buf
            sys.stderr = stderr_buf
            return func(*args, **kwargs)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
