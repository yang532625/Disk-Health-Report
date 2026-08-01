# -*- coding: utf-8 -*-
"""Lanzador de Microsoft Activation Scripts (MAS).

Ejecución embebida (oculta) con salida capturada, o consola visible completa.
Copia MAS_AIO.cmd a AppData para evitar el rechazo de PyInstaller temp (_MEIPASS).
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from typing import Callable, Optional, Tuple

import bundled_assets

_ONLINE_HOST = "get.activated.win"
_FALLBACK_HOST = "1.1.1.1"

_ONLINE_PS_COMMAND = (
    "$Host.UI.RawUI.WindowTitle='Microsoft Activation Scripts';"
    "$host.UI.RawUI.BackgroundColor='Black';Clear-Host;"
    "irm https://get.activated.win | iex"
)

# Switches desatendidos soportados por MAS_AIO.cmd (validados en el script).
METHOD_SWITCHES = {
    "hwid": ["/HWID"],
    "ohook": ["/Ohook"],
    "tsforge": ["/Z-WindowsESUOffice"],
    "kms": ["/K-WindowsOffice"],
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

_ERROR_MARKERS = (
    "==== ERROR ====",
    "Input redirection is not supported",
    "launched from the temp folder",
    "Extract the archive file",
)


def _clean(line: str) -> str:
    """Quita secuencias ANSI y el retorno de carro/nueva línea sobrante."""
    return _ANSI_RE.sub("", line).replace("\r", "").rstrip("\n")


def _output_has_error(text: str) -> bool:
    lower = text.lower()
    return any(m.lower() in lower for m in _ERROR_MARKERS)


def _mas_cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DiskHealthReport", "mas")


def ensure_mas_script() -> str | None:
    """Copia MAS_AIO.cmd a AppData si hace falta y devuelve la ruta persistente."""
    bundled = bundled_assets.mas_script_path()
    if not bundled:
        return None
    dest_dir = _mas_cache_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "MAS_AIO.cmd")
    try:
        if not os.path.isfile(dest):
            shutil.copy2(bundled, dest)
        else:
            src_mtime = os.path.getmtime(bundled)
            dst_mtime = os.path.getmtime(dest)
            src_size = os.path.getsize(bundled)
            dst_size = os.path.getsize(dest)
            if src_mtime > dst_mtime or src_size != dst_size:
                shutil.copy2(bundled, dest)
    except OSError:
        return bundled if os.path.isfile(bundled) else None
    return dest if os.path.isfile(dest) else None


def _new_console_flag() -> int:
    return getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


def _hidden_kwargs() -> dict:
    """kwargs para ejecutar un proceso sin ventana visible (sin redirigir stdin)."""
    kwargs: dict = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


def _stream_process(cmd: list, on_line: Callable[[str], None],
                    cancel: Optional[threading.Event],
                    cwd: str | None = None) -> Tuple[bool, str]:
    """Ejecuta un comando oculto y transmite stdout línea a línea."""
    popen_kw = _hidden_kwargs()
    if cwd:
        popen_kw["cwd"] = cwd
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            **popen_kw,
        )
    except Exception:
        return False, "activation_failed"

    collected: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                try:
                    proc.terminate()
                except Exception:
                    pass
                break
            cleaned = _clean(line)
            collected.append(cleaned)
            on_line(cleaned)
        rc = proc.wait()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        return False, "activation_failed"

    if cancel is not None and cancel.is_set():
        return False, "activation_cancelled"

    full = "\n".join(collected)
    had_error = _output_has_error(full)
    ok = rc == 0 and not had_error
    return ok, ("" if ok else "activation_failed")


def run_mas_action(switches: list, on_line: Callable[[str], None],
                   cancel: Optional[threading.Event] = None) -> Tuple[bool, str]:
    """Ejecuta una acción de MAS en segundo plano (oculta) y transmite la salida."""
    if sys.platform != "win32":
        return False, "activation_failed"

    path = ensure_mas_script()
    if path:
        cwd = os.path.dirname(path)
        return _stream_process(
            ["cmd", "/c", path, *switches], on_line, cancel, cwd=cwd)

    if _has_internet():
        ps_cmd = (
            "& ([ScriptBlock]::Create((irm https://get.activated.win))) "
            + " ".join(switches)
        )
        return _stream_process(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", ps_cmd],
            on_line, cancel,
        )

    return False, "activation_no_internet"


def run_status(on_line: Callable[[str], None],
               cancel: Optional[threading.Event] = None) -> Tuple[bool, str]:
    """Muestra el estado de activación de Windows vía slmgr (oculto)."""
    if sys.platform != "win32":
        return False, "activation_failed"
    slmgr = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                         "System32", "slmgr.vbs")
    return _stream_process(["cscript", "//nologo", slmgr, "/xpr"], on_line, cancel)


def _has_internet(timeout: float = 3.0) -> bool:
    """Comprueba conectividad intentando conectar por HTTPS (443)."""
    for host in (_ONLINE_HOST, _FALLBACK_HOST):
        try:
            with socket.create_connection((host, 443), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _launch_online() -> None:
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-NoExit",
            "-Command",
            _ONLINE_PS_COMMAND,
        ],
        creationflags=_new_console_flag(),
    )


def _launch_offline(path: str) -> None:
    cwd = os.path.dirname(path) or None
    subprocess.Popen(
        ["cmd", "/c", path],
        creationflags=_new_console_flag(),
        cwd=cwd,
    )


def launch_mas() -> Tuple[bool, str]:
    """Lanza MAS en una consola visible."""
    if sys.platform != "win32":
        return False, "activation_failed"

    if _has_internet():
        try:
            _launch_online()
            return True, "online"
        except Exception:
            pass

    path = ensure_mas_script()
    if path:
        try:
            _launch_offline(path)
            return True, "offline"
        except Exception:
            return False, "activation_failed"

    return False, "activation_no_internet"
