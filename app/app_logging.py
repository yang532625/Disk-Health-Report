# -*- coding: utf-8 -*-
"""Registro de errores fatales para depuración del .exe."""

import os
import sys
import traceback
from datetime import datetime
from typing import Callable, Optional

_CRASH_LOG_PATH: Optional[str] = None
_PREVIOUS_HOOK: Optional[Callable] = None


def get_crash_log_path() -> str:
    global _CRASH_LOG_PATH
    if _CRASH_LOG_PATH is None:
        appdata = os.path.join(os.environ.get("APPDATA", ""), "DiskHealthReport")
        os.makedirs(appdata, exist_ok=True)
        _CRASH_LOG_PATH = os.path.join(appdata, "crash.log")
    return _CRASH_LOG_PATH


def log_exception(exc_type, exc_value, exc_tb, context: str = "") -> str:
    lines = [
        "",
        "=" * 60,
        f"{datetime.now().isoformat(timespec='seconds')}",
    ]
    if context:
        lines.append(f"Context: {context}")
    lines.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    text = "\n".join(lines)
    try:
        with open(get_crash_log_path(), "a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    return text


def _global_excepthook(exc_type, exc_value, exc_tb):
    log_exception(exc_type, exc_value, exc_tb, context="unhandled")
    if _PREVIOUS_HOOK and _PREVIOUS_HOOK is not _global_excepthook:
        _PREVIOUS_HOOK(exc_type, exc_value, exc_tb)


def install_crash_handler() -> None:
    global _PREVIOUS_HOOK
    if sys.excepthook is not _global_excepthook:
        _PREVIOUS_HOOK = sys.excepthook
        sys.excepthook = _global_excepthook


def safe_callback(fn: Callable, context: str = ""):
    """Envuelve callbacks de Tk/hilos para no tumbar mainloop en silencio."""

    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log_exception(*sys.exc_info(), context=context or fn.__name__)
            try:
                import tkinter.messagebox as messagebox
                messagebox.showerror(
                    "Disk Health Report",
                    f"An error occurred. Details were saved to:\n{get_crash_log_path()}",
                )
            except Exception:
                pass

    return wrapper
