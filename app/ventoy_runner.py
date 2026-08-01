# -*- coding: utf-8 -*-
"""Instalación de Ventoy en discos USB mediante Ventoy2Disk CLI."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, Optional, Tuple

import bundled_assets
import disk_ops
from disk_service import is_admin
from windows_activation import _hidden_kwargs

CLI_PERCENT_FILE = "cli_percent.txt"
CLI_DONE_FILE = "cli_done.txt"
CLI_LOG_FILE = "cli_log.txt"

VENTOY_FILESYSTEMS = ("exFAT", "NTFS", "FAT32")

VentoyResult = Tuple[bool, str, str]

_ERROR_MARKERS = (
    "[ERROR]",
    "is NOT USB type",
    "Failed to get phydrive",
    "Invalid parameters",
)

_LOG_TS_RE = re.compile(r"^\[\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3}\]\s*")


def _ventoy_cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DiskHealthReport", "ventoy")


def _sync_tree(src: str, dst: str) -> None:
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
            except OSError:
                pass


def ensure_ventoy() -> str | None:
    """Copia el bundle Ventoy a AppData y devuelve la ruta persistente."""
    bundled = bundled_assets.ventoy_bundle_dir()
    if not bundled:
        return None
    dest_dir = _ventoy_cache_dir()
    try:
        _sync_tree(bundled, dest_dir)
    except OSError:
        return bundled if os.path.isdir(bundled) else None
    return dest_dir if os.path.isdir(dest_dir) else None


def ventoy2disk_exe(root: str) -> str:
    return os.path.join(root, "Ventoy2Disk_X64.exe")


def build_cli_args(
    phy_drive: int,
    *,
    update: bool = False,
    gpt: bool = True,
    secure_boot: bool = True,
    reserve_mb: int = 0,
    filesystem: str = "exFAT",
    no_usb_check: bool = False,
) -> list[str]:
    """Construye argumentos para Ventoy2Disk.exe VTOYCLI."""
    args = ["VTOYCLI", "/U" if update else "/I", f"/PhyDrive:{phy_drive}"]
    if gpt:
        args.append("/GPT")
    if not secure_boot:
        args.append("/NoSB")
    if reserve_mb > 0:
        args.append(f"/R:{int(reserve_mb)}")
    fs = (filesystem or "exFAT").upper()
    if fs == "EXFAT":
        fs = "exFAT"
    elif fs in ("NTFS", "FAT32"):
        pass
    else:
        fs = "exFAT"
    if fs != "exFAT":
        args.append(f"/FS:{fs}")
    if no_usb_check:
        args.append("/NoUSBCheck")
    return args


def read_cli_percent(path: str) -> float | None:
    """Lee porcentaje 0-100 desde cli_percent.txt."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read().strip().splitlines()
        if not raw:
            return None
        return float(raw[0].strip())
    except (OSError, ValueError):
        return None


def read_cli_done(path: str) -> bool | None:
    """Lee cli_done.txt: True=éxito, False=fallo, None=ausente."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            line = fh.read().strip().splitlines()
        if not line:
            return None
        return line[0].strip() == "0"
    except OSError:
        return None


def read_cli_log(root: str) -> str:
    """Lee cli_log.txt generado por Ventoy2Disk en modo CLI."""
    path = os.path.join(root, CLI_LOG_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _strip_log_timestamp(line: str) -> str:
    return _LOG_TS_RE.sub("", line).strip()


def parse_cli_log_last_error(log_text: str) -> str:
    """Devuelve la última línea de error relevante del log CLI."""
    last_error = ""
    last_failed = ""
    for raw in log_text.splitlines():
        line = _strip_log_timestamp(raw.strip())
        if not line:
            continue
        upper = line.upper()
        if "[ERROR]" in upper:
            last_error = line
        elif " FAILED" in upper or upper.endswith("FAILED"):
            last_failed = line
    return last_error or last_failed


def classify_ventoy_error(log_text: str) -> str:
    """Clasifica el fallo de Ventoy en una clave i18n."""
    lower = (log_text or "").lower()
    if "no ventoy information detected" in lower:
        return "ventoy_update_not_ventoy"
    if "failed to open physical disk" in lower:
        return "ventoy_disk_locked"
    if "volume is in use" in lower or "device is not ready" in lower:
        return "ventoy_disk_locked"
    if "not usb type" in lower:
        return "ventoy_not_usb"
    if "invalid parameters" in lower:
        return "ventoy_failed"
    return "ventoy_failed"


def _output_has_error(text: str) -> bool:
    upper = text.upper()
    return any(m.upper() in upper for m in _ERROR_MARKERS)


def _cleanup_cli_files(root: str) -> None:
    for name in (CLI_PERCENT_FILE, CLI_DONE_FILE, CLI_LOG_FILE):
        try:
            os.unlink(os.path.join(root, name))
        except OSError:
            pass


def _validate_disk(phy_drive: int) -> tuple[bool, str]:
    pd = disk_ops._get_disk_fresh(phy_drive)
    if pd is None:
        return False, "ventoy_no_disk"
    if pd.get("is_system") or pd.get("is_boot"):
        return False, "ventoy_system_disk"
    return True, ""


def _fail_from_log(root: str, stdout_text: str, rc: int) -> VentoyResult:
    log_text = read_cli_log(root)
    combined = f"{log_text}\n{stdout_text}"
    detail = parse_cli_log_last_error(log_text) or parse_cli_log_last_error(stdout_text)
    if not detail and rc != 0:
        detail = f"exit code {rc}"
    err_key = classify_ventoy_error(combined)
    if err_key == "ventoy_failed" and "NOT USB" in combined.upper():
        err_key = "ventoy_not_usb"
    return False, err_key, detail


def install_ventoy(
    phy_drive: int,
    *,
    update: bool = False,
    gpt: bool = True,
    secure_boot: bool = True,
    reserve_mb: int = 0,
    filesystem: str = "exFAT",
    no_usb_check: bool = False,
    on_line: Callable[[str], None] | None = None,
    progress_cb: Callable[[float], None] | None = None,
    cancel: Optional[threading.Event] = None,
) -> VentoyResult:
    """Instala o actualiza Ventoy. Devuelve (ok, clave_i18n, detalle_log)."""
    if sys.platform != "win32":
        return False, "ventoy_failed", ""

    if not is_admin():
        return False, "ventoy_not_admin", ""

    ok, err = _validate_disk(phy_drive)
    if not ok:
        return False, err, ""

    root = ensure_ventoy()
    if not root:
        return False, "ventoy_not_bundled", ""

    exe = ventoy2disk_exe(root)
    if not os.path.isfile(exe):
        return False, "ventoy_not_bundled", ""

    if not update:
        prep_ok, prep_detail = disk_ops.prepare_disk_for_ventoy(phy_drive)
        if not prep_ok:
            err_key = classify_ventoy_error(prep_detail)
            if err_key == "ventoy_failed":
                err_key = "ventoy_disk_locked"
            return False, err_key, prep_detail

    args = build_cli_args(
        phy_drive,
        update=update,
        gpt=gpt,
        secure_boot=secure_boot,
        reserve_mb=reserve_mb,
        filesystem=filesystem,
        no_usb_check=no_usb_check,
    )
    cmd = [exe, *args]

    def log(line: str) -> None:
        if on_line:
            on_line(line)

    _cleanup_cli_files(root)
    log(f"> {' '.join(cmd)}")

    collected: list[str] = []
    proc_holder: list[subprocess.Popen | None] = [None]
    done = threading.Event()

    def poll_progress() -> None:
        percent_path = os.path.join(root, CLI_PERCENT_FILE)
        log_path = os.path.join(root, CLI_LOG_FILE)
        last_pct = -1.0
        last_log_pos = 0
        while not done.is_set():
            if cancel is not None and cancel.is_set():
                proc = proc_holder[0]
                if proc is not None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                break
            pct = read_cli_percent(percent_path)
            if pct is not None and pct != last_pct and progress_cb:
                try:
                    progress_cb(pct)
                except Exception:
                    pass
                last_pct = pct
            try:
                if os.path.isfile(log_path):
                    with open(log_path, encoding="utf-8", errors="replace") as fh:
                        fh.seek(last_log_pos)
                        chunk = fh.read()
                        last_log_pos = fh.tell()
                    for line in chunk.splitlines():
                        s = line.strip()
                        if s:
                            log(_strip_log_timestamp(s))
            except OSError:
                pass
            time.sleep(0.25)

    def capture(line: str) -> None:
        collected.append(line)
        log(line)

    poll_thread = threading.Thread(target=poll_progress, daemon=True)
    poll_thread.start()

    try:
        popen_kw = _hidden_kwargs()
        popen_kw["cwd"] = root
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            **popen_kw,
        )
        proc_holder[0] = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                try:
                    proc.terminate()
                except Exception:
                    pass
                break
            capture(line.rstrip("\n"))
        rc = proc.wait()
    except Exception:
        done.set()
        poll_thread.join(timeout=2.0)
        return False, "ventoy_failed", ""
    finally:
        done.set()
        poll_thread.join(timeout=2.0)

    if cancel is not None and cancel.is_set():
        return False, "ventoy_cancelled", ""

    done_path = os.path.join(root, CLI_DONE_FILE)
    cli_ok = read_cli_done(done_path)
    text = "\n".join(collected)

    if cli_ok is True:
        if progress_cb:
            try:
                progress_cb(100.0)
            except Exception:
                pass
        return True, "ventoy_done", ""


def _log_suggests_existing_ventoy(log_text: str) -> bool:
    """Indica si el log sugiere que el disco ya tiene Ventoy."""
    lower = (log_text or "").lower()
    if "no ventoy information detected" in lower:
        return False
    markers = (
        "already",
        "ventoy information detected",
        "ventoy_cli_update",
        "no need to install",
    )
    return any(m in lower for m in markers)


def prepare_multiboot_usb(
    phy_drive: int,
    *,
    gpt: bool = True,
    secure_boot: bool = True,
    reserve_mb: int = 0,
    filesystem: str = "exFAT",
    no_usb_check: bool = False,
    on_line: Callable[[str], None] | None = None,
    progress_cb: Callable[[float], None] | None = None,
    cancel: Optional[threading.Event] = None,
) -> VentoyResult:
    """Prepara USB multiboot: elige install/update automáticamente y reintenta si hace falta."""
    root = ensure_ventoy()
    if not root:
        return False, "ventoy_not_bundled", ""

    common = dict(
        gpt=gpt,
        secure_boot=secure_boot,
        reserve_mb=reserve_mb,
        filesystem=filesystem,
        no_usb_check=no_usb_check,
        on_line=on_line,
        progress_cb=progress_cb,
        cancel=cancel,
    )

    update = disk_ops.disk_has_ventoy(phy_drive)
    ok, key, detail = install_ventoy(phy_drive, update=update, **common)
    if ok:
        return True, "boot_multiboot_done", detail

    if key == "ventoy_cancelled":
        return False, key, detail

    if update and key == "ventoy_update_not_ventoy":
        ok, key, detail = install_ventoy(phy_drive, update=False, **common)
        if ok:
            return True, "boot_multiboot_done", detail
        return ok, key, detail

    if not update:
        log_text = read_cli_log(root)
        combined = f"{log_text}\n{detail}"
        if _log_suggests_existing_ventoy(combined) or disk_ops.disk_has_ventoy(phy_drive):
            ok, key, detail = install_ventoy(phy_drive, update=True, **common)
            if ok:
                return True, "boot_multiboot_done", detail
            return ok, key, detail

    return ok, key, detail

    if cli_ok is False or rc != 0 or _output_has_error(read_cli_log(root)) or _output_has_error(text):
        return _fail_from_log(root, text, rc)

    if progress_cb:
        try:
            progress_cb(100.0)
        except Exception:
            pass
    return True, "ventoy_done", ""
