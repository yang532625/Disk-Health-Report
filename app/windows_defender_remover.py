# -*- coding: utf-8 -*-
"""Ejecutor integrado de Windows Defender Remover (PowerRun + regedit /s).

Alineado con Script_Run.bat del proyecto ionuttbara/windows-defender-remover.
PowerRun.exe (Sordum freeware) se incluye en el bundle como en el repo oficial.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
from typing import Callable, Optional, Tuple

import bundled_assets
from disk_service import is_admin
from windows_activation import _output_has_error, _stream_process

Step = tuple[str, str]

_ERROR_MARKERS = (
    "==== ERROR ====",
    "Input redirection is not supported",
    "launched from the temp folder",
    "Extract the archive file",
    "Error accessing the registry",
    "Access is denied",
    "Cannot delete",
    "Acceso denegado",
    "Cannot remove",
)

_REQUIRED_BUNDLE_REL = (
    "PowerRun.exe",
    "RemoveSecHealthApp.ps1",
    "files_removal.bat",
    os.path.join("Remove_Defender", "DisableAntivirusProtection.reg"),
    os.path.join("Remove_SecurityComp", "Remove_SecurityComp.reg"),
)


def _defender_cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DiskHealthReport", "defender_remover")


def _is_meipass_path(path: str) -> bool:
    meipass = getattr(sys, "_MEIPASS", "") or ""
    if not meipass:
        return False
    try:
        return os.path.commonpath([
            os.path.normcase(os.path.abspath(path)),
            os.path.normcase(os.path.abspath(meipass)),
        ]) == os.path.normcase(os.path.abspath(meipass))
    except ValueError:
        return False


def _unblock_file(path: str) -> None:
    """Quita Zone.Identifier (bloqueo MOTW al copiar el .exe a otra PC)."""
    if sys.platform != "win32" or not path:
        return
    zone = f"{path}:Zone.Identifier"
    try:
        os.remove(zone)
    except OSError:
        pass


def _verify_defender_bundle(root: str) -> bool:
    if not root or not os.path.isdir(root):
        return False
    for rel in _REQUIRED_BUNDLE_REL:
        full = os.path.join(root, rel)
        if not os.path.isfile(full) or os.path.getsize(full) <= 0:
            return False
    return True


def _sync_tree(src: str, dst: str) -> None:
    """Copia recursiva del bundle a AppData, actualizando archivos modificados."""
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dest_root = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(dest_root, exist_ok=True)
        for name in files:
            s = os.path.join(root, name)
            d = os.path.join(dest_root, name)
            try:
                if not os.path.isfile(d):
                    shutil.copy2(s, d)
                else:
                    src_mtime = os.path.getmtime(s)
                    dst_mtime = os.path.getmtime(d)
                    src_size = os.path.getsize(s)
                    dst_size = os.path.getsize(d)
                    if src_mtime > dst_mtime or src_size != dst_size:
                        shutil.copy2(s, d)
                if name.lower().endswith(".exe"):
                    _unblock_file(d)
            except OSError:
                pass


def ensure_defender_remover(on_line: Callable[[str], None] | None = None) -> str | None:
    """Copia el bundle a AppData y devuelve la ruta persistente (nunca _MEIPASS)."""
    def log(msg: str) -> None:
        if on_line:
            on_line(msg)

    bundled = bundled_assets.defender_remover_bundle_dir()
    if not bundled:
        log("[X] Defender Remover bundle not found inside the application")
        return None

    dest_dir = _defender_cache_dir()
    try:
        os.makedirs(dest_dir, exist_ok=True)
        _sync_tree(bundled, dest_dir)
    except OSError as exc:
        log(f"[X] Could not copy Defender Remover to AppData: {exc}")

    if _verify_defender_bundle(dest_dir):
        powerrun = os.path.join(dest_dir, "PowerRun.exe")
        _unblock_file(powerrun)
        return dest_dir

    log("[X] Defender Remover files incomplete in AppData (PowerRun or scripts missing)")
    log("    If you copied the .exe from USB, allow it in antivirus and retry.")
    return None


def is_tamper_protection_enabled() -> bool | None:
    """None si no se pudo consultar; True/False según Protección contra alteraciones."""
    if sys.platform != "win32":
        return None
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "try { "
        "  if (Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue) { "
        "    $s=Get-MpComputerStatus; "
        "    if ($null -ne $s.IsTamperProtected) { "
        "      if ($s.IsTamperProtected) { 'true' } else { 'false' }; return "
        "    } "
        "  }; "
        "  $p=Get-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows Defender\\Features' "
        "    -Name TamperProtection -ErrorAction Stop; "
        "  if ($p.TamperProtection -eq 1) { 'true' } else { 'false' } "
        "} catch { 'unknown' }"
    )
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (result.stdout or "").strip().lower()
    except Exception:
        return None
    if out == "true":
        return True
    if out == "false":
        return False
    return None


def _powerrun_path(root: str) -> str:
    return os.path.join(root, "PowerRun.exe")


def _regedit_path() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "regedit.exe")


def _output_has_defender_error(text: str) -> bool:
    lower = text.lower()
    if _output_has_error(text):
        return True
    return any(m.lower() in lower for m in _ERROR_MARKERS)


def _stream_step(cmd: list, on_line: Callable[[str], None],
                 cancel: Optional[threading.Event],
                 cwd: str | None = None) -> Tuple[bool, str]:
    """Ejecuta un paso y traduce errores de activación a defender_failed."""
    collected: list[str] = []

    def capture(line: str) -> None:
        collected.append(line)
        on_line(line)

    ok, err = _stream_process(cmd, capture, cancel, cwd=cwd)
    if _output_has_defender_error("\n".join(collected)):
        return False, "defender_failed"
    if err == "activation_failed":
        return False, "defender_failed"
    if err == "activation_cancelled":
        return False, "defender_cancelled"
    return ok, err


def _run_reg_file(root: str, full_path: str,
                  on_line: Callable[[str], None],
                  cancel: Optional[threading.Event]) -> Tuple[bool, str]:
    regedit = _regedit_path()
    powerrun = _powerrun_path(root)
    collected: list[str] = []

    def capture(line: str) -> None:
        collected.append(line)
        on_line(line)

    if os.path.isfile(powerrun):
        on_line("  PowerRun regedit /s")
        ok_pr, _ = _stream_step(
            [powerrun, "/SW:0", regedit, "/s", full_path],
            capture, cancel, cwd=root,
        )
        if _output_has_defender_error("\n".join(collected)):
            return False, "defender_failed"
        if ok_pr:
            return True, ""
        on_line("[X] PowerRun regedit failed (Tamper Protection may be blocking changes)")
        return False, "defender_failed"

    on_line("[X] PowerRun.exe not found in bundle")
    return False, "defender_no_powerrun"


def _run_powershell(root: str, full_path: str,
                    on_line: Callable[[str], None],
                    cancel: Optional[threading.Event]) -> Tuple[bool, str]:
    powerrun = _powerrun_path(root)
    ps_args = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", full_path,
    ]
    if os.path.isfile(powerrun):
        on_line("  PowerRun powershell -File")
        ok, err = _stream_step(
            [powerrun, "/SW:0", *ps_args], on_line, cancel, cwd=root,
        )
        if ok:
            return ok, err
        on_line("[X] PowerRun powershell failed")
        return False, "defender_failed"
    on_line("[X] PowerRun.exe not found in bundle")
    return False, "defender_no_powerrun"


def _run_batch(root: str, full_path: str,
               on_line: Callable[[str], None],
               cancel: Optional[threading.Event]) -> Tuple[bool, str]:
    powerrun = _powerrun_path(root)
    if os.path.isfile(powerrun):
        on_line("  PowerRun cmd /c")
        ok, err = _stream_step(
            [powerrun, "/SW:0", "cmd.exe", "/c", full_path],
            on_line, cancel, cwd=root,
        )
        if ok:
            return ok, err
        on_line("[X] PowerRun batch failed")
        return False, "defender_failed"
    on_line("[X] PowerRun.exe not found in bundle")
    return False, "defender_no_powerrun"


def _engine_reg_steps(root: str) -> list[Step]:
    reg_dir = os.path.join(root, "Remove_Defender")
    steps: list[Step] = []
    if os.path.isdir(reg_dir):
        for name in sorted(os.listdir(reg_dir)):
            if name.lower().endswith(".reg"):
                steps.append(("reg", os.path.join("Remove_Defender", name)))
    return steps


def _build_action_steps(root: str) -> dict[str, list[Step]]:
    engine_regs = _engine_reg_steps(root)
    security_ps1: Step = ("ps1", "RemoveSecHealthApp.ps1")
    security_reg: Step = (
        "reg", os.path.join("Remove_SecurityComp", "Remove_SecurityComp.reg"),
    )
    files: list[Step] = [("bat", "files_removal.bat")]
    return {
        "full": [security_ps1] + engine_regs + [security_reg] + files,
        "engine": engine_regs,
        "security": [security_ps1, security_reg],
        "files": files,
    }


def _run_step(root: str, kind: str, rel_path: str,
              on_line: Callable[[str], None],
              cancel: Optional[threading.Event]) -> Tuple[bool, str]:
    full = os.path.join(root, rel_path)
    if not os.path.isfile(full):
        on_line(f"[X] Missing: {rel_path}")
        return False, "defender_failed"

    on_line(f"> {kind}: {rel_path}")

    if kind == "reg":
        return _run_reg_file(root, full, on_line, cancel)

    if kind == "ps1":
        return _run_powershell(root, full, on_line, cancel)

    if kind == "bat":
        return _run_batch(root, full, on_line, cancel)

    return False, "defender_failed"


def run_action(action_id: str, on_line: Callable[[str], None],
               cancel: Optional[threading.Event] = None) -> Tuple[bool, str]:
    """Ejecuta una acción de Defender Remover en segundo plano."""
    if sys.platform != "win32":
        return False, "defender_failed"

    if not is_admin():
        on_line("[X] Administrator privileges required")
        return False, "defender_not_admin"

    tamper = is_tamper_protection_enabled()
    if tamper is True:
        on_line("[!] Tamper Protection is ON in Windows Security")
        on_line("    Turn it off before continuing (Virus & threat protection settings)")
        return False, "defender_tamper_enabled"

    root = ensure_defender_remover(on_line)
    if not root:
        return False, "defender_bundle_missing"
    if _is_meipass_path(root):
        on_line("[X] Internal error: bundle must run from AppData, not temp folder")
        return False, "defender_bundle_missing"

    on_line(f"Using: {root}")

    steps_map = _build_action_steps(root)
    steps = steps_map.get(action_id)
    if not steps:
        return False, "defender_failed"

    last_ok = False
    last_err = "defender_failed"

    for kind, rel_path in steps:
        if cancel is not None and cancel.is_set():
            return False, "defender_cancelled"
        ok, err = _run_step(root, kind, rel_path, on_line, cancel)
        last_ok, last_err = ok, err
        if not ok:
            break

    if cancel is not None and cancel.is_set():
        return False, "defender_cancelled"

    return last_ok, ("" if last_ok else last_err)
