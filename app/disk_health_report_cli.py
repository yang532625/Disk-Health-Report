# -*- coding: utf-8 -*-
"""Modo consola legacy."""

import sys

from disk_service import get_smartctl_path, get_smart_data, is_admin, scan_disks_with_info
from disk_health_report import procesar_volcado, _wait_exit


def run_cli():
    print("=" * 60)
    print("  DISK HEALTH REPORT - CLI MODE")
    print("=" * 60)

    if not is_admin():
        print("[!] Administrator privileges required.")
        _wait_exit()
        sys.exit(1)

    smartctl = get_smartctl_path()
    if not smartctl:
        print("[X] smartctl not found.")
        _wait_exit()
        sys.exit(1)

    disks = scan_disks_with_info(smartctl)
    for i, d in enumerate(disks):
        print(f"  {i + 1}) {d.path} -> {d.model} ({d.capacity})")

    try:
        sel = int(input(f"Select drive (1-{len(disks)}): ")) - 1
    except ValueError:
        sys.exit(1)

    raw = get_smart_data(smartctl, disks[sel].path)
    procesar_volcado(raw)
    _wait_exit()
