# -*- coding: utf-8 -*-
"""Ajuste de la hora local del sistema a partir de una ubicación (online + SetLocalTime).

Solo usa la biblioteca estándar (urllib). La app ya corre elevada, por lo que
``SetLocalTime`` tiene los privilegios necesarios.
"""

from __future__ import annotations

import ctypes
import json
import sys
import urllib.parse
import urllib.request
from typing import Optional, Tuple

_TIMEOUT = 8
_USER_AGENT = "DiskHealthReport/1.0 (+local-time-tool)"


def _http_get_json(url: str) -> Optional[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    return json.loads(data)


def geocode_location(name: str) -> Optional[Tuple[str, str]]:
    """Resuelve un nombre de lugar a ``(display_name, iana_tz)`` vía open-meteo.

    Devuelve ``None`` si no se encuentra.
    """
    name = (name or "").strip()
    if not name:
        return None
    q = urllib.parse.quote(name)
    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={q}&count=1&language=en&format=json"
    )
    data = _http_get_json(url)
    if not data:
        return None
    results = data.get("results") or []
    if not results:
        return None
    top = results[0]
    tz = top.get("timezone")
    if not tz:
        return None
    parts = [top.get("name")]
    admin1 = top.get("admin1")
    country = top.get("country")
    if admin1 and admin1 != top.get("name"):
        parts.append(admin1)
    if country:
        parts.append(country)
    display = ", ".join(p for p in parts if p)
    return display, tz


def _parse_iso_components(iso: str) -> Optional[Tuple[int, int, int, int, int, int]]:
    """Parsea un ISO8601 'YYYY-MM-DDTHH:MM:SS...' a componentes enteros."""
    try:
        date_part, time_part = iso.replace("Z", "").split("T", 1)
        y, mo, d = (int(x) for x in date_part.split("-"))
        time_part = time_part.split("+")[0].split("-")[0]
        hh, mm, ss = time_part.split(":")[:3]
        return y, mo, d, int(hh), int(mm), int(float(ss))
    except Exception:
        return None


def fetch_zone_now(iana_tz: str) -> Optional[Tuple[int, int, int, int, int, int]]:
    """Obtiene la hora actual de una zona IANA. Devuelve (y, mo, d, h, mi, s)."""
    tz_q = urllib.parse.quote(iana_tz)
    # Fuente principal: timeapi.io
    try:
        data = _http_get_json(
            f"https://timeapi.io/api/Time/current/zone?timeZone={tz_q}"
        )
        if data and "year" in data:
            return (
                int(data["year"]),
                int(data["month"]),
                int(data["day"]),
                int(data["hour"]),
                int(data["minute"]),
                int(data.get("seconds", 0)),
            )
    except Exception:
        pass
    # Fallback: worldtimeapi.org (ISO en 'datetime')
    try:
        data = _http_get_json(f"https://worldtimeapi.org/api/timezone/{tz_q}")
        if data and data.get("datetime"):
            return _parse_iso_components(data["datetime"])
    except Exception:
        pass
    return None


class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", ctypes.c_ushort),
        ("wMonth", ctypes.c_ushort),
        ("wDayOfWeek", ctypes.c_ushort),
        ("wDay", ctypes.c_ushort),
        ("wHour", ctypes.c_ushort),
        ("wMinute", ctypes.c_ushort),
        ("wSecond", ctypes.c_ushort),
        ("wMilliseconds", ctypes.c_ushort),
    ]


def set_system_local_time(y: int, mo: int, d: int, h: int, mi: int, s: int) -> bool:
    """Ajusta la hora local del sistema con ``SetLocalTime`` (requiere admin)."""
    if sys.platform != "win32":
        return False
    st = _SYSTEMTIME()
    st.wYear = y
    st.wMonth = mo
    st.wDay = d
    st.wDayOfWeek = 0  # ignorado por SetLocalTime
    st.wHour = h
    st.wMinute = mi
    st.wSecond = s
    st.wMilliseconds = 0
    try:
        ok = ctypes.windll.kernel32.SetLocalTime(ctypes.byref(st))
        return bool(ok)
    except Exception:
        return False


def set_time_for_location(name: str) -> Tuple[bool, str]:
    """Orquesta geocode -> hora -> SetLocalTime.

    Devuelve ``(ok, info)`` donde, si ``ok`` es True, ``info`` es un texto
    descriptivo del lugar y la nueva hora; si es False, ``info`` es una clave
    i18n de error: ``set_time_invalid``, ``set_time_no_internet``,
    ``set_time_not_found`` o ``set_time_failed``.
    """
    if not (name or "").strip():
        return False, "set_time_invalid"

    try:
        geo = geocode_location(name)
    except Exception:
        return False, "set_time_no_internet"
    if not geo:
        return False, "set_time_not_found"
    display, tz = geo

    try:
        comps = fetch_zone_now(tz)
    except Exception:
        return False, "set_time_no_internet"
    if not comps:
        return False, "set_time_no_internet"

    y, mo, d, h, mi, s = comps
    if not set_system_local_time(y, mo, d, h, mi, s):
        return False, "set_time_failed"

    hour12 = h % 12 or 12
    ampm = "AM" if h < 12 else "PM"
    info = f"{display} ({tz})  -  {y}-{mo:02d}-{d:02d}  {hour12}:{mi:02d} {ampm}"
    return True, info
