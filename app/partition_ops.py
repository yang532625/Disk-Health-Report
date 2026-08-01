# -*- coding: utf-8 -*-
"""Gestión nativa de particiones en Windows (Partition Manager).

Reimplementa las operaciones de particionado tipo GParted usando las APIs
nativas de almacenamiento de Windows (PowerShell Storage cmdlets / VDS),
ejecutadas de forma OCULTA (sin consolas emergentes). Todas las funciones
destructivas rechazan discos de sistema/arranque y la partición del volumen
de Windows, para proteger los datos del usuario.

Cada operación devuelve una tupla (ok: bool, info: str). En éxito, info puede
contener un dato útil (p.ej. la letra asignada); en error, una clave/mensaje.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Optional

from disk_ops import (
    _hidden_kwargs,  # noqa: F401  (reservado para futuros comandos externos)
    _normalize_storage_error,
    _parse_json,
    _ps_catch_json,
    _run_ps,
)

FILESYSTEMS = ("NTFS", "exFAT", "FAT32")
_FS_PS = {"FAT32": "FAT32", "NTFS": "NTFS", "EXFAT": "exFAT"}

# Alineación típica de particiones modernas (1 MiB). Huecos menores se ignoran.
_MIN_GAP_BYTES = 1 * 1024 * 1024
_ALIGN_BYTES = 1 * 1024 * 1024


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _fs_ps(filesystem: str) -> str:
    return _FS_PS.get((filesystem or "").upper(), "NTFS")


def _safe_label(label: str) -> str:
    return re.sub(r"[\"'`$\r\n]", "", label or "")[:32]


def normalize_letter(letter: str) -> str:
    """Devuelve una letra de unidad válida (A-Z) o cadena vacía."""
    if not letter:
        return ""
    ch = str(letter).strip().rstrip(":").upper()
    if len(ch) == 1 and "A" <= ch <= "Z":
        return ch
    return ""


def _run_op(script: str, timeout: int = 120) -> tuple[bool, str]:
    """Ejecuta un script PowerShell que produce JSON {ok, error?, ...}."""
    info = _parse_json(_run_ps(script, timeout=timeout))
    if not info or not info.get("ok"):
        return False, _normalize_storage_error((info or {}).get("error", "pm_op_failed"))
    return True, str(info.get("letter") or "").strip().rstrip(":")


def _guard_prefix(n: int, pn: Optional[int] = None) -> str:
    """Fragmento PS que aborta si el disco es de sistema/arranque o si la
    partición indicada contiene el volumen de Windows."""
    guard = (
        f"$d=Get-Disk -Number {n}; "
        "if ($d.IsSystem -or $d.IsBoot) { throw 'SYSTEM' }; "
    )
    if pn is not None:
        guard += (
            f"$p=Get-Partition -DiskNumber {n} -PartitionNumber {pn} -ErrorAction Stop; "
            "if ($p.DriveLetter) { $sys=($env:SystemDrive).TrimEnd(':'); "
            "if ([string]$p.DriveLetter -eq $sys) { throw 'SYSTEM' } }; "
        )
    return guard


# ---------------------------------------------------------------------------
# Lectura: discos + particiones + huecos no asignados
# ---------------------------------------------------------------------------
def list_disks_with_partitions() -> list[dict]:
    """Devuelve la lista de discos con sus particiones y huecos no asignados."""
    if sys.platform != "win32":
        return []

    script = (
        "$out = @(Get-Disk | Sort-Object Number | ForEach-Object { "
        "$d = $_; "
        "$parts = @(Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue | "
        "ForEach-Object { "
        "$p = $_; "
        "$vol = Get-Volume -Partition $p -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{ "
        "PartitionNumber=$p.PartitionNumber; "
        "DriveLetter=([string]$p.DriveLetter); "
        "Offset=[uint64]$p.Offset; "
        "Size=[uint64]$p.Size; "
        "Type=([string]$p.Type); "
        "IsActive=[bool]$p.IsActive; "
        "IsHidden=[bool]$p.IsHidden; "
        "GptType=([string]$p.GptType); "
        "Label=([string]$vol.FileSystemLabel); "
        "FileSystem=([string]$vol.FileSystem); "
        "SizeRemaining=([uint64]($vol.SizeRemaining)) } }); "
        "[pscustomobject]@{ "
        "Number=$d.Number; "
        "Model=([string]$d.Model).Trim(); "
        "BusType=$d.BusType.ToString(); "
        "Size=[uint64]$d.Size; "
        "PartitionStyle=$d.PartitionStyle.ToString(); "
        "IsSystem=[bool]$d.IsSystem; "
        "IsBoot=[bool]$d.IsBoot; "
        "IsReadOnly=[bool]$d.IsReadOnly; "
        "Partitions=$parts } }); "
        "ConvertTo-Json -InputObject $out -Depth 6 -Compress"
    )
    raw = _run_ps(script, timeout=60)
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        data = [data]

    disks: list[dict] = []
    for item in data:
        disks.append(_build_disk(item))
    return disks


def _build_disk(item: dict) -> dict:
    raw_parts = item.get("Partitions") or []
    if isinstance(raw_parts, dict):
        raw_parts = [raw_parts]

    partitions: list[dict] = []
    for p in raw_parts:
        size = int(p.get("Size", 0) or 0)
        remaining = int(p.get("SizeRemaining", 0) or 0)
        used = max(size - remaining, 0) if remaining else 0
        partitions.append(
            {
                "partition_number": int(p.get("PartitionNumber", 0) or 0),
                "letter": normalize_letter(p.get("DriveLetter", "")),
                "label": (p.get("Label") or "").strip(),
                "filesystem": (p.get("FileSystem") or "").strip(),
                "offset": int(p.get("Offset", 0) or 0),
                "size": size,
                "used": used,
                "free": remaining,
                "type": (p.get("Type") or "").strip(),
                "gpt_type": (p.get("GptType") or "").strip(),
                "is_active": bool(p.get("IsActive", False)),
                "is_hidden": bool(p.get("IsHidden", False)),
                "is_unallocated": False,
            }
        )

    disk_size = int(item.get("Size", 0) or 0)
    segments = _compute_segments(partitions, disk_size)

    return {
        "number": int(item.get("Number", -1)),
        "model": (item.get("Model") or "").strip(),
        "bus_type": (item.get("BusType") or "").strip(),
        "size": disk_size,
        "partition_style": (item.get("PartitionStyle") or "").strip(),
        "is_system": bool(item.get("IsSystem", False)),
        "is_boot": bool(item.get("IsBoot", False)),
        "is_readonly": bool(item.get("IsReadOnly", False)),
        "partitions": partitions,
        "segments": segments,
    }


def _compute_segments(partitions: list[dict], disk_size: int) -> list[dict]:
    """Combina particiones y huecos no asignados en orden por offset.

    Devuelve segmentos con: kind ('partition'|'unallocated'), offset, size, y
    (para particiones) una referencia 'partition_number'.
    """
    segments: list[dict] = []
    ordered = sorted(partitions, key=lambda x: x["offset"])
    cursor = _ALIGN_BYTES  # reservado al inicio (MBR/GPT headers)

    for p in ordered:
        if p["size"] <= 0:
            continue
        gap = p["offset"] - cursor
        if gap >= _MIN_GAP_BYTES:
            segments.append(
                {"kind": "unallocated", "offset": cursor, "size": gap,
                 "partition_number": None}
            )
        segments.append(
            {"kind": "partition", "offset": p["offset"], "size": p["size"],
             "partition_number": p["partition_number"]}
        )
        cursor = max(cursor, p["offset"] + p["size"])

    if disk_size > 0:
        tail = disk_size - cursor
        if tail >= _MIN_GAP_BYTES:
            segments.append(
                {"kind": "unallocated", "offset": cursor, "size": tail,
                 "partition_number": None}
            )
    return segments


def disk_has_unallocated(disk: dict) -> bool:
    return any(s["kind"] == "unallocated" for s in disk.get("segments", []))


# ---------------------------------------------------------------------------
# Operaciones de escritura
# ---------------------------------------------------------------------------
def create_partition(disk_number: int, size_mb: Optional[int], filesystem: str,
                     label: str = "", letter: str = "") -> tuple[bool, str]:
    """Crea una partición en espacio no asignado y la formatea."""
    if sys.platform != "win32":
        return False, "pm_op_failed"
    fs = _fs_ps(filesystem)
    lbl = _safe_label(label)
    let = normalize_letter(letter)

    size_part = "-UseMaximumSize" if not size_mb or size_mb <= 0 else f"-Size {int(size_mb)}MB"
    letter_part = f"-DriveLetter {let}" if let else "-AssignDriveLetter"
    label_kw = f"-NewFileSystemLabel '{lbl}' " if lbl else ""

    script = (
        "$ErrorActionPreference='Stop'; "
        f"$n={int(disk_number)}; try {{ "
        + _guard_prefix(int(disk_number))
        + f"$p=New-Partition -DiskNumber $n {size_part} {letter_part} -ErrorAction Stop; "
        f"Format-Volume -Partition $p -FileSystem {fs} {label_kw}-Force -Confirm:$false -ErrorAction Stop | Out-Null; "
        "ConvertTo-Json @{ ok=$true; letter=\"$($p.DriveLetter)\" } -Compress "
        f"}} catch {{ {_ps_catch_json()} }}"
    )
    return _run_op(script, timeout=600)


def delete_partition(disk_number: int, partition_number: int) -> tuple[bool, str]:
    """Elimina una partición (rechaza system/boot)."""
    if sys.platform != "win32":
        return False, "pm_op_failed"
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$n={int(disk_number)}; try {{ "
        + _guard_prefix(int(disk_number), int(partition_number))
        + f"Remove-Partition -DiskNumber $n -PartitionNumber {int(partition_number)} -Confirm:$false -ErrorAction Stop; "
        "ConvertTo-Json @{ ok=$true } -Compress "
        f"}} catch {{ {_ps_catch_json()} }}"
    )
    return _run_op(script, timeout=120)


def format_partition(disk_number: int, partition_number: int, filesystem: str,
                    label: str = "", quick: bool = True) -> tuple[bool, str]:
    """Formatea una partición existente (rechaza system/boot)."""
    if sys.platform != "win32":
        return False, "pm_op_failed"
    fs = _fs_ps(filesystem)
    lbl = _safe_label(label)
    label_kw = f"-NewFileSystemLabel '{lbl}' " if lbl else ""
    full = "" if quick else "-Full "
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$n={int(disk_number)}; try {{ "
        + _guard_prefix(int(disk_number), int(partition_number))
        + f"Format-Volume -Partition $p -FileSystem {fs} {label_kw}{full}-Force -Confirm:$false -ErrorAction Stop | Out-Null; "
        "ConvertTo-Json @{ ok=$true } -Compress "
        f"}} catch {{ {_ps_catch_json()} }}"
    )
    return _run_op(script, timeout=240 if quick else 3600 * 8)


def get_supported_size(disk_number: int, partition_number: int) -> tuple[int, int]:
    """Devuelve (min_bytes, max_bytes) admisibles para redimensionar."""
    if sys.platform != "win32":
        return (0, 0)
    script = (
        "$ErrorActionPreference='Stop'; try { "
        f"$s=Get-PartitionSupportedSize -DiskNumber {int(disk_number)} -PartitionNumber {int(partition_number)}; "
        "ConvertTo-Json @{ ok=$true; min=[uint64]$s.SizeMin; max=[uint64]$s.SizeMax } -Compress "
        f"}} catch {{ {_ps_catch_json()} }}"
    )
    info = _parse_json(_run_ps(script, timeout=60))
    if not info or not info.get("ok"):
        return (0, 0)
    return (int(info.get("min", 0) or 0), int(info.get("max", 0) or 0))


def resize_partition(disk_number: int, partition_number: int,
                    new_size_bytes: int) -> tuple[bool, str]:
    """Redimensiona (reduce o extiende) una partición a new_size_bytes."""
    if sys.platform != "win32":
        return False, "pm_op_failed"
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$n={int(disk_number)}; try {{ "
        + _guard_prefix(int(disk_number), int(partition_number))
        + f"Resize-Partition -DiskNumber $n -PartitionNumber {int(partition_number)} -Size {int(new_size_bytes)} -ErrorAction Stop; "
        "ConvertTo-Json @{ ok=$true } -Compress "
        f"}} catch {{ {_ps_catch_json()} }}"
    )
    return _run_op(script, timeout=600)


def set_label(disk_number: int, partition_number: int, label: str) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "pm_op_failed"
    lbl = _safe_label(label)
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$n={int(disk_number)}; try {{ "
        f"$p=Get-Partition -DiskNumber $n -PartitionNumber {int(partition_number)} -ErrorAction Stop; "
        f"Set-Volume -Partition $p -NewFileSystemLabel '{lbl}' -ErrorAction Stop; "
        "ConvertTo-Json @{ ok=$true } -Compress "
        f"}} catch {{ {_ps_catch_json()} }}"
    )
    return _run_op(script, timeout=60)


def set_drive_letter(disk_number: int, partition_number: int,
                    new_letter: str) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "pm_op_failed"
    let = normalize_letter(new_letter)
    if not let:
        return False, "pm_invalid_letter"
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$n={int(disk_number)}; try {{ "
        + _guard_prefix(int(disk_number), int(partition_number))
        + f"Set-Partition -DiskNumber $n -PartitionNumber {int(partition_number)} -NewDriveLetter {let} -ErrorAction Stop; "
        "ConvertTo-Json @{ ok=$true } -Compress "
        f"}} catch {{ {_ps_catch_json()} }}"
    )
    return _run_op(script, timeout=60)


def set_attributes(disk_number: int, partition_number: int,
                  active: Optional[bool] = None, hidden: Optional[bool] = None,
                  readonly: Optional[bool] = None,
                  no_default_letter: Optional[bool] = None) -> tuple[bool, str]:
    """Ajusta atributos avanzados. 'active' aplica a MBR; el resto a GPT."""
    if sys.platform != "win32":
        return False, "pm_op_failed"
    sets: list[str] = []
    if active is not None:
        sets.append(f"-IsActive ${'true' if active else 'false'}")
    if hidden is not None:
        sets.append(f"-IsHidden ${'true' if hidden else 'false'}")
    if readonly is not None:
        sets.append(f"-IsReadOnly ${'true' if readonly else 'false'}")
    if no_default_letter is not None:
        sets.append(f"-NoDefaultDriveLetter ${'true' if no_default_letter else 'false'}")
    if not sets:
        return False, "pm_op_failed"

    set_part = " ".join(sets)
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$n={int(disk_number)}; try {{ "
        + _guard_prefix(int(disk_number), int(partition_number))
        + f"Set-Partition -DiskNumber $n -PartitionNumber {int(partition_number)} {set_part} -ErrorAction Stop; "
        "ConvertTo-Json @{ ok=$true } -Compress "
        f"}} catch {{ {_ps_catch_json()} }}"
    )
    return _run_op(script, timeout=60)
