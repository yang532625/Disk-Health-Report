# -*- coding: utf-8 -*-
"""Comprobación de actualizaciones (GitHub Releases + instaladores locales)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

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

ProgressCallback = Callable[[float, str], None]


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


def download_installer(
    url: str,
    dest_dir: str | None = None,
    progress_callback: ProgressCallback | None = None,
    *,
    version: str | None = None,
) -> str:
    """Descarga el Setup.exe. progress_callback(fraction 0..1, status_text)."""
    import time

    folder = dest_dir or tempfile.gettempdir()
    os.makedirs(folder, exist_ok=True)
    base = os.path.basename(url.split("?")[0]) or "DiskHealthReport_Setup_x64.exe"
    if not base.lower().endswith(".exe"):
        base = "DiskHealthReport_Setup_x64.exe"
    stem, ext = os.path.splitext(base)
    # Nombre único: evita Errno 13 si un Setup anterior sigue bloqueado en Temp.
    ver_part = re.sub(r"[^\d.]", "", version or "") or time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(folder, f"{stem}_v{ver_part}_{os.getpid()}{ext}")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if progress_callback:
        progress_callback(0.0, "download")
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as out:
        total = 0
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        done = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress_callback:
                if total > 0:
                    progress_callback(min(done / total, 1.0), "download")
                else:
                    progress_callback(min(0.15 + done / (80 * 1024 * 1024), 0.7), "download")
    if progress_callback:
        progress_callback(1.0, "download")
    return dest


def _ps_single_quote(value: str) -> str:
    """Comilla un literal para PowerShell (comillas simples)."""
    return "'" + str(value).replace("'", "''") + "'"


def schedule_silent_update(
    installer_path: str,
    *,
    install_dir: str | None = None,
) -> str:
    """
    Patrón profesional de actualización Inno/Windows:
    1) Eleva un helper (UAC) mientras la app aún puede mostrarlo.
    2) La app debe cerrarse justo después (libera AppMutex).
    3) El helper espera el cierre, fuerza fin de procesos residuales,
       instala en silencio sobre la misma carpeta y reabre la app.

    Importante: no lanzar Setup.exe mientras AppMutex sigue activo —
    con /SUPPRESSMSGBOXES Inno cancela el diálogo "app is running".
    """
    from disk_service import get_install_dir

    setup = os.path.abspath(installer_path)
    if not os.path.isfile(setup):
        raise FileNotFoundError(setup)

    target = os.path.abspath(install_dir or get_install_dir())
    temp = tempfile.gettempdir()
    log_path = os.path.join(temp, "DiskHealthReport_update.log")
    setup_log = os.path.join(temp, "DiskHealthReport_setup.log")
    ps1 = os.path.join(temp, f"DiskHealthReport_update_{os.getpid()}.ps1")
    exe_path = os.path.join(target, "DiskHealthReport.exe")
    wait_pid = os.getpid()

    script = f"""# Disk Health Report — silent update helper (run elevated)
param([int]$WaitPid = 0)
$ErrorActionPreference = 'Continue'
$log = {_ps_single_quote(log_path)}
$setup = {_ps_single_quote(setup)}
$installDir = {_ps_single_quote(target)}
$setupLog = {_ps_single_quote(setup_log)}
$exe = {_ps_single_quote(exe_path)}
function Write-UpdateLog([string]$Message) {{
  $line = '{{0:yyyy-MM-dd HH:mm:ss}} {{1}}' -f (Get-Date), $Message
  try {{ Add-Content -LiteralPath $log -Value $line -Encoding UTF8 }} catch {{}}
}}
try {{
  Write-UpdateLog 'Elevated helper started'
  Write-UpdateLog ("Installer=" + $setup)
  Write-UpdateLog ("InstallDir=" + $installDir)
  Write-UpdateLog ("WaitPid=" + $WaitPid)
  $deadline = (Get-Date).AddSeconds(90)
  do {{
    $appProcs = @(Get-Process -Name 'DiskHealthReport' -ErrorAction SilentlyContinue)
    $waitAlive = $false
    if ($WaitPid -gt 0) {{
      $waitAlive = $null -ne (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue)
    }}
    if (-not $waitAlive -and $appProcs.Count -eq 0) {{
      Write-UpdateLog 'App processes exited'
      break
    }}
    Write-UpdateLog ('Waiting for exit; DiskHealthReport=' + $appProcs.Count + ' WaitPidAlive=' + $waitAlive)
    Start-Sleep -Seconds 1
  }} while ((Get-Date) -lt $deadline)

  # Como admin: liberar AppMutex antes de Setup (si no, /SUPPRESSMSGBOXES cancela).
  Write-UpdateLog 'Force-stopping DiskHealthReport.exe (elevated)'
  & taskkill.exe /F /IM DiskHealthReport.exe 2>$null | Out-Null
  Start-Sleep -Seconds 2

  if (-not (Test-Path -LiteralPath $setup)) {{
    throw "Installer missing: $setup"
  }}
  $argString = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /DIR="' + $installDir + '" /LOG="' + $setupLog + '"'
  Write-UpdateLog ('Starting Setup: ' + $argString)
  $p = Start-Process -FilePath $setup -ArgumentList $argString -PassThru
  # Process.WaitForExit espera solo Setup.exe. Start-Process -Wait también espera
  # descendientes y quedaba vivo mientras la app recién lanzada siguiera abierta.
  $p.WaitForExit()
  $code = if ($null -ne $p) {{ $p.ExitCode }} else {{ -1 }}
  Write-UpdateLog ("Setup exit code=" + $code)
  if ($code -ne 0 -and $null -ne $code) {{
    throw "Setup failed with exit code $code"
  }}

  Start-Sleep -Seconds 1
  $running = @(Get-Process -Name 'DiskHealthReport' -ErrorAction SilentlyContinue)
  if ($running.Count -eq 0 -and (Test-Path -LiteralPath $exe)) {{
    Write-UpdateLog 'Relaunching DiskHealthReport.exe'
    Start-Process -FilePath $exe
  }} else {{
    Write-UpdateLog ('Relaunch skipped; running=' + $running.Count)
  }}
  Write-UpdateLog 'Helper finished OK'
}} catch {{
  Write-UpdateLog ('Helper FAILED: ' + $_.Exception.Message)
  exit 1
}}
"""
    with open(ps1, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(script)

    # Elevar YA (UAC visible); el helper espera a que esta app cierre.
    # No elevar Setup.exe directo: AppMutex + SUPPRESSMSGBOXES = cancel.
    ps_args = (
        f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
        f'-File "{ps1}" -WaitPid {wait_pid}'
    )
    if sys.platform == "win32":
        import ctypes

        rc = int(
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "powershell.exe",
                ps_args,
                temp,
                0,  # SW_HIDE
            )
        )
        if rc <= 32:
            if rc in (1223, 0):
                raise RuntimeError("UAC cancelled")
            raise RuntimeError(f"Update helper launch failed (ShellExecute={rc})")
        return log_path

    subprocess.Popen(  # noqa: S603
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1,
         "-WaitPid", str(wait_pid)],
        cwd=temp,
        close_fds=True,
    )
    return log_path


def launch_installer(path: str, *, silent: bool = False, install_dir: str | None = None) -> None:
    """Abre el Setup. silent=True: programa instalación tras cerrar la app."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if not silent:
        os.startfile(path)  # noqa: S606 — Windows installer launch
        return
    schedule_silent_update(path, install_dir=install_dir)


def apply_update(
    info: UpdateInfo,
    *,
    progress_callback: ProgressCallback | None = None,
    silent: bool = True,
) -> str:
    """
    Descarga (si hace falta) y programa el instalador.
    Progreso: descarga 0..0.85, preparar 0.85..0.95, listo para cerrar 1.0.
    Devuelve la ruta del Setup usado.
    """
    path = ""
    if info.local_path and os.path.isfile(info.local_path):
        path = info.local_path
        if progress_callback:
            progress_callback(0.9, "install")
    elif info.download_url and ".exe" in info.download_url.lower():
        def _map_dl(frac: float, _phase: str) -> None:
            if progress_callback:
                progress_callback(0.85 * max(0.0, min(frac, 1.0)), "download")

        path = download_installer(
            info.download_url,
            progress_callback=_map_dl,
            version=info.version,
        )
        if progress_callback:
            progress_callback(0.9, "install")
    else:
        raise RuntimeError("No installer URL or local path")

    if progress_callback:
        progress_callback(0.95, "install")
    launch_installer(path, silent=silent)
    if progress_callback:
        progress_callback(1.0, "done")
    return path
