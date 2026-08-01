# -*- coding: utf-8 -*-
"""Rutas a recursos embebidos en el .exe (PyInstaller one-file)."""

from __future__ import annotations

import os
import sys

_DEV_ASSETS = "packaging", "assets"


def resource_path(*parts: str) -> str:
    """Resuelve un archivo empaquetado dentro del .exe o en packaging/assets en desarrollo."""
    rel = os.path.join(*parts)
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", "")
        if base:
            candidate = os.path.join(base, rel)
            if os.path.exists(candidate):
                return candidate
    root = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(root).lower() == "app":
        root = os.path.dirname(root)
    dev = os.path.join(root, *_DEV_ASSETS, rel)
    if os.path.exists(dev):
        return dev
    return os.path.join(root, rel)


def app_icon_path() -> str | None:
    for parts in (("bundled", "app.ico"), ("app.ico",)):
        path = resource_path(*parts)
        if os.path.isfile(path):
            return path
    return None


def rufus_path() -> str | None:
    """Ruta al rufus.exe empaquetado (o en packaging/assets/rufus en desarrollo)."""
    path = resource_path("rufus", "rufus.exe")
    if os.path.isfile(path):
        return path
    return None


def mas_script_path() -> str | None:
    """Ruta al MAS_AIO.cmd empaquetado (o en packaging/assets/mas en desarrollo)."""
    path = resource_path("mas", "MAS_AIO.cmd")
    if os.path.isfile(path):
        return path
    return None


def defender_remover_bundle_dir() -> str | None:
    """Directorio empaquetado de Windows Defender Remover."""
    path = resource_path("defender_remover")
    return path if os.path.isdir(path) else None


def ventoy_bundle_dir() -> str | None:
    """Directorio empaquetado de Ventoy (Ventoy2Disk + ventoy/)."""
    path = resource_path("ventoy")
    return path if os.path.isdir(path) else None


def ventoy2disk_path() -> str | None:
    """Ruta a Ventoy2Disk_X64.exe empaquetado."""
    path = resource_path("ventoy", "Ventoy2Disk_X64.exe")
    return path if os.path.isfile(path) else None
