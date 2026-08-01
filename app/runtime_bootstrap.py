# -*- coding: utf-8 -*-
"""Extrae smartctl embebido al arranque (build PyInstaller one-file)."""

import hashlib
import os
import shutil
import sys

_RUNTIME_MARKER = "runtime_version.txt"
_EMBEDDED_FILES = ("smartctl.exe", "drivedb.h")


def get_runtime_cache_dir() -> str:
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "DiskHealthReport", "runtime")
    return os.path.join(base, "smartmontools", "bin")


def get_cached_smartctl_path() -> str:
    return os.path.join(get_runtime_cache_dir(), "smartctl.exe")


def _embedded_bundle_dir() -> str | None:
    if not getattr(sys, "frozen", False):
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(here) if os.path.basename(here).lower() == "app" else here
        dev = os.path.join(root, "packaging", "assets", "smartmontools", "bin")
        return dev if os.path.isdir(dev) else None
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    bundled = os.path.join(meipass, "smartmontools", "bin")
    return bundled if os.path.isdir(bundled) else None


def _bundle_fingerprint(bundle_dir: str) -> str:
    parts: list[str] = []
    for name in _EMBEDDED_FILES:
        path = os.path.join(bundle_dir, name)
        if os.path.isfile(path):
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            parts.append(f"{name}:{h.hexdigest()}")
    return "|".join(parts)


def _needs_extract(bundle_dir: str, cache_dir: str) -> bool:
    smartctl = os.path.join(cache_dir, "smartctl.exe")
    if not os.path.isfile(smartctl):
        return True
    marker = os.path.join(cache_dir, _RUNTIME_MARKER)
    fingerprint = _bundle_fingerprint(bundle_dir)
    if not fingerprint:
        return False
    if os.path.isfile(marker):
        try:
            with open(marker, "r", encoding="utf-8") as f:
                if f.read().strip() == fingerprint:
                    return False
        except OSError:
            pass
    return True


def ensure_runtime_smartctl() -> str | None:
    """
    Extrae smartctl + drivedb.h a %LOCALAPPDATA%\\DiskHealthReport\\runtime si hace falta.
    Retorna ruta a smartctl.exe en caché, o None si no hay bundle embebido.
    """
    bundle_dir = _embedded_bundle_dir()
    if not bundle_dir:
        return None

    smartctl_src = os.path.join(bundle_dir, "smartctl.exe")
    if not os.path.isfile(smartctl_src):
        return None

    cache_dir = get_runtime_cache_dir()
    if not _needs_extract(bundle_dir, cache_dir):
        return get_cached_smartctl_path()

    os.makedirs(cache_dir, exist_ok=True)
    tmp_dir = cache_dir + ".tmp"
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        for name in _EMBEDDED_FILES:
            src = os.path.join(bundle_dir, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(tmp_dir, name))
        fingerprint = _bundle_fingerprint(bundle_dir)
        if fingerprint:
            with open(os.path.join(tmp_dir, _RUNTIME_MARKER), "w", encoding="utf-8") as f:
                f.write(fingerprint)
        for name in os.listdir(cache_dir):
            path = os.path.join(cache_dir, name)
            if os.path.isfile(path):
                os.remove(path)
        for name in os.listdir(tmp_dir):
            shutil.move(os.path.join(tmp_dir, name), os.path.join(cache_dir, name))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return get_cached_smartctl_path() if os.path.isfile(get_cached_smartctl_path()) else None
