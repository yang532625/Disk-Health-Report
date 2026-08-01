# -*- coding: utf-8 -*-
"""Comprobación de actualizaciones (GitHub Releases + instaladores locales)."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from version import __version__

GITHUB_OWNER = "yang532625"
GITHUB_REPO = "Disk-Health-Report"
GITHUB_API_LATEST = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
USER_AGENT = f"DiskHealthReport/{__version__}"

_SETUP_NAME_RE = re.compile(
    r"DiskHealthReport[_-]?(?:Setup|Installer)?[_-]?v?(\d+\.\d+\.\d+)",
    re.IGNORECASE,
)


@dataclass
class UpdateInfo:
    version: str
    source: str  # "github" | "local"
    download_url: str = ""
    local_path: str = ""
    notes: str = ""

    @property
    def is_remote(self) -> bool:
        return self.source == "github" and bool(self.download_url)


def parse_version(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text or ""))
    if not m:
        return (0, 0, 0)
    return tuple(int(x) for x in m.groups())


def is_newer(candidate: str, current: str | None = None) -> bool:
    return parse_version(candidate) > parse_version(current or __version__)


def _http_json(url: str, timeout: float = 12.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_github_update(current: str | None = None) -> Optional[UpdateInfo]:
    """Consulta la última release pública en GitHub."""
    try:
        data = _http_json(GITHUB_API_LATEST)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    tag = str(data.get("tag_name") or data.get("name") or "")
    version = re.sub(r"^v", "", tag, flags=re.I).strip()
    if not version or not is_newer(version, current):
        return None
    assets = data.get("assets") or []
    download_url = ""
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower().endswith(".exe") and ("setup" in name.lower() or "installer" in name.lower()):
            download_url = str(asset.get("browser_download_url") or "")
            break
    if not download_url and assets:
        download_url = str(assets[0].get("browser_download_url") or "")
    return UpdateInfo(
        version=version,
        source="github",
        download_url=download_url or GITHUB_RELEASES_URL,
        notes=str(data.get("body") or "")[:500],
    )


def _version_from_filename(path: str) -> str:
    name = os.path.basename(path)
    m = _SETUP_NAME_RE.search(name)
    if m:
        return m.group(1)
    return ""


def check_local_update(
    search_dirs: list[str] | None = None,
    current: str | None = None,
) -> Optional[UpdateInfo]:
    """Busca instaladores Setup más nuevos en carpetas locales."""
    dirs = list(search_dirs or [])
    home = os.path.expanduser("~")
    dirs.extend(
        [
            os.path.join(home, "Downloads"),
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
        ]
    )
    best: Optional[UpdateInfo] = None
    best_ver = parse_version(current or __version__)
    seen: set[str] = set()
    for folder in dirs:
        if not folder or not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(".exe"):
                continue
            if "diskhealth" not in name.lower() and "disk_health" not in name.lower():
                continue
            if "setup" not in name.lower() and "installer" not in name.lower():
                continue
            path = os.path.abspath(os.path.join(folder, name))
            if path in seen:
                continue
            seen.add(path)
            ver = _version_from_filename(path)
            if not ver or parse_version(ver) <= best_ver:
                continue
            best_ver = parse_version(ver)
            best = UpdateInfo(version=ver, source="local", local_path=path)
    return best


def check_for_updates(
    *,
    current: str | None = None,
    local_dirs: list[str] | None = None,
) -> Optional[UpdateInfo]:
    """Prefiere la versión más alta entre GitHub y local."""
    remote = check_github_update(current)
    local = check_local_update(local_dirs, current)
    if remote and local:
        return remote if parse_version(remote.version) >= parse_version(local.version) else local
    return remote or local


def download_installer(url: str, dest_dir: str | None = None) -> str:
    """Descarga el Setup.exe a dest_dir (o TEMP) y devuelve la ruta."""
    folder = dest_dir or tempfile.gettempdir()
    os.makedirs(folder, exist_ok=True)
    name = os.path.basename(url.split("?")[0]) or "DiskHealthReport_Setup_x64.exe"
    if not name.lower().endswith(".exe"):
        name = "DiskHealthReport_Setup_x64.exe"
    dest = os.path.join(folder, name)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
    return dest


def launch_installer(path: str) -> None:
    os.startfile(path)  # noqa: S606 — Windows installer launch
