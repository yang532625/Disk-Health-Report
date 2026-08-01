# -*- coding: utf-8 -*-
"""Creacion nativa de USB booteable (sin Rufus).

- ISOs de Windows (con sources\\install.wim): formatea FAT32 + copia archivos +
  divide install.wim con DISM si supera 4 GB (limite de FAT32). Arranca por UEFI.
- ISOs de Linux / imagenes 'dd' (isohibridas): escribe la imagen byte a byte al
  disco fisico (\\\\.\\PhysicalDriveN).

Todo de forma defensiva: nunca opera sobre el disco del sistema/arranque.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from typing import Callable, Optional

import disk_ops

ProgressCB = Optional[Callable[[str, Optional[float]], None]]

_FAT32_MAX_FILE = 4000 * 1024 * 1024  # margen seguro bajo el limite de 4 GiB


def _report(cb: ProgressCB, stage: str, fraction: Optional[float] = None) -> None:
    if cb:
        try:
            cb(stage, fraction)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Montaje de ISO
# ---------------------------------------------------------------------------
def mount_iso(iso_path: str) -> Optional[str]:
    """Monta la ISO y devuelve la letra de unidad (sin ':') o None."""
    safe = iso_path.replace("'", "''")
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$img = Mount-DiskImage -ImagePath '{safe}' -PassThru; "
        "Start-Sleep -Milliseconds 700; "
        "$vol = $img | Get-DiskImage | Get-Volume; "
        "if ($vol -and $vol.DriveLetter) { \"$($vol.DriveLetter)\" }"
    )
    out = disk_ops._run_ps(script, timeout=60).strip()
    letter = out.splitlines()[-1].strip() if out else ""
    letter = letter.rstrip(":")
    if len(letter) == 1 and letter.isalpha():
        return letter.upper()
    return None


def dismount_iso(iso_path: str) -> None:
    safe = iso_path.replace("'", "''")
    disk_ops._run_ps(
        f"Dismount-DiskImage -ImagePath '{safe}' -ErrorAction SilentlyContinue | Out-Null",
        timeout=60,
    )


def detect_iso_type(mount_letter: str) -> str:
    """Devuelve 'windows', 'linux' u 'other' segun el contenido del ISO montado."""
    root = f"{mount_letter}:\\"
    wim = os.path.join(root, "sources", "install.wim")
    esd = os.path.join(root, "sources", "install.esd")
    bootmgr = os.path.join(root, "bootmgr")
    if os.path.exists(wim) or os.path.exists(esd) or os.path.exists(bootmgr):
        return "windows"
    return "linux"


def detect_iso_type_for_file(iso_path: str) -> str:
    """Monta temporalmente la ISO para detectar su tipo y la desmonta."""
    letter = mount_iso(iso_path)
    if not letter:
        return "linux"
    try:
        return detect_iso_type(letter)
    finally:
        dismount_iso(iso_path)


# ---------------------------------------------------------------------------
# USB de instalacion de Windows (formato + copia + split WIM)
# ---------------------------------------------------------------------------
def _set_partition_active(number: int, letter: str) -> None:
    """Marca la particion como activa (MBR) para arranque BIOS. Best-effort."""
    script = (
        f"select disk {number}\r\n"
        f"select partition 1\r\n"
        "active\r\n"
        "exit\r\n"
    )
    tmp = None
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="ascii", errors="ignore") as fh:
            fh.write(script)
        subprocess.run(["diskpart", "/s", tmp], capture_output=True, text=True,
                       timeout=60, **disk_ops._hidden_kwargs())
    except Exception:
        pass
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def create_windows_usb(iso_path: str, number: int, label: str = "WIN_USB",
                       progress_cb: ProgressCB = None) -> tuple[bool, str]:
    _report(progress_cb, "boot_preparing")
    pd = disk_ops._get_disk_fresh(number)
    if pd is None:
        return False, "no_disk"
    if pd["is_system"] or pd["is_boot"]:
        return False, "system"

    # Formato FAT32 (MBR) reutilizando la logica nativa de formateo
    _BOOT_FORMAT_FRACS = {
        "checking": 0.05,
        "partitioning": 0.12,
        "formatting": 0.20,
        "done": 0.25,
    }

    def on_format_progress(stage: str, fraction: float | None = None):
        frac = fraction if fraction is not None else _BOOT_FORMAT_FRACS.get(stage)
        if frac is not None:
            _report(progress_cb, "boot_preparing", frac)
        else:
            _report(progress_cb, "boot_preparing")

    ok, info = disk_ops.format_disk(
        number, "MBR", "FAT32", label or "WIN_USB",
        quick=True,
        progress_cb=on_format_progress if progress_cb else None,
    )
    if not ok:
        return False, info
    usb_letter = str(info).strip().rstrip(":")
    if not usb_letter:
        return False, "no_letter"

    _set_partition_active(number, usb_letter)

    _report(progress_cb, "boot_mounting")
    iso_letter = mount_iso(iso_path)
    if not iso_letter:
        return False, "iso_mount_failed"

    try:
        iso_root = f"{iso_letter}:\\"
        usb_root = f"{usb_letter}:\\"

        _report(progress_cb, "boot_copying")
        # Copiar todo excepto install.wim (se maneja aparte por el limite FAT32)
        rc = subprocess.run(
            ["robocopy", iso_root, usb_root, "/E", "/NJH", "/NJS",
             "/NFL", "/NDL", "/NP", "/R:1", "/W:1", "/XF", "install.wim"],
            capture_output=True, text=True, timeout=3600 * 4,
            **disk_ops._hidden_kwargs(),
        )
        # robocopy: codigos 0-7 = exito
        if rc.returncode >= 8:
            return False, "copy_failed"

        wim = os.path.join(iso_root, "sources", "install.wim")
        if os.path.exists(wim):
            dest_dir = os.path.join(usb_root, "sources")
            os.makedirs(dest_dir, exist_ok=True)
            try:
                size = os.path.getsize(wim)
            except OSError:
                size = _FAT32_MAX_FILE + 1
            if size <= _FAT32_MAX_FILE:
                import shutil
                shutil.copy2(wim, os.path.join(dest_dir, "install.wim"))
            else:
                _report(progress_cb, "boot_splitting")
                swm = os.path.join(dest_dir, "install.swm")
                dism = subprocess.run(
                    ["dism", "/English", "/Split-Image",
                     f"/ImageFile:{wim}", f"/SWMFile:{swm}", "/FileSize:3800"],
                    capture_output=True, text=True, timeout=3600 * 4,
                    **disk_ops._hidden_kwargs(),
                )
                if dism.returncode != 0:
                    return False, "wim_split_failed"
    finally:
        dismount_iso(iso_path)

    disk_ops._invalidate_cache()
    _report(progress_cb, "boot_finalizing")
    _report(progress_cb, "done")
    return True, usb_letter


# ---------------------------------------------------------------------------
# Escritura DD (Linux / imagenes isohibridas)
# ---------------------------------------------------------------------------
def _clean_disk(number: int) -> bool:
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$n={number}; "
        "try { "
        "$d=Get-Disk -Number $n; if ($d.IsSystem -or $d.IsBoot) { throw 'SYSTEM' }; "
        "Set-Disk -Number $n -IsReadOnly $false -ErrorAction SilentlyContinue; "
        "Set-Disk -Number $n -IsOffline $false -ErrorAction SilentlyContinue; "
        "Clear-Disk -Number $n -RemoveData -RemoveOEM -Confirm:$false -ErrorAction SilentlyContinue; "
        "'OK' } catch { 'FAIL' }"
    )
    return "OK" in disk_ops._run_ps(script, timeout=120)


def _set_disk_offline(number: int, offline: bool) -> None:
    val = "$true" if offline else "$false"
    disk_ops._run_ps(
        f"Set-Disk -Number {number} -IsOffline {val} -ErrorAction SilentlyContinue | Out-Null",
        timeout=60,
    )


def create_dd_usb(iso_path: str, number: int,
                  progress_cb: ProgressCB = None) -> tuple[bool, str]:
    _report(progress_cb, "boot_preparing")
    pd = disk_ops._get_disk_fresh(number)
    if pd is None:
        return False, "no_disk"
    if pd["is_system"] or pd["is_boot"]:
        return False, "system"

    try:
        total = os.path.getsize(iso_path)
    except OSError:
        return False, "iso_invalid"
    if total <= 0:
        return False, "iso_invalid"

    if not _clean_disk(number):
        return False, "prepare_failed"
    _set_disk_offline(number, True)
    time.sleep(1.0)

    GENERIC_WRITE = 0x40000000
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    OPEN_EXISTING = 3
    INVALID = wintypes.HANDLE(-1).value

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    path = f"\\\\.\\PhysicalDrive{number}"
    handle = kernel32.CreateFileW(
        path, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None,
    )
    if not handle or handle == INVALID:
        _set_disk_offline(number, False)
        return False, "open_failed"

    _report(progress_cb, "boot_writing", 0.0)
    chunk = 1024 * 1024
    written_total = 0
    ok = True
    err = ""
    try:
        with open(iso_path, "rb") as src:
            while True:
                data = src.read(chunk)
                if not data:
                    break
                # Alinear a 512 bytes el ultimo bloque
                if len(data) % 512 != 0:
                    pad = 512 - (len(data) % 512)
                    data = data + (b"\x00" * pad)
                buf = ctypes.create_string_buffer(data, len(data))
                written = wintypes.DWORD(0)
                res = kernel32.WriteFile(
                    handle, buf, len(data), ctypes.byref(written), None
                )
                if not res or written.value != len(data):
                    ok = False
                    err = "write_failed"
                    break
                written_total += len(data)
                if total:
                    _report(progress_cb, "boot_writing",
                            min(0.999, written_total / total))
        kernel32.FlushFileBuffers(handle)
    except Exception as e:
        ok = False
        err = str(e) or "write_failed"
    finally:
        kernel32.CloseHandle(handle)
        _set_disk_offline(number, False)
        disk_ops._invalidate_cache()

    if not ok:
        return False, err
    _report(progress_cb, "done", 1.0)
    return True, ""


def create_bootable(iso_path: str, number: int, iso_type: str, label: str = "",
                    progress_cb: ProgressCB = None) -> tuple[bool, str]:
    """Punto de entrada: elige el metodo segun el tipo de ISO."""
    if iso_type == "windows":
        return create_windows_usb(iso_path, number, label or "WIN_USB", progress_cb)
    return create_dd_usb(iso_path, number, progress_cb)
