# -*- coding: utf-8 -*-
"""Operaciones de disco en Windows: resolver disco fisico, abrir explorador,
extraccion segura (expulsar) y lanzar Rufus. Todo de forma defensiva: si no se
puede identificar el disco con certeza, se considera 'del sistema' (protegido)."""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

from bundled_assets import rufus_path
from disk_service import DiskInfo, disk_identity
@dataclass
class EjectedDiskRecord:
    """Disco expulsado lógicamente pero aún conectado físicamente."""
    disk: DiskInfo
    disk_number: int
    letters: list[str]
    identity: str

_PS_TIMEOUT = 15
_disk_cache: tuple[float, list[dict]] | None = None
_CACHE_TTL = 4.0


@dataclass
class WinDisk:
    number: int
    serial: str
    model: str
    bus_type: str
    is_system: bool
    is_boot: bool
    letters: list[str]
    removable: bool


def _hidden_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    kwargs: dict = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


def _run_ps(script: str, timeout: int = _PS_TIMEOUT) -> str:
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            **_hidden_kwargs(),
        )
        return result.stdout
    except Exception:
        return ""


def _norm(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").lower()


def _list_physical_disks() -> list[dict]:
    """Devuelve la lista de discos fisicos via Storage cmdlets (con cache corto)."""
    global _disk_cache
    now = time.monotonic()
    if _disk_cache and (now - _disk_cache[0]) < _CACHE_TTL:
        return _disk_cache[1]

    script = (
        "$out = @(Get-Disk | ForEach-Object { "
        "$d = $_; "
        "$letters = @(Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DriveLetter } | ForEach-Object { \"$($_.DriveLetter):\" }); "
        "[pscustomobject]@{ Number=$d.Number; "
        "Serial=([string]$d.SerialNumber).Trim(); "
        "Model=([string]$d.Model).Trim(); "
        "BusType=$d.BusType.ToString(); "
        "IsSystem=[bool]$d.IsSystem; IsBoot=[bool]$d.IsBoot; "
        "Size=[int64]$d.Size; "
        "Letters=$letters } }); "
        "ConvertTo-Json -InputObject $out -Depth 4 -Compress"
    )
    raw = _run_ps(script)
    disks: list[dict] = []
    if raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                letters = item.get("Letters") or []
                if isinstance(letters, str):
                    letters = [letters]
                disks.append(
                    {
                        "number": int(item.get("Number", -1)),
                        "serial": (item.get("Serial") or "").strip(),
                        "model": (item.get("Model") or "").strip(),
                        "bus_type": (item.get("BusType") or "").strip(),
                        "is_system": bool(item.get("IsSystem", False)),
                        "is_boot": bool(item.get("IsBoot", False)),
                        "size": int(item.get("Size") or 0),
                        "letters": [str(x) for x in letters if x],
                    }
                )
        except (ValueError, TypeError):
            disks = []

    _disk_cache = (now, disks)
    return disks


def _disk_number_from_path(path: str) -> Optional[int]:
    match = re.search(r"/dev/pd(\d+)", path or "", re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"/dev/sd([a-z])", path or "", re.IGNORECASE)
    if match:
        return ord(match.group(1).lower()) - ord("a")
    match = re.search(r"physicaldrive(\d+)", path or "", re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def resolve_windows_disk(disk) -> Optional[WinDisk]:
    """Empareja un DiskInfo (de smartctl) con un disco fisico de Windows.
    Primero por numero de serie; si falla, por el indice de /dev/pdN."""
    physical = _list_physical_disks()
    if not physical:
        return None

    target_serial = _norm(getattr(disk, "serial", ""))
    matched: Optional[dict] = None

    if target_serial:
        for pd in physical:
            ser = _norm(pd["serial"])
            if ser and (ser == target_serial or ser in target_serial or target_serial in ser):
                matched = pd
                break

    if matched is None:
        number = _disk_number_from_path(getattr(disk, "path", ""))
        if number is not None:
            for pd in physical:
                if pd["number"] == number:
                    matched = pd
                    break

    if matched is None:
        return None

    bus = matched["bus_type"]
    return WinDisk(
        number=matched["number"],
        serial=matched["serial"],
        model=matched["model"],
        bus_type=bus,
        is_system=matched["is_system"],
        is_boot=matched["is_boot"],
        letters=matched["letters"],
        removable=(bus.upper() == "USB"),
    )


def is_system_disk(disk) -> bool:
    """True si el disco contiene Windows/boot. Si no se puede resolver, True (seguro)."""
    win = resolve_windows_disk(disk)
    if win is None:
        return True
    return win.is_system or win.is_boot


def get_drive_letters(disk) -> list[str]:
    win = resolve_windows_disk(disk)
    return win.letters if win else []


def can_eject(disk) -> bool:
    win = resolve_windows_disk(disk)
    if win is None:
        return False
    return win.removable and not (win.is_system or win.is_boot)


def open_in_explorer(disk) -> bool:
    """Abre la primera unidad del disco en el Explorador. Si no tiene letra,
    abre 'Este equipo'."""
    letters = get_drive_letters(disk)
    try:
        if letters:
            os.startfile(letters[0] + "\\")
        else:
            subprocess.Popen(["explorer.exe", "shell:MyComputerFolder"], **_hidden_kwargs())
        return True
    except Exception:
        try:
            subprocess.Popen(["explorer.exe"], **_hidden_kwargs())
            return True
        except Exception:
            return False


_GUID_DEVINTERFACE_DISK = (
    0x53F56307, 0xB6BF, 0x11D0, (0x94, 0xF2, 0x00, 0xA0, 0xC9, 0x1E, 0xFB, 0x8B)
)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", _GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", _GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _STORAGE_DEVICE_NUMBER(ctypes.Structure):
    _fields_ = [
        ("DeviceType", wintypes.DWORD),
        ("DeviceNumber", wintypes.DWORD),
        ("PartitionNumber", wintypes.DWORD),
    ]


def _make_guid(d1, d2, d3, d4) -> _GUID:
    g = _GUID()
    g.Data1, g.Data2, g.Data3 = d1, d2, d3
    for i, b in enumerate(d4):
        g.Data4[i] = b
    return g


def _eject_by_device_number(device_number: int) -> bool:
    """Extraccion segura real via CM_Request_Device_Eject (Quitar hardware con seguridad).
    Funciona aunque el disco USB se presente como fijo (sin bit 'removable')."""
    if sys.platform != "win32":
        return False

    setupapi = ctypes.windll.setupapi
    cfgmgr32 = ctypes.windll.cfgmgr32
    kernel32 = ctypes.windll.kernel32

    setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    setupapi.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(_GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD
    ]
    setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_GUID),
        wintypes.DWORD, ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
    ]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(_SP_DEVINFO_DATA),
    ]
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    kernel32.DeviceIoControl.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    cfgmgr32.CM_Get_Parent.argtypes = [
        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.ULONG
    ]
    cfgmgr32.CM_Request_Device_EjectW.argtypes = [
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
        wintypes.ULONG, wintypes.ULONG,
    ]

    DIGCF_PRESENT = 0x2
    DIGCF_DEVICEINTERFACE = 0x10
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    OPEN_EXISTING = 3
    IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x2D1080
    CR_SUCCESS = 0
    INVALID_HANDLE = wintypes.HANDLE(-1).value

    guid = _make_guid(*_GUID_DEVINTERFACE_DISK)
    hdev = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if not hdev or hdev == INVALID_HANDLE:
        return False

    found_devinst = None
    cb = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
    try:
        idx = 0
        did = _SP_DEVICE_INTERFACE_DATA()
        did.cbSize = ctypes.sizeof(_SP_DEVICE_INTERFACE_DATA)
        while setupapi.SetupDiEnumDeviceInterfaces(
            hdev, None, ctypes.byref(guid), idx, ctypes.byref(did)
        ):
            idx += 1
            req = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(did), None, 0, ctypes.byref(req), None
            )
            if req.value == 0:
                continue
            buf = ctypes.create_string_buffer(req.value)
            ctypes.memmove(buf, ctypes.byref(wintypes.DWORD(cb)), 4)
            devinfo = _SP_DEVINFO_DATA()
            devinfo.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(did), buf, req.value, None, ctypes.byref(devinfo)
            ):
                continue
            device_path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            handle = kernel32.CreateFileW(
                device_path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, 0, None,
            )
            if not handle or handle == INVALID_HANDLE:
                continue
            try:
                sdn = _STORAGE_DEVICE_NUMBER()
                returned = wintypes.DWORD(0)
                ok = kernel32.DeviceIoControl(
                    handle, IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0,
                    ctypes.byref(sdn), ctypes.sizeof(sdn), ctypes.byref(returned), None,
                )
                if ok and sdn.DeviceNumber == device_number:
                    found_devinst = devinfo.DevInst
                    break
            finally:
                kernel32.CloseHandle(handle)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)

    if found_devinst is None:
        return False

    devinst = found_devinst
    for _ in range(8):
        parent = wintypes.DWORD(0)
        if cfgmgr32.CM_Get_Parent(ctypes.byref(parent), devinst, 0) != CR_SUCCESS:
            break
        veto_type = wintypes.DWORD(0)
        veto_name = ctypes.create_unicode_buffer(260)
        cr = cfgmgr32.CM_Request_Device_EjectW(
            parent, ctypes.byref(veto_type), veto_name, 260, 0
        )
        if cr == CR_SUCCESS and veto_type.value == 0:
            return True
        devinst = parent.value
    return False


def safe_eject(disk) -> bool:
    """Extraccion segura de un disco USB. Usa la API real de Windows
    (CM_Request_Device_Eject); como respaldo intenta el verbo del shell."""
    win = resolve_windows_disk(disk)
    if win is None or win.is_system or win.is_boot or not win.removable:
        return False

    # Metodo principal: API de Windows por numero de disco fisico.
    try:
        if _eject_by_device_number(win.number):
            _invalidate_cache()
            return True
    except Exception:
        pass

    # Respaldo: verbo Eject del shell (solo sirve en medios extraibles tipo flash).
    if win.letters:
        letter = win.letters[0]
        script = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "$sh = New-Object -ComObject Shell.Application; "
            f"$item = $sh.Namespace(17).ParseName('{letter}'); "
            "if ($item) { $item.InvokeVerb('Eject') }"
        )
        _run_ps(script)
        time.sleep(1.5)
        if letter not in get_drive_letters_fresh(disk):
            return True
    return False


def remount_disk(record: EjectedDiskRecord) -> bool:
    """Vuelve a montar un disco previamente expulsado (online + letra de unidad)."""
    n = record.disk_number
    preferred = [x.rstrip(":").upper() for x in record.letters if x]
    letters_json = ",".join(f'"{c}"' for c in preferred) or ""
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        f"$n = {n}; "
        f"$preferred = @({letters_json}); "
        "$disk = Get-Disk -Number $n -ErrorAction SilentlyContinue; "
        "if (-not $disk) { exit 1 }; "
        "if ($disk.IsOffline) { Set-Disk -Number $n -IsOffline $false }; "
        "if ($disk.IsReadOnly) { Set-Disk -Number $n -IsReadOnly $false }; "
        "Update-HostStorageCache | Out-Null; "
        "$parts = @(Get-Partition -DiskNumber $n -ErrorAction SilentlyContinue); "
        "if ($parts.Count -eq 0) { exit 2 }; "
        "$idx = 0; "
        "foreach ($p in $parts) { "
        "  if ($p.DriveLetter) { continue }; "
        "  $letter = $null; "
        "  if ($idx -lt $preferred.Count) { $letter = $preferred[$idx] }; "
        "  if (-not $letter) { "
        "    foreach ($code in 68..90) { "
        "      $c = [char]$code; "
        "      if (-not (Get-Partition -DriveLetter $c -ErrorAction SilentlyContinue)) { "
        "        $letter = $c; break "
        "      } "
        "    } "
        "  }; "
        "  if ($letter) { "
        "    Set-Partition -DiskNumber $n -PartitionNumber $p.PartitionNumber "
        "      -NewDriveLetter $letter -ErrorAction SilentlyContinue | Out-Null; "
        "    $idx++ "
        "  } "
        "}; "
        "$mounted = @(Get-Partition -DiskNumber $n -ErrorAction SilentlyContinue | "
        "  Where-Object { $_.DriveLetter }); "
        "if ($mounted.Count -gt 0) { exit 0 } else { exit 3 }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            capture_output=True,
            text=True,
            timeout=25,
            **_hidden_kwargs(),
        )
        if result.returncode == 0:
            _invalidate_cache()
            return True
    except Exception:
        pass

    # Respaldo: diskpart online + assign
    letters = preferred or ["E"]
    for letter in letters:
        dp_script = (
            f"select disk {n}\n"
            "online disk\n"
            "attributes disk clear readonly\n"
            f"select partition 1\n"
            f"assign letter={letter}\n"
        )
        try:
            proc = subprocess.run(
                ["diskpart"],
                input=dp_script,
                capture_output=True,
                text=True,
                timeout=20,
                **_hidden_kwargs(),
            )
            if proc.returncode == 0:
                _invalidate_cache()
                fresh = get_drive_letters(record.disk)
                if fresh:
                    return True
        except Exception:
            continue
    return False


def make_ejected_record(disk, win: WinDisk) -> EjectedDiskRecord:
    return EjectedDiskRecord(
        disk=disk,
        disk_number=win.number,
        letters=list(win.letters),
        identity=disk_identity(disk),
    )


def _invalidate_cache() -> None:
    global _disk_cache
    _disk_cache = None


def get_drive_letters_fresh(disk) -> list[str]:
    _invalidate_cache()
    return get_drive_letters(disk)


def _usage_from_drive_letters(letters: list[str]) -> Optional[tuple[int, int, float]]:
    """Uso agregado vía shutil.disk_usage (stats en vivo del sistema de archivos)."""
    total = 0
    used = 0
    for letter in letters:
        root = letter if letter.endswith("\\") else f"{letter.rstrip(':')}:\\"
        try:
            du = shutil.disk_usage(root)
        except OSError:
            continue
        total += int(du.total)
        used += int(du.used)
    if total <= 0:
        return None
    used = max(0, min(used, total))
    return used, total, (used / total) * 100.0


def get_disk_usage(disk) -> Optional[tuple[int, int, float]]:
    """Devuelve (usado, total, porcentaje) del disco fisico, o None si no se
    puede medir (sin volumen montado). Prefiere shutil.disk_usage cuando hay
    letra de unidad (actualización en vivo); si no, PowerShell sobre volumenes."""
    win = resolve_windows_disk(disk)
    if win is None:
        return None
    if win.letters:
        live = _usage_from_drive_letters(win.letters)
        if live is not None:
            return live
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        f"$n={win.number}; "
        "$disk = Get-Disk -Number $n; "
        "$physical = [int64]$disk.Size; "
        "$volTotal = [int64]0; "
        "$used = [int64]0; $have = $false; "
        "Get-Partition -DiskNumber $n | ForEach-Object { "
        "$v = $_ | Get-Volume; "
        "if ($v -and $v.Size -gt 0) { $have = $true; "
        "$volTotal += [int64]$v.Size; "
        "$used += ([int64]$v.Size - [int64]$v.SizeRemaining) } }; "
        "$total = if ($volTotal -gt 0) { $volTotal } else { $physical }; "
        "[pscustomobject]@{ Total=$total; Used=$used; Have=$have } | "
        "ConvertTo-Json -Compress"
    )
    info = _parse_json(_run_ps(script, timeout=8))
    if not info:
        return None
    try:
        total = int(info.get("Total") or 0)
        used = int(info.get("Used") or 0)
        have = bool(info.get("Have", False))
    except (ValueError, TypeError):
        return None
    if total <= 0 or not have:
        return None
    used = max(0, min(used, total))
    percent = (used / total) * 100.0
    return used, total, percent


def _runtime_rufus_path() -> Optional[str]:
    """Copia rufus.exe a una carpeta temporal estable y devuelve su ruta."""
    src = rufus_path()
    if not src or not os.path.isfile(src):
        return None
    if not getattr(sys, "frozen", False):
        return src
    dest_dir = os.path.join(tempfile.gettempdir(), "DiskHealthReport", "rufus")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "rufus.exe")
    try:
        if not os.path.isfile(dest) or os.path.getsize(dest) != os.path.getsize(src):
            shutil.copy2(src, dest)
    except OSError:
        return src
    return dest


def launch_rufus() -> bool:
    """Lanza Rufus (empaquetado). Devuelve True si se inicio."""
    exe = _runtime_rufus_path()
    if not exe:
        return False
    try:
        os.startfile(exe)
        return True
    except OSError:
        try:
            subprocess.Popen([exe], **_hidden_kwargs())
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Formateo nativo de discos (sin Rufus). Usa Storage cmdlets y diskpart de
# respaldo. Solo discos que NO sean del sistema/arranque.
# ---------------------------------------------------------------------------

FILESYSTEMS = ("NTFS", "exFAT", "FAT32")
SCHEMES = ("MBR", "GPT")

_FORMAT_STAGE_FRACTIONS = {
    "checking": 0.10,
    "partitioning": 0.40,
    "formatting": 0.75,
    "retry_mbr": 0.55,
    "done": 1.0,
}


def _is_vds_error(msg: str) -> bool:
    return "virtual disk service" in (msg or "").lower()


def _is_usb_disk(number: int) -> bool:
    pd = _get_disk_fresh(number)
    if pd is None:
        return False
    return (pd.get("bus_type") or "").upper() == "USB"


def _disk_size_gb(number: int) -> Optional[float]:
    pd = _get_disk_fresh(number)
    if pd is None:
        return None
    size = pd.get("size") or 0
    if size <= 0:
        return None
    return size / (1024 ** 3)


def _parse_json(raw: str) -> Optional[dict]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def _get_disk_fresh(number: int) -> Optional[dict]:
    _invalidate_cache()
    for pd in _list_physical_disks():
        if pd["number"] == number:
            return pd
    return None


def _ps_catch_json() -> str:
    """PowerShell catch block that serializes full VDS/Storage error text."""
    return (
        "$msg = [string]$_.Exception.Message; "
        "if ($_.Exception.InnerException) { "
        "$msg = ($msg + ' ' + [string]$_.Exception.InnerException.Message).Trim() }; "
        "if ($_.ErrorDetails.Message) { "
        "$msg = ($msg + ' ' + [string]$_.ErrorDetails.Message).Trim() }; "
        "ConvertTo-Json @{ ok=$false; error=$msg } -Compress"
    )


def _normalize_storage_error(msg: str) -> str:
    text = (msg or "").strip()
    while text.endswith(":"):
        text = text[:-1].strip()
    return text or "format_failed"


def _note_format_error(errors: list[str], source: str, msg: str) -> None:
    if msg in ("system", "SYSTEM"):
        return
    text = _normalize_storage_error(msg or "format_failed")
    line = f"{source}: {text}"
    if line not in errors:
        errors.append(line)


def _combine_format_errors(errors: list[str]) -> str:
    if not errors:
        return "format_failed"
    return "\n".join(errors)


def _diskpart_remove_letters(number: int) -> None:
    """Quita letras de unidad vía diskpart (fallback sin cmdlets Storage)."""
    list_script = f"select disk {number}\r\nlist volume\r\n"
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="ascii", errors="ignore") as fh:
            fh.write(list_script)
        result = subprocess.run(
            ["diskpart", "/s", tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
            **_hidden_kwargs(),
        )
        out = (result.stdout or "") + (result.stderr or "")
    except Exception:
        return
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    remove_lines = [f"select disk {number}"]
    for raw in out.splitlines():
        line = raw.strip()
        if not line.startswith("Volume ") or "Volume ###" in line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        vol_num = parts[1]
        letter = parts[2]
        if len(letter) == 1 and letter.isalpha():
            remove_lines.extend([
                f"select volume {vol_num}",
                f"remove letter={letter.upper()}",
            ])
    if len(remove_lines) <= 1:
        return

    remove_lines.append("exit")
    script_remove = "\r\n".join(remove_lines) + "\r\n"
    tmp_remove = None
    try:
        fd, tmp_remove = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="ascii", errors="ignore") as fh:
            fh.write(script_remove)
        subprocess.run(
            ["diskpart", "/s", tmp_remove],
            capture_output=True,
            text=True,
            timeout=60,
            **_hidden_kwargs(),
        )
    except Exception:
        pass
    finally:
        if tmp_remove:
            try:
                os.unlink(tmp_remove)
            except OSError:
                pass


def _run_diskpart_script(lines: list[str], timeout: int = 60) -> str:
    """Ejecuta diskpart con las líneas indicadas y devuelve stdout+stderr."""
    script = "\r\n".join(lines + ["exit"]) + "\r\n"
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="ascii", errors="ignore") as fh:
            fh.write(script)
        result = subprocess.run(
            ["diskpart", "/s", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            **_hidden_kwargs(),
        )
        return ((result.stdout or "") + (result.stderr or "")).strip()
    except Exception:
        return ""
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _diskpart_offline_online(number: int) -> None:
    """Ciclo offline/online y quita readonly vía diskpart (libera handles VDS)."""
    _run_diskpart_script([
        f"select disk {number}",
        "attributes disk clear readonly noerr",
        "offline disk noerr",
        "online disk noerr",
        "attributes disk clear readonly noerr",
    ])


def _release_disk_access(number: int) -> tuple[bool, str]:
    """Libera disco USB (Rufus/Ventoy): quita letras y desmonta sin depender de Dismount-Volume."""
    catch_json = _ps_catch_json()
    script = (
        "Import-Module Storage -ErrorAction SilentlyContinue; "
        "$ErrorActionPreference='Continue'; "
        f"$n={number}; "
        "try { "
        "$d=Get-Disk -Number $n -ErrorAction Stop; "
        "if ($d.IsSystem -or $d.IsBoot) { throw 'SYSTEM' }; "
        "Set-Disk -Number $n -IsReadOnly $false -ErrorAction SilentlyContinue; "
        "Set-Disk -Number $n -IsOffline $false -ErrorAction SilentlyContinue; "
        "$hasDismount = [bool](Get-Command Dismount-Volume -ErrorAction SilentlyContinue); "
        "Get-Partition -DiskNumber $n -ErrorAction SilentlyContinue | ForEach-Object { "
        "  $part=$_; "
        "  if ($part.DriveLetter) { "
        "    Remove-PartitionAccessPath -DiskNumber $n -PartitionNumber $part.PartitionNumber "
        "      -AccessPath ($part.DriveLetter.ToString()+':\\') -ErrorAction SilentlyContinue "
        "  }; "
        "  if ($hasDismount) { "
        "    $vol=Get-Volume -Partition $part -ErrorAction SilentlyContinue; "
        "    if ($vol) { "
        "      Dismount-Volume -UniqueId $vol.UniqueId -ErrorAction SilentlyContinue "
        "    } "
        "  } "
        "}; "
        "Start-Sleep -Milliseconds 400; "
        "ConvertTo-Json @{ ok=$true } -Compress "
        f"}} catch {{ {catch_json} }}"
    )
    info = _parse_json(_run_ps(script, timeout=90))
    if not info or not info.get("ok"):
        err = (info or {}).get("error", "")
        if err == "SYSTEM":
            return False, "system"
        return False, _normalize_storage_error(err or "Volume is in use")

    letters_script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        f"@(Get-Partition -DiskNumber {number} | Where-Object {{ $_.DriveLetter }} | "
        "ForEach-Object { $_.DriveLetter.ToString() }) -join ','"
    )
    remaining = (_run_ps(letters_script, timeout=30) or "").strip()
    if remaining:
        _diskpart_remove_letters(number)
        time.sleep(0.4)

    _diskpart_offline_online(number)
    time.sleep(0.4)

    remaining = (_run_ps(letters_script, timeout=30) or "").strip()
    if remaining:
        _diskpart_remove_letters(number)
        time.sleep(0.4)
    return True, ""


def prepare_disk_for_format(number: int) -> tuple[bool, str]:
    """Desmonta volúmenes y quita letras antes de formatear (evita errores VDS)."""
    return _release_disk_access(number)


def prepare_disk_for_ventoy(number: int) -> tuple[bool, str]:
    """Desbloquea el disco y quita letras de unidad antes de instalar Ventoy."""
    catch_json = _ps_catch_json()
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$n={number}; "
        "try { "
        "$d=Get-Disk -Number $n -ErrorAction Stop; "
        "if ($d.IsSystem -or $d.IsBoot) { throw 'SYSTEM' }; "
        "Set-Disk -Number $n -IsReadOnly $false -ErrorAction SilentlyContinue; "
        "Set-Disk -Number $n -IsOffline $false -ErrorAction SilentlyContinue; "
        "Get-Partition -DiskNumber $n -ErrorAction SilentlyContinue | ForEach-Object { "
        "  $part=$_; "
        "  if ($part.DriveLetter) { "
        "    Remove-PartitionAccessPath -DiskNumber $n -PartitionNumber $part.PartitionNumber "
        "      -AccessPath ($part.DriveLetter.ToString()+':\\') -ErrorAction SilentlyContinue "
        "  } "
        "}; "
        "ConvertTo-Json @{ ok=$true } -Compress "
        f"}} catch {{ {catch_json} }}"
    )
    info = _parse_json(_run_ps(script, timeout=60))
    if not info or not info.get("ok"):
        err = (info or {}).get("error", "")
        if err == "SYSTEM":
            return False, "ventoy_system_disk"
        return False, _normalize_storage_error(err or "Volume is in use")
    return True, ""


def disk_has_ventoy(number: int) -> bool:
    """Heurística MBR/GPT: etiqueta Ventoy o layout EFI + partición de datos."""
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        f"$n={number}; "
        "$parts=@(Get-Partition -DiskNumber $n -ErrorAction SilentlyContinue); "
        "if ($parts.Count -lt 1) { 'false'; return }; "
        "foreach ($p in $parts) { "
        "  $vol=Get-Volume -Partition $p -ErrorAction SilentlyContinue; "
        "  if ($vol -and $vol.FileSystemLabel -match '(?i)ventoy|vtoy') { 'true'; return }; "
        "}; "
        "$efi=$parts | Where-Object { "
        "  $_.Type -eq 'System' -or "
        "  $_.GptType -eq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' "
        "}; "
        "$data=$parts | Where-Object { $_.PartitionNumber -ge 2 } | Select-Object -First 1; "
        "if ($efi -and $data -and $parts.Count -ge 2) { "
        "  $v=Get-Volume -Partition $data -ErrorAction SilentlyContinue; "
        "  if ($v -and $v.FileSystem -in @('exFAT','NTFS','FAT32','UDF')) { 'true'; return }; "
        "}; "
        "'false'"
    )
    out = _run_ps(script, timeout=30).strip().lower()
    return out == "true" or out.endswith("true")


def _format_via_storage(number, scheme, fs_ps, label, quick, report=None) -> tuple[bool, str]:
    label_part = f"-NewFileSystemLabel '{label}' " if label else ""
    catch_json = _ps_catch_json()
    script_a = (
        "$ErrorActionPreference='Stop'; "
        f"$n={number}; "
        "try { "
        "$d=Get-Disk -Number $n; "
        "if ($d.IsSystem -or $d.IsBoot) { throw 'SYSTEM' }; "
        "Set-Disk -Number $n -IsReadOnly $false -ErrorAction SilentlyContinue; "
        "Set-Disk -Number $n -IsOffline $false -ErrorAction SilentlyContinue; "
        "Get-Partition -DiskNumber $n -ErrorAction SilentlyContinue | ForEach-Object { "
        "Remove-Partition -DiskNumber $n -PartitionNumber $_.PartitionNumber -Confirm:$false -ErrorAction SilentlyContinue }; "
        "$d=Get-Disk -Number $n; "
        "if ($d.PartitionStyle -ne 'RAW') { Clear-Disk -Number $n -RemoveData -RemoveOEM -Confirm:$false -ErrorAction Stop }; "
        "$d=Get-Disk -Number $n; "
        "if ($d.PartitionStyle -eq 'RAW') { "
        f"Initialize-Disk -Number $n -PartitionStyle {scheme} -ErrorAction Stop; "
        "}; "
        "$npArgs=@{ DiskNumber=$n; UseMaximumSize=$true; AssignDriveLetter=$true }; "
        "if ((Get-Command New-Partition).Parameters.ContainsKey('PartitionType')) { "
        "$npArgs['PartitionType']='Basic' }; "
        "$p=New-Partition @npArgs -ErrorAction Stop; "
        "ConvertTo-Json @{ ok=$true; letter=\"$($p.DriveLetter)\" } -Compress "
        f"}} catch {{ {catch_json} }}"
    )
    info = _parse_json(_run_ps(script_a, timeout=120))
    if not info or not info.get("ok"):
        return False, _normalize_storage_error((info or {}).get("error", "format_failed"))
    letter = (str(info.get("letter") or "")).strip().rstrip(":")
    if not letter:
        return False, "no_letter"

    if report:
        report("formatting", 0.75)
    full = "" if quick else "-Full "
    script_b = (
        "$ErrorActionPreference='Stop'; "
        "try { "
        f"Format-Volume -DriveLetter {letter} -FileSystem {fs_ps} {label_part}{full}-Force -Confirm:$false -ErrorAction Stop | Out-Null; "
        "ConvertTo-Json @{ ok=$true } -Compress "
        f"}} catch {{ {catch_json} }}"
    )
    fmt_timeout = 240 if quick else 3600 * 8
    info = _parse_json(_run_ps(script_b, timeout=fmt_timeout))
    if not info or not info.get("ok"):
        return False, _normalize_storage_error((info or {}).get("error", "format_failed"))
    return True, letter


def _diskpart_assigned_letter(number: int) -> str:
    """Obtiene la letra de unidad tras diskpart assign."""
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        f"$p=Get-Partition -DiskNumber {number} | "
        "Where-Object { $_.DriveLetter } | Select-Object -First 1; "
        "if ($p) { $p.DriveLetter }"
    )
    raw = (_run_ps(script, timeout=30) or "").strip()
    return raw.rstrip(":")


def _extract_diskpart_error(output: str) -> str:
    """Extrae el mensaje de error más relevante de la salida de diskpart."""
    if not output:
        return "format_failed"
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    markers = (
        "there is no volume",
        "virtual disk service error",
        "diskpart has encountered an error",
        "error",
        "failed",
    )
    for line in reversed(lines):
        low = line.lower()
        if any(m in low for m in markers):
            return line
    if lines:
        return "\n".join(lines[-3:])
    return "format_failed"


def _diskpart_output_failed(output: str) -> bool:
    if not output:
        return False
    text = output.lower()
    return any(
        m in text for m in (
            "there is no volume",
            "virtual disk service error",
            "diskpart has encountered an error",
        )
    )


def _format_via_diskpart(number, scheme, fs_dp, label, quick, clean_all=False) -> tuple[bool, str]:
    conv = "gpt" if scheme.upper() == "GPT" else "mbr"
    quick_kw = "quick" if quick else ""
    lbl = re.sub(r'["\r\n]', "", label or "")[:32]
    label_part = f'label="{lbl}"' if lbl else ""
    clean_cmd = "clean all" if clean_all else "clean"
    lines = [
        f"select disk {number}",
        "attributes disk clear readonly noerr",
        "offline disk noerr",
        "online disk noerr",
        "attributes disk clear readonly noerr",
        clean_cmd,
        "online disk noerr",
        f"convert {conv}",
        "create partition primary",
        "select partition 1",
        "attributes volume clear readonly noerr",
        " ".join(filter(None, [f"format fs={fs_dp}", label_part, quick_kw])).strip(),
        "assign",
    ]
    timeout = 240 if quick else 3600 * 8
    if clean_all and quick:
        timeout = max(timeout, 600)
    try:
        out = _run_diskpart_script(lines, timeout=timeout)
        if not _diskpart_output_failed(out):
            letter = _diskpart_assigned_letter(number)
            return True, letter or ""
        return False, _extract_diskpart_error(out)
    except Exception as e:
        return False, str(e) or "format_failed"


def format_disk(number, scheme="MBR", filesystem="NTFS", label="", quick=True,
                progress_cb=None) -> tuple[bool, str]:
    """Formatea (borra) un disco completo de forma nativa.
    Devuelve (ok, info). info = letra asignada si ok, o texto/clave de error."""
    if sys.platform != "win32":
        return False, "format_failed"

    from disk_service import is_admin
    if not is_admin():
        return False, "format_not_admin"

    def report(stage, fraction=None):
        if fraction is None:
            fraction = _FORMAT_STAGE_FRACTIONS.get(stage)
        if progress_cb:
            try:
                progress_cb(stage, fraction)
            except Exception:
                pass

    scheme = (scheme or "MBR").upper()
    if scheme not in SCHEMES:
        scheme = "MBR"
    fs_norm = (filesystem or "NTFS").upper()
    fs_ps = {"FAT32": "FAT32", "NTFS": "NTFS", "EXFAT": "exFAT"}.get(fs_norm, "NTFS")
    fs_dp = {"FAT32": "fat32", "NTFS": "ntfs", "EXFAT": "exfat"}.get(fs_norm, "ntfs")
    safe_label = re.sub(r"[\"'`$\r\n]", "", label or "")[:32]

    report("checking")
    pd = _get_disk_fresh(number)
    if pd is None:
        return False, "no_disk"
    if pd["is_system"] or pd["is_boot"]:
        return False, "system"

    is_usb = (pd.get("bus_type") or "").upper() == "USB"

    prep_ok, prep_detail = prepare_disk_for_format(number)
    if not prep_ok:
        return False, prep_detail

    errors: list[str] = []
    ok = False
    info = "format_failed"

    report("partitioning")
    if is_usb:
        ok, info = _format_via_diskpart(number, scheme, fs_dp, safe_label, quick)
        if not ok:
            if info in ("system", "SYSTEM"):
                return False, info
            _note_format_error(errors, "diskpart", info)
            report("formatting")
            ok, info = _format_via_storage(
                number, scheme, fs_ps, safe_label, quick, report=report,
            )
            if not ok:
                if info in ("system", "SYSTEM"):
                    return False, info
                _note_format_error(errors, "storage", info)
    else:
        ok, info = _format_via_storage(
            number, scheme, fs_ps, safe_label, quick, report=report,
        )
        if not ok:
            if info in ("system", "SYSTEM"):
                return False, info
            _note_format_error(errors, "storage", info)
            report("formatting")
            ok, info = _format_via_diskpart(number, scheme, fs_dp, safe_label, quick)
            if not ok:
                _note_format_error(errors, "diskpart", info)

    if not ok and _is_vds_error(info):
        report("formatting")
        ok, info = _format_via_diskpart(
            number, scheme, fs_dp, safe_label, quick, clean_all=True,
        )
        if not ok:
            _note_format_error(errors, "diskpart (clean all)", info)
            if not ok and scheme == "GPT" and is_usb:
                size_gb = _disk_size_gb(number)
                if size_gb is None or size_gb <= 64:
                    report("retry_mbr")
                    prepare_disk_for_format(number)
                    ok, info = _format_via_diskpart(
                        number, "MBR", fs_dp, safe_label, quick, clean_all=True,
                    )
                    if not ok:
                        _note_format_error(errors, "diskpart (MBR)", info)
                        ok, info = _format_via_storage(
                            number, "MBR", fs_ps, safe_label, quick, report=report,
                        )
                        if not ok:
                            _note_format_error(errors, "storage (MBR)", info)

    _invalidate_cache()
    if ok:
        report("done")
        return True, info
    return False, _combine_format_errors(errors)


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_path_under_volume(path: str, volume_root: str) -> bool:
    """True si path está dentro del volumen (no permite borrar la raíz)."""
    try:
        path_n = _norm_path(path)
        root_n = _norm_path(volume_root)
        if not root_n.endswith(os.sep):
            root_n = root_n + os.sep
        root_stripped = root_n.rstrip(os.sep)
        if path_n == root_stripped:
            return False
        return path_n.startswith(root_n)
    except OSError:
        return False


def send_to_recycle_bin(path: str, volume_root: str = "") -> bool:
    """Envía un archivo o carpeta a la Papelera de reciclaje (Windows)."""
    if sys.platform != "win32":
        return False
    if not path or not os.path.exists(path):
        return False
    abs_path = os.path.abspath(path)
    if volume_root and not is_path_under_volume(abs_path, volume_root):
        return False

    FO_DELETE = 0x0003
    FOF_ALLOWUNDO = 0x0040
    FOF_NOCONFIRMATION = 0x0010
    FOF_SILENT = 0x0004

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    shell32 = ctypes.windll.shell32
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = abs_path + "\0\0"
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None
    result = shell32.SHFileOperationW(ctypes.byref(op))
    return result == 0 and not op.fAnyOperationsAborted
