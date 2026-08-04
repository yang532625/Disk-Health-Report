# -*- coding: utf-8 -*-
"""Detección de conexión/desconexión de discos en tiempo real (hot-plug).

Escucha los eventos nativos de hardware de Windows (WM_DEVICECHANGE) mediante
una ventana message-only creada con ctypes en un hilo dedicado, de modo que la
app reacciona en el instante en que Windows reconoce el dispositivo, sin sondear
periódicamente. Se conserva un sondeo de respaldo de baja frecuencia por si la
ventana nativa no estuviera disponible.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional

from app_logging import log_message
from disk_service import disk_signature_key, get_smartctl_path, scan_disk_signature

WM_DEVICECHANGE = 0x0219
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002

DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004
DBT_DEVNODES_CHANGED = 0x0007

HWND_MESSAGE = wintypes.HWND(-3)
DEVICE_NOTIFY_WINDOW_HANDLE = 0x00000000
DEVICE_NOTIFY_ALL_INTERFACE_CLASSES = 0x00000004
DBT_DEVTYP_DEVICEINTERFACE = 0x00000005

# Intervalo del sondeo de respaldo (mucho mayor que el polling original).
FALLBACK_INTERVAL_MS = 15000
# Los puentes USB y HDD mecánicos pueden tardar varios segundos en estar listos.
HOTPLUG_RETRY_DELAYS_MS = (1000, 3000, 6000, 10000)


if sys.platform == "win32":
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class DEV_BROADCAST_DEVICEINTERFACE(ctypes.Structure):
        _fields_ = [
            ("dbcc_size", wintypes.DWORD),
            ("dbcc_devicetype", wintypes.DWORD),
            ("dbcc_reserved", wintypes.DWORD),
            ("dbcc_classguid", ctypes.c_byte * 16),
            ("dbcc_name", wintypes.WCHAR * 1),
        ]


class DiskWatcher:
    """Notifica cambios de discos reaccionando a eventos nativos de Windows."""

    def __init__(self, root, on_change: Callable[[], None], interval_ms: int = FALLBACK_INTERVAL_MS):
        self._root = root
        self._on_change = on_change
        self._interval = interval_ms
        self._running = True
        self._polling = False
        self._poll_pending = False
        self._last_signature: Optional[frozenset[str]] = None
        self._job = None
        self._retry_jobs: list = []

        # Ventana nativa de eventos de hardware.
        self._hwnd = None
        self._notify_handle = None
        self._wndproc_ref = None
        self._class_name = f"DiskHealthDevWatcher_{id(self)}"
        self._thread = None

        if sys.platform == "win32":
            self._thread = threading.Thread(target=self._message_loop, daemon=True)
            self._thread.start()

        # Sondeo de respaldo de baja frecuencia.
        self._job = self._root.after(interval_ms, self._schedule_poll)

    # ------------------------------------------------------------------ API
    def sync(
        self,
        paths: frozenset[str],
        smart_paths: frozenset[str] = frozenset(),
    ) -> None:
        """Actualiza la firma tras un escaneo manual para evitar falsos positivos."""
        signature = {disk_signature_key(path) for path in paths}
        signature.update(
            f"smart:{disk_signature_key(path)}" for path in smart_paths
        )
        self._last_signature = frozenset(signature)

    def stop(self):
        self._running = False
        if self._job:
            try:
                self._root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        for retry_job in self._retry_jobs:
            try:
                self._root.after_cancel(retry_job)
            except Exception:
                pass
        self._retry_jobs = []
        if sys.platform == "win32" and self._hwnd:
            try:
                ctypes.windll.user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

    # ----------------------------------------------------- ventana nativa
    @staticmethod
    def _configure_ctypes(user32, kernel32):
        """Fija tipos para evitar truncamiento de handles/retornos en 64-bit."""
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

        user32.RegisterClassW.restype = wintypes.ATOM
        user32.RegisterClassW.argtypes = [ctypes.c_void_p]

        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]

        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]

        user32.RegisterDeviceNotificationW.restype = wintypes.HANDLE
        user32.RegisterDeviceNotificationW.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ]
        user32.UnregisterDeviceNotification.argtypes = [wintypes.HANDLE]

        user32.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]
        user32.DestroyWindow.argtypes = [wintypes.HWND]

    def _message_loop(self):
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._configure_ctypes(user32, kernel32)

            self._wndproc_ref = WNDPROC(self._wnd_proc)

            wndclass = WNDCLASS()
            wndclass.lpfnWndProc = self._wndproc_ref
            wndclass.lpszClassName = self._class_name
            wndclass.hInstance = kernel32.GetModuleHandleW(None)

            atom = user32.RegisterClassW(ctypes.byref(wndclass))
            if not atom:
                log_message("RegisterClassW failed; using polling", context="disk-watcher")
                return

            self._hwnd = user32.CreateWindowExW(
                0, self._class_name, self._class_name, 0,
                0, 0, 0, 0, HWND_MESSAGE, None, wndclass.hInstance, None,
            )
            if not self._hwnd:
                log_message("CreateWindowExW failed; using polling", context="disk-watcher")
                return

            self._register_device_notification(user32)

            msg = wintypes.MSG()
            while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            log_message(f"Native watcher failed: {exc}", context="disk-watcher")

    def _register_device_notification(self, user32):
        try:
            dbi = DEV_BROADCAST_DEVICEINTERFACE()
            dbi.dbcc_size = ctypes.sizeof(DEV_BROADCAST_DEVICEINTERFACE)
            dbi.dbcc_devicetype = DBT_DEVTYP_DEVICEINTERFACE
            self._notify_handle = user32.RegisterDeviceNotificationW(
                self._hwnd, ctypes.byref(dbi),
                DEVICE_NOTIFY_WINDOW_HANDLE | DEVICE_NOTIFY_ALL_INTERFACE_CLASSES,
            )
        except Exception as exc:
            self._notify_handle = None
            log_message(
                f"RegisterDeviceNotificationW failed: {exc}",
                context="disk-watcher",
            )

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        user32 = ctypes.windll.user32
        if msg == WM_DEVICECHANGE:
            if wparam in (DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE, DBT_DEVNODES_CHANGED):
                self._notify_from_native()
        elif msg == WM_CLOSE:
            if self._notify_handle:
                try:
                    user32.UnregisterDeviceNotification(self._notify_handle)
                except Exception:
                    pass
                self._notify_handle = None
            user32.DestroyWindow(hwnd)
            return 0
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _notify_from_native(self):
        """Programa reintentos escalonados en el hilo de Tk."""
        if not self._running:
            return
        try:
            self._root.after(0, self._schedule_hotplug_checks)
        except Exception as exc:
            log_message(f"Could not schedule hotplug check: {exc}", context="disk-watcher")

    def _schedule_hotplug_checks(self):
        if not self._running:
            return
        for retry_job in self._retry_jobs:
            try:
                self._root.after_cancel(retry_job)
            except Exception:
                pass
        self._retry_jobs = [
            self._root.after(delay, lambda d=delay: self._run_signature_check(d))
            for delay in HOTPLUG_RETRY_DELAYS_MS
        ]

    def _run_signature_check(self, delay_ms: int = 0):
        self._retry_jobs = [
            job for job in self._retry_jobs
            if job is not None
        ]
        self._schedule_poll(force=True)

    # ---------------------------------------------------- sondeo / firma
    def _schedule_fallback(self):
        if self._running and self._job is None:
            self._job = self._root.after(self._interval, self._schedule_poll)

    def _schedule_poll(self, force: bool = False):
        if not self._running:
            return
        if not force:
            self._job = None
        if self._polling:
            if force:
                self._poll_pending = True
            self._schedule_fallback()
            return
        self._polling = True

        def worker():
            signature: Optional[frozenset[str]] = None
            try:
                smartctl = get_smartctl_path()
                if smartctl:
                    signature = scan_disk_signature(smartctl)
            except Exception as exc:
                log_message(f"Signature poll failed: {exc}", context="disk-watcher")
            try:
                self._root.after(0, lambda: self._on_poll_done(signature))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_poll_done(self, signature: Optional[frozenset[str]]):
        self._polling = False
        poll_again = self._poll_pending
        self._poll_pending = False
        if not self._running or signature is None:
            if poll_again and self._running:
                self._schedule_poll(force=True)
            else:
                self._schedule_fallback()
            return
        if self._last_signature is None:
            self._last_signature = signature
            if poll_again:
                self._schedule_poll(force=True)
            else:
                self._schedule_fallback()
            return
        if signature != self._last_signature:
            self._last_signature = signature
            try:
                self._on_change()
            except Exception as exc:
                log_message(f"on_change failed: {exc}", context="disk-watcher")
        if poll_again and self._running:
            self._schedule_poll(force=True)
        else:
            self._schedule_fallback()
