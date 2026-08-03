# -*- coding: utf-8 -*-
"""Servicio de acceso a discos y smartctl."""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from i18n import DEFAULT_LANG

DiskCategory = Literal["system", "external"]

_SMARTCTL_SCAN_TIMEOUT = 12
_SMARTCTL_INFO_TIMEOUT = 20
_SMARTCTL_DATA_TIMEOUT = 45
_WMI_TIMEOUT = 8

_BRAND_RULES: list[tuple[str, str]] = [
    (r"^MTFD|^MICRON", "Micron"),
    (r"^SAMSUNG|Samsung", "Samsung"),
    (r"^WDC\b|^WD[_\s]", "Western Digital"),
    (r"^ST\d", "Seagate"),
    (r"^TOSHIBA|^MK\d|^DT\d|^HD", "Toshiba"),
    (r"^HITACHI|^HTS", "Hitachi"),
    (r"^INTEL", "Intel"),
    (r"^KINGSTON", "Kingston"),
    (r"DataTraveler", "Kingston"),
    (r"^CRUCIAL", "Crucial"),
    (r"^SANDISK", "SanDisk"),
    (r"^XrayDisk", "XrayDisk"),
    (r"^ADATA", "ADATA"),
    (r"^SK\s*hynix|^HFS", "SK hynix"),
    (r"^PNY", "PNY"),
    (r"^LITEON", "Lite-On"),
    (r"^HP\b", "HP"),
    (r"^APPLE", "Apple"),
    (r"^LEXAR", "Lexar"),
]


@dataclass
class DiskInfo:
    path: str
    description: str
    model: str = "Unknown"
    serial: str = ""
    capacity: str = "Unknown"
    interface: str = ""
    rotation: str = ""
    smart_available: bool = True
    brand: str = "Unknown"
    category: DiskCategory = "system"
    transport: str = ""


def get_project_root() -> str:
    """Repo root in development; executable dir when frozen."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    here = os.path.dirname(os.path.abspath(__file__)) or "."
    if os.path.basename(here).lower() == "app":
        return os.path.dirname(here)
    return here


def get_app_dir() -> str:
    """Directory used for adjacent runtime files (exe dir or project root)."""
    return get_project_root()


def get_default_reports_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents", "DiskHealthReport")


def get_reports_dir() -> str:
    custom = load_settings().get("reports_dir")
    if custom:
        try:
            os.makedirs(custom, exist_ok=True)
            return custom
        except OSError:
            pass
    default = get_default_reports_dir()
    os.makedirs(default, exist_ok=True)
    return default


def resolve_report_day_dir(base: str | None = None) -> str:
    """Carpeta de reportes del día: {reports_dir}/YYYY-MM-DD/."""
    from datetime import datetime

    root = base or get_reports_dir()
    day = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(root, day)
    os.makedirs(path, exist_ok=True)
    return path


def set_reports_dir(path: str) -> str:
    """Valida/crea la carpeta y la guarda en settings. Devuelve la ruta efectiva."""
    os.makedirs(path, exist_ok=True)
    settings = load_settings()
    settings["reports_dir"] = path
    save_settings(settings)
    return path


def get_settings_path() -> str:
    appdata = os.path.join(os.environ.get("APPDATA", ""), "DiskHealthReport")
    os.makedirs(appdata, exist_ok=True)
    return os.path.join(appdata, "settings.json")


def load_settings() -> dict:
    path = get_settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"lang": DEFAULT_LANG}


def save_settings(settings: dict) -> None:
    with open(get_settings_path(), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def is_admin() -> bool:
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def restart_as_admin() -> bool:
    """Relanza la app elevada. Devuelve True si ShellExecute aceptó el lanzamiento."""
    import ctypes
    exe = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return int(rc) > 32


def _show_admin_required_message() -> None:
    """Mensaje nativo si el usuario cancela UAC o no puede elevar."""
    try:
        import ctypes
        from i18n import t
        msg = t("admin_required_exit", "es")
        ctypes.windll.user32.MessageBoxW(
            None, msg, "Disk Health Report", 0x00000010,
        )
    except Exception:
        pass


def ensure_elevated() -> None:
    """Solicita elevación UAC si no se ejecuta como administrador."""
    if is_admin():
        return
    if not restart_as_admin():
        _show_admin_required_message()
    sys.exit(0)


_APP_MUTEX_HANDLE = None


def acquire_app_mutex() -> None:
    """
    Crea el mutex que Inno Setup espera (AppMutex=DiskHealthReportRunning)
    para cerrar/actualizar la app instalada en la misma carpeta.
    """
    global _APP_MUTEX_HANDLE
    if sys.platform != "win32" or _APP_MUTEX_HANDLE is not None:
        return
    try:
        import ctypes

        _APP_MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(
            None, False, "DiskHealthReportRunning"
        )
    except Exception:
        _APP_MUTEX_HANDLE = None


def get_install_dir() -> str:
    """Carpeta de instalación real (para actualizaciones in-place)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\Disk Health\DiskHealthReport",
        ) as key:
            path, _ = winreg.QueryValueEx(key, "InstallPath")
            if path and os.path.isdir(path):
                return path
    except OSError:
        pass
    return os.path.join(
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        "DiskHealthReport",
    )


def _hidden_subprocess_kwargs() -> dict:
    """Evita ventanas CMD al lanzar smartctl u otros procesos en Windows."""
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


def _run_hidden(cmd: list[str], timeout: int, **extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        **_hidden_subprocess_kwargs(),
        **extra,
    )


def get_smartctl_path() -> Optional[str]:
    from runtime_bootstrap import ensure_runtime_smartctl, get_cached_smartctl_path

    cached = get_cached_smartctl_path()
    if os.path.isfile(cached):
        return cached

    if getattr(sys, "frozen", False):
        extracted = ensure_runtime_smartctl()
        if extracted and os.path.isfile(extracted):
            return extracted
        return None

    embedded = os.path.join(get_app_dir(), "smartmontools", "bin", "smartctl.exe")
    if os.path.exists(embedded):
        return embedded

    if not getattr(sys, "frozen", False):
        dev_embedded = os.path.join(
            get_app_dir(), "packaging", "assets", "smartmontools", "bin", "smartctl.exe"
        )
        if os.path.isfile(dev_embedded):
            return dev_embedded

    for ruta in [
        r"C:\Program Files\smartmontools\bin\smartctl.exe",
        r"C:\Program Files (x86)\smartmontools\bin\smartctl.exe",
    ]:
        if os.path.exists(ruta):
            return ruta

    try:
        _run_hidden(
            ["smartctl", "--version"],
            timeout=5,
            check=True,
        )
        return "smartctl"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _search(pattern: str, text: str, group: int = 1, default: str = "") -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return default
    try:
        return match.group(group).strip()
    except IndexError:
        return default


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def _norm_serial(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").lower()


def _disk_index_from_path(path: str) -> Optional[int]:
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


def _clean_model_for_brand(model: str) -> str:
    model = (model or "").strip()
    return re.sub(r"\s+USB\s+Device\s*$", "", model, flags=re.IGNORECASE).strip()


def _is_weak_model(model: str, description: str = "") -> bool:
    model = (model or "").strip()
    if not model or model.lower() in ("unknown", "unknown device"):
        return True
    if model.startswith("/dev"):
        return True
    if "scsi device" in model.lower():
        return True
    if description and model == description:
        return True
    return False


def _brand_from_pnp(pnp: str) -> str:
    if not pnp:
        return ""
    match = re.search(r"VEN_([^&\\]+)", pnp, re.IGNORECASE)
    if not match:
        return ""
    vendor = match.group(1).replace("_", " ").strip()
    if not vendor:
        return ""
    brand = extract_brand(vendor)
    return brand if brand != "Unknown" else vendor.capitalize()


def _format_capacity_bytes(nbytes: int) -> str:
    if nbytes <= 0:
        return "Unknown"
    tb = nbytes / (1024 ** 4)
    if tb >= 1:
        return f"{tb:.2f} TB"
    gb = nbytes / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.0f} GB"
    mb = nbytes / (1024 ** 2)
    return f"{mb:.0f} MB"


def extract_brand(model: str) -> str:
    model = _clean_model_for_brand(model)
    if not model or model.lower() in ("unknown", "unknown device"):
        return "Unknown"
    for pattern, brand in _BRAND_RULES:
        if re.search(pattern, model, re.IGNORECASE):
            return brand
    first = model.split()[0] if model.split() else model
    if len(first) <= 20 and not first.startswith("/dev"):
        return first
    return "Unknown"


def _parse_capacity(raw: str) -> str:
    for pattern in (
        r"User Capacity:\s+.+?\[(.+?)\]",
        r"Total NVM Capacity:\s+.+?\[(.+?)\]",
        r"Namespace 1 Size/Capacity:\s+.+?\[(.+?)\]",
        r"Namespace \d+ Size/Capacity:\s+.+?\[(.+?)\]",
    ):
        cap = _search(pattern, raw)
        if cap and cap not in ("0 B", "0"):
            return cap

    for pattern in (
        r"User Capacity:\s+([\d,]+)\s*bytes",
        r"Total NVM Capacity:\s+([\d,]+)\s*bytes",
        r"Namespace 1 Size/Capacity:\s+([\d,]+)\s*bytes",
    ):
        cap_bytes = _search(pattern, raw)
        if cap_bytes:
            try:
                nbytes = int(cap_bytes.replace(",", ""))
                if nbytes <= 0:
                    continue
                tb = nbytes / (1024 ** 4)
                return f"{tb:.2f} TB" if tb >= 1 else f"{tb * 1024:.0f} GB"
            except ValueError:
                return cap_bytes
    return "Unknown"


def _detect_transport(raw: str, description: str) -> str:
    desc = (description or "").lower()
    if "usb" in raw.lower() or "usb" in desc:
        return "USB"
    if _has(r"NVMe Version:", raw) or "nvme" in desc:
        return "NVMe"
    if _has(r"SATA Version is:", raw):
        return "SATA"
    transport = _search(r"Transport protocol:\s+(.+)", raw)
    if transport:
        if "usb" in transport.lower():
            return "USB"
        if "pcie" in transport.lower() or "nvme" in transport.lower():
            return "NVMe"
        if "sata" in transport.lower():
            return "SATA"
        return transport.split(",")[0].strip()
    if "scsi device" in desc:
        return "SCSI"
    return ""


def _wmi_usb_serials() -> set[str]:
    if sys.platform != "win32":
        return set()
    try:
        result = _run_hidden(
            [
                "powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                "Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue | "
                "Where-Object { $_.InterfaceType -eq 'USB' } | "
                "ForEach-Object { $_.SerialNumber.Trim() }",
            ],
            timeout=_WMI_TIMEOUT,
        )
        return {s.strip() for s in result.stdout.splitlines() if s.strip()}
    except Exception:
        return set()


def _wmi_physical_disks() -> list[dict]:
    if sys.platform != "win32":
        return []
    try:
        result = _run_hidden(
            [
                "powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                "Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue | "
                "Select-Object Index, SerialNumber, Model, PNPDeviceID, Size | "
                "ConvertTo-Json -Depth 3 -Compress",
            ],
            timeout=_WMI_TIMEOUT,
        )
        raw = result.stdout.strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        rows: list[dict] = []
        for item in data:
            try:
                size = int(item.get("Size") or 0)
            except (TypeError, ValueError):
                size = 0
            rows.append({
                "index": int(item.get("Index", -1)),
                "serial": (item.get("SerialNumber") or "").strip(),
                "model": (item.get("Model") or "").strip(),
                "pnp": (item.get("PNPDeviceID") or "").strip(),
                "size": size,
            })
        return rows
    except Exception:
        return []


def _enrich_disk_from_windows(info: DiskInfo, wmi_rows: list[dict]) -> None:
    if not wmi_rows:
        return

    target_serial = _norm_serial(info.serial)
    idx = _disk_index_from_path(info.path)
    matched: Optional[dict] = None

    if target_serial:
        for row in wmi_rows:
            ser = _norm_serial(row.get("serial", ""))
            if ser and (ser == target_serial or ser in target_serial or target_serial in ser):
                matched = row
                break

    if matched is None and idx is not None:
        for row in wmi_rows:
            if row.get("index") == idx:
                matched = row
                break

    if matched is None:
        return

    wmi_serial = (matched.get("serial") or "").strip()
    if not info.serial.strip() and wmi_serial:
        info.serial = wmi_serial

    wmi_model = matched.get("model") or ""
    if _is_weak_model(info.model, info.description) and wmi_model:
        info.model = wmi_model

    if info.capacity in ("Unknown", "") and matched.get("size"):
        info.capacity = _format_capacity_bytes(matched["size"])

    pnp_brand = _brand_from_pnp(matched.get("pnp") or "")
    if info.brand in ("Unknown", ""):
        if pnp_brand:
            info.brand = pnp_brand
        elif wmi_model:
            info.brand = extract_brand(wmi_model)
    elif pnp_brand and info.brand == "Unknown":
        info.brand = pnp_brand


def classify_disk(
    info: DiskInfo,
    description: str,
    raw: str,
    usb_serials: Optional[set[str]] = None,
) -> DiskCategory:
    desc_lower = (description or "").lower()
    raw_lower = raw.lower()
    model_lower = (info.model or "").lower()

    if usb_serials and info.serial and info.serial.strip() in usb_serials:
        return "external"

    if info.transport == "USB":
        return "external"

    if "usb" in raw_lower or re.search(r"\busb\b", desc_lower):
        return "external"

    if "transport protocol: usb" in raw_lower:
        return "external"

    if "scsi device" in desc_lower:
        if not info.serial or info.model == info.description:
            return "external"
        if model_lower.startswith("/dev") or "scsi device" in model_lower:
            return "external"

    return "system"


def group_disks_by_category(disks: list[DiskInfo]) -> dict[str, list[DiskInfo]]:
    grouped: dict[str, list[DiskInfo]] = {"system": [], "external": []}
    for disk in disks:
        cat = disk.category if disk.category in grouped else "system"
        grouped[cat].append(disk)
    return grouped


def _disk_dedup_key(disk: DiskInfo) -> str | None:
    serial = _norm_serial(disk.serial)
    if serial:
        return f"s:{serial}"
    idx = _disk_index_from_path(disk.path)
    if idx is not None:
        return f"i:{idx}"
    return None


def _prefer_disk_entry(a: DiskInfo, b: DiskInfo) -> DiskInfo:
    def score(disk: DiskInfo) -> tuple:
        return (
            1 if disk.smart_available else 0,
            0 if _is_weak_model(disk.model, disk.description) else 1,
            1 if re.search(r"/dev/pd\d+", disk.path, re.IGNORECASE) else 0,
            len(disk.model or ""),
        )

    return a if score(a) >= score(b) else b


def deduplicate_disks(disks: list[DiskInfo]) -> list[DiskInfo]:
    """Una entrada por disco físico (mismo serial o mismo índice Windows)."""
    by_key: dict[str, DiskInfo] = {}
    unkeyed: list[DiskInfo] = []
    for disk in disks:
        key = _disk_dedup_key(disk)
        if key is None:
            unkeyed.append(disk)
            continue
        existing = by_key.get(key)
        by_key[key] = disk if existing is None else _prefer_disk_entry(existing, disk)
    return list(by_key.values()) + unkeyed


def disk_identity(disk: DiskInfo) -> str:
    serial = _norm_serial(disk.serial)
    if serial:
        return f"serial:{serial}"
    idx = _disk_index_from_path(disk.path)
    if idx is not None:
        return f"pd:{idx}"
    return disk.path


def scan_disks(smartctl_path: str) -> list[dict]:
    try:
        resultado = _run_hidden(
            [smartctl_path, "--scan"],
            timeout=_SMARTCTL_SCAN_TIMEOUT,
            check=True,
        )
        discos = []
        for linea in resultado.stdout.strip().split("\n"):
            if linea.strip() and not linea.startswith("#"):
                partes = linea.split("#")
                comando = partes[0].strip().split()[0]
                descripcion = partes[1].strip() if len(partes) > 1 else "Unknown device"
                discos.append({"comando": comando, "descripcion": descripcion})
        return discos
    except Exception:
        return []


def get_disk_info(
    smartctl_path: str,
    disk_path: str,
    description: str = "",
    usb_serials: Optional[set[str]] = None,
) -> DiskInfo:
    info = DiskInfo(path=disk_path, description=description or disk_path)
    raw = ""

    try:
        resultado = _run_hidden(
            [smartctl_path, "-i", disk_path],
            timeout=_SMARTCTL_INFO_TIMEOUT,
        )
        raw = resultado.stdout + resultado.stderr
    except subprocess.TimeoutExpired:
        info.smart_available = False
        info.brand = extract_brand(info.model)
        info.category = classify_disk(info, description, raw, usb_serials)
        return info
    except Exception:
        info.smart_available = False
        info.brand = extract_brand(info.model)
        info.category = classify_disk(info, description, raw, usb_serials)
        return info

    if "SMART support is: Unavailable" in raw or "Read SMART Data failed" in raw:
        info.smart_available = False

    vendor = _search(r"Vendor:\s+(.+)", raw)
    product = _search(r"Product:\s+(.+)", raw)

    info.model = (
        _search(r"Device Model:\s+(.+)", raw)
        or _search(r"Model Number:\s+(.+)", raw)
        or product
        or info.description
    )
    if product and _is_weak_model(info.model, description):
        info.model = product

    info.serial = _search(r"Serial Number:\s+(.+)", raw)
    info.capacity = _parse_capacity(raw)

    info.interface = _search(r"SATA Version is:\s+(.+)", raw) or _search(
        r"Transport protocol:\s+(.+)", raw
    )
    info.rotation = _search(r"Rotation Rate:\s+(.+)", raw) or _search(
        r"Rotation Speed:\s+(.+)", raw
    )
    if not info.rotation and ("Solid State" in raw or "NVMe" in raw):
        info.rotation = "SSD"

    info.transport = _detect_transport(raw, description)
    if vendor:
        brand_from_vendor = extract_brand(vendor)
        info.brand = brand_from_vendor if brand_from_vendor != "Unknown" else vendor.strip()
    if info.brand in ("Unknown", ""):
        info.brand = extract_brand(info.model)
    info.category = classify_disk(info, description, raw, usb_serials)

    return info


def scan_disks_with_info(
    smartctl_path: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> list[DiskInfo]:
    usb_serials = _wmi_usb_serials()
    raw_entries = scan_disks(smartctl_path)
    disks: list[DiskInfo] = []
    total = len(raw_entries) or 1

    for i, entry in enumerate(raw_entries):
        disks.append(
            get_disk_info(
                smartctl_path,
                entry["comando"],
                entry["descripcion"],
                usb_serials,
            )
        )
        if progress_cb:
            progress_cb(i + 1, total)

    if not disks:
        fallback = "/dev/pd0"
        disks.append(
            get_disk_info(smartctl_path, fallback, "Primary physical drive", usb_serials)
        )
        if progress_cb:
            progress_cb(1, 1)

    wmi_rows = _wmi_physical_disks()
    for disk in disks:
        _enrich_disk_from_windows(disk, wmi_rows)

    return deduplicate_disks(disks)


def get_smart_data(smartctl_path: str, disk_path: str) -> str:
    try:
        resultado = _run_hidden(
            [smartctl_path, "-a", disk_path],
            timeout=_SMARTCTL_DATA_TIMEOUT,
        )
        return resultado.stdout
    except Exception:
        return ""
