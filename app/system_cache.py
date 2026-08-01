# -*- coding: utf-8 -*-
"""Limpieza de carpetas temporales del sistema (solo contenido, no las carpetas)."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from typing import TypedDict


class CacheCleanResult(TypedDict):
    deleted: int
    skipped: int
    bytes_freed: int
    recycle_emptied: bool


def empty_recycle_bin() -> bool:
    """Vacía la Papelera de reciclaje de forma nativa y silenciosa (Windows)."""
    if sys.platform != "win32":
        return False
    SHERB_NOCONFIRMATION = 0x00000001
    SHERB_NOPROGRESSUI = 0x00000002
    SHERB_NOSOUND = 0x00000004
    try:
        res = ctypes.windll.shell32.SHEmptyRecycleBinW(
            None, None,
            SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND,
        )
        # S_OK (0) o E_UNEXPECTED cuando ya está vacía (-2147418113 / 0x8000FFFF).
        return res in (0, -2147418113)
    except Exception:
        return False


def _cache_directories() -> list[str]:
    user_profile = os.environ.get("USERPROFILE", "")
    system_root = os.environ.get("SystemRoot", "C:\\Windows")
    paths = []
    if user_profile:
        paths.append(os.path.join(user_profile, "AppData", "Local", "Temp"))
    paths.append(os.path.join(system_root, "Temp"))
    paths.append(os.path.join(system_root, "Prefetch"))
    return paths


def _entry_size(path: str) -> int:
    try:
        if os.path.isfile(path) or os.path.islink(path):
            return os.path.getsize(path)
        total = 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def _remove_entry(path: str) -> bool:
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            return not os.path.exists(path)
        os.unlink(path)
        return True
    except OSError:
        return False


def _clean_directory_contents(directory: str) -> tuple[int, int, int]:
    deleted = 0
    skipped = 0
    bytes_freed = 0

    if not os.path.isdir(directory):
        return deleted, skipped, bytes_freed

    try:
        entries = list(os.scandir(directory))
    except OSError:
        return deleted, skipped, bytes_freed

    for entry in entries:
        try:
            path = entry.path
            size = _entry_size(path)
            if _remove_entry(path):
                deleted += 1
                bytes_freed += size
            else:
                skipped += 1
        except OSError:
            skipped += 1

    return deleted, skipped, bytes_freed


def clean_system_cache() -> CacheCleanResult:
    """Vacía el contenido de las carpetas temporales del sistema."""
    total_deleted = 0
    total_skipped = 0
    total_bytes = 0

    for directory in _cache_directories():
        try:
            d, s, b = _clean_directory_contents(directory)
            total_deleted += d
            total_skipped += s
            total_bytes += b
        except OSError:
            continue

    recycle_emptied = empty_recycle_bin()

    return {
        "deleted": total_deleted,
        "skipped": total_skipped,
        "bytes_freed": total_bytes,
        "recycle_emptied": recycle_emptied,
    }
