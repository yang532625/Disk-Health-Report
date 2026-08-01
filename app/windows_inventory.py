# -*- coding: utf-8 -*-
"""Inventario del sistema Windows en ejecución (programas, drivers, metadatos)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Callable

import disk_ops
import win_image_job

ProgressCB = Callable[[str], None] | None

_UNINSTALL_ROOTS = (
    r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
)


def _run_ps_json(script: str, timeout: int = 120) -> Any:
    wrapped = (
        "$ErrorActionPreference='SilentlyContinue'; "
        + script
        + " | ConvertTo-Json -Depth 6 -Compress"
    )
    raw = disk_ops._run_ps(wrapped, timeout=timeout).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _parse_uninstall_entry(item: dict) -> dict[str, str] | None:
    name = (item.get("DisplayName") or "").strip()
    if not name:
        return None
    version = (item.get("DisplayVersion") or "").strip()
    publisher = (item.get("Publisher") or "").strip()
    if item.get("SystemComponent") in (1, "1", True):
        return None
    if item.get("ParentKeyName"):
        return None
    lower = name.lower()
    if lower.startswith("update for") or "security update" in lower:
        return None
    return {
        "name": name,
        "version": version,
        "publisher": publisher,
        "source": "msi",
    }


def scan_registry_programs() -> list[dict[str, str]]:
    if sys.platform != "win32":
        return []
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for root in _UNINSTALL_ROOTS:
        script = (
            f"Get-ChildItem -Path 'Registry::{root}' -ErrorAction SilentlyContinue | "
            "ForEach-Object { "
            "Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue | "
            "Select-Object DisplayName, DisplayVersion, Publisher, SystemComponent, ParentKeyName "
            "}"
        )
        data = _run_ps_json(script, timeout=90)
        if data is None:
            continue
        if isinstance(data, dict):
            data = [data]
        for item in data:
            if not isinstance(item, dict):
                continue
            parsed = _parse_uninstall_entry(item)
            if not parsed:
                continue
            key = parsed["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            entries.append(parsed)
    entries.sort(key=lambda x: x["name"].lower())
    return entries


def scan_store_apps() -> list[dict[str, str]]:
    if sys.platform != "win32":
        return []
    script = (
        "Get-AppxPackage -AllUsers -ErrorAction SilentlyContinue | "
        "Where-Object { $_.IsFramework -eq $false -and $_.SignatureKind -ne 'System' } | "
        "Select-Object Name, Version, Publisher"
    )
    data = _run_ps_json(script, timeout=120)
    if not data:
        return []
    if isinstance(data, dict):
        data = [data]
    apps: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        name = (item.get("Name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        pub = item.get("Publisher") or ""
        if isinstance(pub, dict):
            pub = str(pub)
        apps.append({
            "name": name,
            "version": str(item.get("Version") or ""),
            "publisher": str(pub)[:80],
            "source": "store",
        })
    apps.sort(key=lambda x: x["name"].lower())
    return apps


def export_winget(job_id: str) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "not_windows"
    winget = shutil.which("winget")
    if not winget:
        return False, "no_winget"
    out_path = win_image_job.winget_export_path(job_id)
    try:
        result = subprocess.run(
            [winget, "export", "-o", out_path, "--include-versions"],
            capture_output=True,
            text=True,
            timeout=300,
            **disk_ops._hidden_kwargs(),
        )
        if result.returncode != 0 or not os.path.isfile(out_path):
            return False, "winget_export_failed"
        return True, out_path
    except (OSError, subprocess.TimeoutExpired):
        return False, "winget_export_failed"


def scan_drivers() -> list[dict[str, str]]:
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            ["pnputil", "/enum-drivers"],
            capture_output=True,
            text=True,
            timeout=120,
            **disk_ops._hidden_kwargs(),
        )
        text = result.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return []
    drivers: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Published Name:"):
            if current.get("published"):
                drivers.append(current)
            current = {"published": line.split(":", 1)[-1].strip()}
        elif line.startswith("Original Name:") and current:
            current["original"] = line.split(":", 1)[-1].strip()
        elif line.startswith("Provider Name:") and current:
            current["provider"] = line.split(":", 1)[-1].strip()
    if current.get("published"):
        drivers.append(current)
    return drivers


def _system_metadata() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    script = (
        "$os = Get-CimInstance Win32_OperatingSystem; "
        "$cs = Get-CimInstance Win32_ComputerSystem; "
        "$c = Get-PSDrive -Name C -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{ "
        "Caption=$os.Caption; Version=$os.Version; BuildNumber=$os.BuildNumber; "
        "OSArchitecture=$os.OSArchitecture; "
        "ComputerName=$cs.Name; "
        "UsedBytes=[int64]($os.Size - $os.FreePhysicalMemory*1024); "
        "TotalBytes=[int64]$os.Size; "
        "CUsed=[int64]($c.Used); CFree=[int64]($c.Free) }"
    )
    data = _run_ps_json(script, timeout=30)
    return data if isinstance(data, dict) else {}


def _exportable_config_paths() -> list[str]:
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Themes"),
    ]
    return [p for p in candidates if p and os.path.isdir(p)]


def run_inventory(job_id: str, progress_cb: ProgressCB = None) -> dict[str, Any]:
    def log(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    log("inventory_registry")
    registry = scan_registry_programs()
    log("inventory_store")
    store = scan_store_apps()
    log("inventory_drivers")
    drivers = scan_drivers()
    log("inventory_metadata")
    meta = _system_metadata()

    winget_ok = False
    winget_path = ""
    log("inventory_winget")
    winget_ok, winget_path = export_winget(job_id)

    inventory: dict[str, Any] = {
        "programs": registry,
        "store_apps": store,
        "drivers": drivers,
        "metadata": meta,
        "config_paths": _exportable_config_paths(),
        "program_count": len(registry) + len(store),
        "winget_export": winget_path if winget_ok else None,
    }

    inv_path = win_image_job.inventory_path(job_id)
    os.makedirs(os.path.dirname(inv_path), exist_ok=True)
    with open(inv_path, "w", encoding="utf-8") as fh:
        json.dump(inventory, fh, indent=2, ensure_ascii=False)

    return inventory


def merge_program_lists(registry: list[dict], store: list[dict]) -> list[dict]:
    """Lista unificada para la UI."""
    combined = list(registry) + list(store)
    combined.sort(key=lambda x: x.get("name", "").lower())
    return combined
