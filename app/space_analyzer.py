# -*- coding: utf-8 -*-
"""Análisis de uso de espacio en un volumen (estilo WizTree, sin MFT)."""

from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from ui_progress import clamp_pct


@dataclass
class SpaceEntry:
    name: str
    path: str
    size_bytes: int
    is_dir: bool


ProgressCallback = Callable[[int, int, float], None]


def normalize_volume_root(root: str) -> Optional[str]:
    root = (root or "").strip().strip('"')
    if not root:
        return None
    if len(root) == 2 and root[1] == ":":
        root = root + "\\"
    if not os.path.isdir(root):
        return None
    return root


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _activity_percent(files: int, dirs: int) -> float:
    return clamp_pct(min(99.0, files / 200.0 + dirs / 40.0))


def _emit_progress(
    state: dict,
    used_bytes: int,
    progress_cb: Optional[ProgressCallback],
) -> None:
    if not progress_cb:
        return
    files = state["files_seen"]
    dirs = state["dirs_seen"]
    bytes_seen = state["bytes_seen"]
    if used_bytes > 0:
        pct = clamp_pct(min(99.0, bytes_seen / used_bytes * 100.0))
    else:
        pct = _activity_percent(files, dirs)
    progress_cb(files, dirs, pct)


def _scan_directory(
    path: str,
    entries: list[SpaceEntry],
    state: dict,
    used_bytes: int,
    progress_cb: Optional[ProgressCallback],
    cancel_event: Optional[threading.Event],
) -> int:
    if cancel_event and cancel_event.is_set():
        return 0

    try:
        children = list(os.scandir(path))
    except OSError:
        return 0

    state["dirs_seen"] += 1
    if progress_cb and state["dirs_seen"] % 25 == 0:
        _emit_progress(state, used_bytes, progress_cb)

    total = 0
    for entry in children:
        if cancel_event and cancel_event.is_set():
            break
        entry_path = entry.path
        try:
            if entry.is_dir(follow_symlinks=False):
                subtotal = _scan_directory(
                    entry_path, entries, state, used_bytes, progress_cb, cancel_event,
                )
                total += subtotal
                entries.append(SpaceEntry(
                    name=entry.name,
                    path=entry_path,
                    size_bytes=subtotal,
                    is_dir=True,
                ))
            elif entry.is_file(follow_symlinks=False):
                size = _file_size(entry_path)
                state["files_seen"] += 1
                state["bytes_seen"] += size
                total += size
                entries.append(SpaceEntry(
                    name=entry.name,
                    path=entry_path,
                    size_bytes=size,
                    is_dir=False,
                ))
                if progress_cb and state["files_seen"] % 100 == 0:
                    _emit_progress(state, used_bytes, progress_cb)
        except OSError:
            continue

    return total


def scan_volume(
    root: str,
    *,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> tuple[list[SpaceEntry], int]:
    """Escanea un volumen y devuelve entradas ordenadas por tamaño (mayor primero)."""
    normalized = normalize_volume_root(root)
    if not normalized:
        return [], 0

    try:
        used_bytes = shutil.disk_usage(normalized).used
    except OSError:
        used_bytes = 0

    entries: list[SpaceEntry] = []
    state = {"files_seen": 0, "dirs_seen": 0, "bytes_seen": 0}
    if progress_cb:
        progress_cb(0, 0, 0.0)

    total_bytes = _scan_directory(
        normalized, entries, state, used_bytes, progress_cb, cancel_event,
    )

    if cancel_event and cancel_event.is_set():
        entries.clear()
        return [], 0

    entries.sort(key=lambda item: item.size_bytes, reverse=True)
    if progress_cb:
        progress_cb(state["files_seen"], state["dirs_seen"], 100.0)
    return entries, total_bytes
