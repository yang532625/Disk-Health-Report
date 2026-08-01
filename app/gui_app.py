# -*- coding: utf-8 -*-
"""Interfaz gráfica bilingüe para Disk Health Report."""

import ctypes
import os
import sys
import threading
import time
import tkinter as tk
import tkinter.messagebox as messagebox
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageTk

from bundled_assets import app_icon_path
from disk_service import (
    DiskInfo,
    disk_identity,
    get_app_dir,
    get_reports_dir,
    get_smartctl_path,
    get_smart_data,
    group_disks_by_category,
    is_admin,
    load_settings,
    restart_as_admin,
    save_settings,
    scan_disks_with_info,
    set_reports_dir,
)
from disk_watcher import DiskWatcher
import disk_ops
import disk_image
import partition_ops
import space_analyzer
import system_cache
import win_time
import windows_activation
import windows_defender_remover
import ventoy_runner
import win_image_job
import windows_imaging
import windows_inventory
from i18n import SUPPORTED_LANGS, t
from report_preview import ReportPreviewFrame
from version import __version__
from smart_parser import DiskReport, parsear_smartctl
from treemap_layout import layout_treemap
from ui_theme import ui_font
from ui_progress import clamp_pct


def footer_should_collapse_after_progress(*, user_pinned: bool, auto_expanded: bool) -> bool:
    """True si el footer se expandió solo por progreso y no fue fijado por el usuario."""
    return auto_expanded and not user_pinned
from virtual_list import VirtualList

# Paleta visual
COLOR_BG = "#eef2f7"
COLOR_HEADER = "#003d80"
COLOR_HEADER_SUB = "#b8d4f0"
COLOR_PRIMARY = "#0056b3"
COLOR_PRIMARY_HOVER = "#004494"
COLOR_CARD = "#ffffff"
COLOR_SSD = "#0ea5e9"
COLOR_HDD = "#0056b3"
COLOR_TEXT_MUTED = "#64748b"
COLOR_TEXT_BODY = "#334155"
COLOR_SECTION = "#003d80"
COLOR_SECTION_BG = "#e8eef5"
COLOR_APPLE_BLUE = "#0071e3"
COLOR_APPLE_BLUE_HOVER = "#0077ed"
COLOR_APPLE_GRAY_BG = "#f5f5f7"
COLOR_APPLE_GRAY_HOVER = "#e8e8ed"
COLOR_APPLE_TEXT = "#1d1d1f"
COLOR_APPLE_RED = "#d70015"
COLOR_APPLE_DISABLED = "#aeaeb2"
COLOR_USAGE_GREEN = "#22c55e"
COLOR_USAGE_YELLOW = "#ea580c"
COLOR_USAGE_RED = "#dc2626"
COLOR_RING_TRACK = "#cbd5e1"
RING_SIZE = 112
RING_SCALE = 2
SPACE_ANALYZER_TOP_N = 500
TREEMAP_HEIGHT = 320
TREEMAP_TOP_N = 48
SPACE_ROW_HEIGHT = 46
PM_ROW_HEIGHT = 44
PM_BAR_HEIGHT = 72
USAGE_POLL_INTERVAL_MS = 4000
USAGE_POLL_BUSY_TIMEOUT_MS = 18000


def usage_ring_rounded_pct(pct: float | None) -> int | None:
    """Porcentaje entero [0, 100] para el anillo, o None si no hay dato."""
    if pct is None:
        return None
    return max(0, min(100, int(round(pct))))


def usage_ring_needs_redraw(last: int | None, pct: float | None) -> bool:
    """True si el porcentaje redondeado cambió respecto al último dibujado."""
    return last != usage_ring_rounded_pct(pct)


def usage_ring_arc_angles(pct: float) -> tuple[float, float]:
    """Ángulos PIL para el arco de uso (CCW desde start a end, origen en 3 h)."""
    sweep = max(0.0, min(100.0, pct)) / 100.0 * 360.0
    return 90.0 - sweep, 90.0


def format_bytes(nbytes: int) -> str:
    if nbytes >= 1024 ** 4:
        return f"{nbytes / (1024 ** 4):.2f} TB"
    if nbytes >= 1024 ** 3:
        return f"{nbytes / (1024 ** 3):.2f} GB"
    if nbytes >= 1024 ** 2:
        return f"{nbytes / (1024 ** 2):.1f} MB"
    if nbytes >= 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes} B"


def format_usage_size_text(used: int, total: int) -> str:
    return f"{format_bytes(used)} / {format_bytes(total)}"


def usage_size_needs_update(
    last: tuple[int, int] | None, used: int, total: int,
) -> bool:
    return last != (used, total)


class DiskHealthApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.lang = self.settings.get("lang", "es")
        if self.lang not in SUPPORTED_LANGS:
            self.lang = "es"

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.configure(fg_color=COLOR_BG)
        self.title(f"{t('app_title', self.lang)} v{__version__}")
        self.geometry("860x660")
        self.minsize(720, 520)
        self._center_window()

        icon_path = app_icon_path()
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.disks: list[DiskInfo] = []
        self._prev_disk_ids: set[str] = set()
        self._scanning = False
        self._building = False
        self._silent_scan = False
        self._status_key = ""
        self._status_kwargs: dict = {}
        self._toast_job = None
        self._clock_job = None
        self._disk_watcher = None
        self._act_running = False
        self._act_active = False
        self._act_cancel = None
        self._act_output = None
        self._act_buttons = []
        self._def_running = False
        self._def_active = False
        self._def_cancel = None
        self._def_output = None
        self._def_buttons = []
        self._win_iso_active = False
        self._win_iso_running = False
        self._win_iso_job: dict | None = None
        self._win_iso_output = None
        self._win_iso_prog_list = None
        self._win_iso_base_path = None
        self._win_iso_wim_path = None
        self._win_iso_out_path = None
        self._win_iso_usb_var = None
        self._set_time_running = False
        self._set_time_active = False
        self._set_time_status_label = None
        self._set_time_entry = None
        self._set_time_btn = None
        self._usage_poll_job = None
        self._usage_poll_busy = False
        self._usage_poll_busy_since: float | None = None
        self._usage_last_pct: dict[str, int | None] = {}
        self._usage_last_bytes: dict[str, tuple[int, int] | None] = {}
        self._settings_folder_label = None
        self._disk_cards: dict = {}
        self._disk_action_btns: dict = {}
        self._disk_rings: dict = {}
        self._disk_usage_labels: dict = {}
        self._flash_jobs: list = []
        self._subview = None
        self._formatting = False
        self._cleaning_cache = False
        self._fmt = {}
        self._cache_clean_btn = None
        self._iso_path = None
        self._iso_type = None
        self._ejected_disks: dict[str, disk_ops.EjectedDiskRecord] = {}
        self._ejected_panel_visible = False
        self._ejected_toggle_btn = None
        self._ejected_items_frame = None
        self._footer = None
        self._footer_state = "idle"
        self._footer_hidden_for_preview = False
        self._footer_expanded = bool(self.settings.get("footer_expanded", False))
        self._footer_user_pinned = self._footer_expanded
        self._footer_auto_expanded = False
        self._footer_body = None
        self._footer_handle = None
        self._footer_chevron_label = None
        self._footer_handle_dot = None
        self._footer_handle_summary = None
        self._category_expanded = {"system": True, "external": True}
        self._category_sections: dict = {}
        self._space_scanning = False
        self._space_scan_cancel = None
        self._space_view_active = False
        self._tools_btn = None
        self._space_entries: list = []
        self._space_total_bytes = 0
        self._space_volume_root = ""
        self._space_selected_index = None
        self._space_treemap_layout: list = []
        self._space_treemap_indices: list = []
        self._space_vlist: VirtualList | None = None
        self._space_treemap_hit: list = []
        self._space_treemap_collapsed = False
        self._pseudo_progress_job = None
        self._pseudo_progress_active = False
        self._pseudo_progress_pct = 0.0
        self._space_progress_frame = None
        self._space_progress_bar = None
        self._space_progress_label = None
        self._pm_running = False
        self._pm_disks: list = []
        self._pm_current_disk: dict | None = None
        self._pm_selected: dict | None = None
        self._pm_seg_hit: list = []
        self._pm_vlist: VirtualList | None = None
        self._pm_disk_labels: dict = {}
        self._pm_active = False
        self._pm_part_by_offset: dict = {}
        self._ui_error_last_shown: float = 0.0

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, lambda: self._scan_disks(silent=False))

    def _schedule_ui(self, fn, *args, **kwargs):
        """Ejecuta callback en el hilo UI con captura de errores."""
        def run():
            try:
                fn(*args, **kwargs)
            except Exception:
                from app_logging import get_crash_log_path, log_exception
                import sys
                log_exception(*sys.exc_info(), context=getattr(fn, "__name__", "ui"))
                now = time.monotonic()
                if now - self._ui_error_last_shown < 2.0:
                    return
                self._ui_error_last_shown = now
                messagebox.showerror(
                    t("ui_error", self.lang),
                    t("ui_error_hint", self.lang, log=get_crash_log_path()),
                    parent=self,
                )
        self.after(0, run)

    def _center_window(self):
        self.update_idletasks()
        w, h = 860, 660
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    _CLOCK_MONTHS = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )

    def _update_clock(self):
        now = time.localtime()
        hour12 = now.tm_hour % 12 or 12
        ampm = "AM" if now.tm_hour < 12 else "PM"
        text = (
            f"{self._CLOCK_MONTHS[now.tm_mon - 1]} {now.tm_mday}, {now.tm_year}"
            f"  -  {hour12}:{now.tm_min:02d} {ampm}"
        )
        try:
            self.clock_label.configure(text=text)
        except Exception:
            return
        self._clock_job = self.after(1000, self._update_clock)

    def _lang_display(self) -> str:
        return t("lang_es", self.lang) if self.lang == "es" else t("lang_en", self.lang)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        self.header = ctk.CTkFrame(self, fg_color=COLOR_HEADER, corner_radius=0, height=100)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)
        self.header.grid_propagate(False)

        header_inner = ctk.CTkFrame(self.header, fg_color="transparent")
        header_inner.pack(fill="both", expand=True, padx=24, pady=16)
        header_inner.grid_columnconfigure(0, weight=1)

        title_row = ctk.CTkFrame(header_inner, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            title_row,
            text=t("app_title", self.lang),
            font=ui_font(size=24, weight="bold"),
            text_color="#ffffff",
            anchor="w",
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        controls = ctk.CTkFrame(title_row, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e")

        self.lang_var = ctk.StringVar(value=self._lang_display())
        self.lang_menu = ctk.CTkOptionMenu(
            controls,
            values=[t("lang_es", "es"), t("lang_en", "en")],
            variable=self.lang_var,
            command=self._on_lang_change,
            width=120,
            fg_color=COLOR_PRIMARY,
            button_color=COLOR_PRIMARY_HOVER,
            button_hover_color="#003366",
            dropdown_fg_color="#ffffff",
            dropdown_text_color=COLOR_TEXT_BODY,
        )
        self.lang_menu.grid(row=0, column=0, padx=(0, 10))

        self.settings_btn = ctk.CTkButton(
            controls,
            text=f"\u2699  {t('settings', self.lang)}",
            command=self._show_settings_view,
            width=130,
            fg_color="#ffffff",
            text_color=COLOR_PRIMARY,
            hover_color="#e8f0fa",
            border_width=1,
            border_color="#ffffff",
        )
        self.settings_btn.grid(row=0, column=1, padx=(0, 10))

        self.tools_btn = ctk.CTkButton(
            controls,
            text=f"{t('other_tools', self.lang)}  \u25bc",
            command=self._show_tools_menu,
            width=150,
            fg_color="#ffffff",
            text_color=COLOR_PRIMARY,
            hover_color="#e8f0fa",
            border_width=1,
            border_color="#ffffff",
        )
        self.tools_btn.grid(row=0, column=2, padx=(0, 10))

        self.refresh_btn = ctk.CTkButton(
            controls,
            text=t("refresh", self.lang),
            command=self._on_refresh_click,
            width=120,
            fg_color="#ffffff",
            text_color=COLOR_PRIMARY,
            hover_color="#e8f0fa",
            border_width=1,
            border_color="#ffffff",
        )
        self.refresh_btn.grid(row=0, column=3)

        subtitle_row = ctk.CTkFrame(header_inner, fg_color="transparent")
        subtitle_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        subtitle_row.grid_columnconfigure(0, weight=1)

        self.subtitle_label = ctk.CTkLabel(
            subtitle_row,
            text=t("app_subtitle", self.lang),
            font=ui_font(size=13),
            text_color=COLOR_HEADER_SUB,
            anchor="w",
        )
        self.subtitle_label.grid(row=0, column=0, sticky="w")

        self.clock_label = ctk.CTkLabel(
            subtitle_row,
            text="",
            font=ui_font(size=13, weight="bold"),
            text_color="#ffffff",
            anchor="e",
        )
        self.clock_label.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self.version_label = ctk.CTkLabel(
            subtitle_row,
            text=f"v{__version__}",
            font=ui_font(size=11),
            text_color="#7eb8e8",
            anchor="e",
        )
        self.version_label.grid(row=0, column=2, sticky="e", padx=(12, 0))

        self.admin_badge = ctk.CTkLabel(
            subtitle_row,
            text="",
            font=ui_font(size=11, weight="bold"),
            text_color="#ffffff",
            fg_color="#2d8a4e",
            corner_radius=6,
            anchor="center",
            width=120,
            height=22,
        )
        self.admin_badge.grid(row=0, column=3, sticky="e", padx=(12, 0))
        self.admin_badge.bind("<Button-1>", lambda _e: self._on_admin_badge_click())
        self._update_admin_badge()

        self._clock_job = None
        self._update_clock()
        self.after(4000, lambda: self._check_for_updates(manual=False))

        # Lista de discos
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=COLOR_BG,
            scrollbar_button_color=COLOR_PRIMARY,
            scrollbar_button_hover_color=COLOR_PRIMARY_HOVER,
        )
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))
        self.scroll.grid_columnconfigure(0, weight=1)

        self.empty_label = ctk.CTkLabel(
            self.scroll,
            text=t("scanning", self.lang, pct=0),
            text_color=COLOR_TEXT_MUTED,
            font=ui_font(size=14),
        )
        self.empty_label.grid(row=0, column=0, pady=60)

        # Footer (handle colapsable + body desplegable)
        self._footer = ctk.CTkFrame(self, fg_color="#f0f5fb", corner_radius=0)
        self._footer.grid(row=2, column=0, sticky="ew")
        self._footer.grid_columnconfigure(0, weight=1)

        accent_bar = ctk.CTkFrame(self._footer, fg_color=COLOR_PRIMARY, height=3, corner_radius=0)
        accent_bar.grid(row=0, column=0, sticky="ew")

        self._footer_handle = ctk.CTkFrame(self._footer, fg_color="#f0f5fb", corner_radius=0, height=34)
        self._footer_handle.grid(row=1, column=0, sticky="ew")
        self._footer_handle.grid_propagate(False)
        self._footer_handle.grid_columnconfigure(1, weight=1)

        handle_row = ctk.CTkFrame(self._footer_handle, fg_color="transparent")
        handle_row.grid(row=0, column=0, sticky="ew", padx=20, pady=4)
        handle_row.grid_columnconfigure(2, weight=1)

        self._footer_chevron_label = ctk.CTkLabel(
            handle_row,
            text="\u25B2",
            font=ui_font(size=12, weight="bold"),
            text_color=COLOR_PRIMARY,
            width=20,
        )
        self._footer_chevron_label.grid(row=0, column=0, padx=(0, 8))

        self._footer_handle_dot = ctk.CTkLabel(
            handle_row,
            text="\u25cf",
            font=ui_font(size=12),
            text_color=COLOR_USAGE_GREEN,
            width=16,
        )
        self._footer_handle_dot.grid(row=0, column=1, padx=(0, 6))

        self._footer_handle_summary = ctk.CTkLabel(
            handle_row,
            text="",
            text_color=COLOR_APPLE_TEXT,
            font=ui_font(size=12, weight="bold"),
            anchor="w",
        )
        self._footer_handle_summary.grid(row=0, column=2, sticky="w")

        for w in (self._footer_handle, handle_row, self._footer_chevron_label,
                  self._footer_handle_dot, self._footer_handle_summary):
            w.bind("<Button-1>", self._on_footer_handle_click)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

        self._footer_body = ctk.CTkFrame(self._footer, fg_color="transparent")
        self._footer_body.grid(row=2, column=0, sticky="ew")
        self._footer_body.grid_columnconfigure(0, weight=1)

        footer_inner = ctk.CTkFrame(self._footer_body, fg_color="transparent")
        footer_inner.grid(row=0, column=0, sticky="ew", padx=28, pady=(4, 14))
        footer_inner.grid_columnconfigure(0, weight=1)

        status_row = ctk.CTkFrame(footer_inner, fg_color="transparent")
        status_row.grid(row=0, column=0, sticky="w")

        self._status_dot = ctk.CTkLabel(
            status_row,
            text="\u25cf",
            font=ui_font(size=14),
            text_color=COLOR_USAGE_GREEN,
            width=18,
        )
        self._status_dot.pack(side="left", padx=(0, 6))

        self.status_label = ctk.CTkLabel(
            status_row,
            text="",
            text_color=COLOR_APPLE_TEXT,
            font=ui_font(size=14, weight="bold"),
            anchor="w",
        )
        self.status_label.pack(side="left")

        bottom_row = ctk.CTkFrame(footer_inner, fg_color="transparent")
        bottom_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        bottom_row.grid_columnconfigure(0, weight=1)

        self._reports_chip = ctk.CTkFrame(
            bottom_row,
            fg_color="#ffffff",
            corner_radius=8,
            border_width=1,
            border_color="#c5d4e4",
        )
        self._reports_chip.grid(row=0, column=0, sticky="w")

        chip_inner = ctk.CTkFrame(self._reports_chip, fg_color="transparent")
        chip_inner.pack(padx=10, pady=6)

        ctk.CTkLabel(
            chip_inner,
            text="\U0001F4C1",
            font=ui_font(size=12),
            text_color=COLOR_PRIMARY,
        ).pack(side="left", padx=(0, 6))

        self.reports_label = ctk.CTkLabel(
            chip_inner,
            text=f"{t('reports_folder', self.lang)}: {get_reports_dir()}",
            text_color=COLOR_TEXT_BODY,
            font=ui_font(size=11),
            anchor="w",
        )
        self.reports_label.pack(side="left")

        def _open_reports_from_chip(_event=None):
            self._open_reports_folder()

        for w in (self._reports_chip, chip_inner, self.reports_label):
            w.bind("<Button-1>", _open_reports_from_chip)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

        self._ejected_toggle_btn = ctk.CTkButton(
            bottom_row,
            text=t("ejected_drives", self.lang),
            command=self._toggle_ejected_panel,
            width=190,
            height=28,
            corner_radius=8,
            fg_color=COLOR_APPLE_GRAY_BG,
            hover_color=COLOR_APPLE_GRAY_HOVER,
            text_color=COLOR_APPLE_TEXT,
            font=ui_font(size=11),
        )
        self._ejected_toggle_btn.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self._ejected_toggle_btn.grid_remove()

        self._progress_frame = ctk.CTkFrame(footer_inner, fg_color="transparent")
        self._progress_frame.grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 0))
        self._progress_frame.grid_remove()

        self.progress = ctk.CTkProgressBar(
            self._progress_frame,
            mode="determinate",
            progress_color=COLOR_PRIMARY,
            fg_color="#d4e4f7",
            width=240,
            height=14,
            corner_radius=7,
        )
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress.set(0)

        self._progress_badge = ctk.CTkFrame(
            self._progress_frame, fg_color=COLOR_PRIMARY, corner_radius=6,
        )
        self._progress_badge.pack(side="left", padx=(10, 0))

        self.progress_pct_label = ctk.CTkLabel(
            self._progress_badge,
            text="0%",
            text_color="#ffffff",
            font=ui_font(size=11, weight="bold"),
            width=44,
        )
        self.progress_pct_label.pack(padx=6, pady=2)

        self._set_footer_state("idle")

        self._ejected_panel = ctk.CTkFrame(self._footer_body, fg_color="#f8fafc", corner_radius=8)
        self._ejected_panel.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 10))
        self._ejected_panel.grid_remove()
        self._ejected_items_frame = ctk.CTkFrame(self._ejected_panel, fg_color="transparent")
        self._ejected_items_frame.pack(fill="x", padx=12, pady=10)

        self._apply_footer_collapsed_state()
        self._update_footer_toggle_label()

    def _change_reports_dir(self, parent=None):
        chosen = filedialog.askdirectory(
            parent=parent or self,
            initialdir=get_reports_dir(),
            title=t("change_folder", self.lang),
        )
        if not chosen:
            return
        try:
            set_reports_dir(chosen)
        except OSError as e:
            messagebox.showerror(t("report_error", self.lang), str(e), parent=parent or self)
            return
        current = get_reports_dir()
        self.reports_label.configure(text=f"{t('reports_folder', self.lang)}: {current}")
        if getattr(self, "_settings_folder_label", None) is not None:
            try:
                self._settings_folder_label.configure(text=current)
            except Exception:
                pass
        self._show_transient_status("folder_changed")

    def _open_reports_folder(self):
        path = get_reports_dir()
        try:
            os.startfile(path)
        except Exception:
            messagebox.showerror(t("report_error", self.lang), path, parent=self)

    def _visible_disks(self) -> list[DiskInfo]:
        return [d for d in self.disks if disk_identity(d) not in self._ejected_disks]

    def _prune_ejected_disks(self):
        scanned = {disk_identity(d) for d in self.disks}
        for ident in list(self._ejected_disks.keys()):
            if ident not in scanned:
                del self._ejected_disks[ident]

    def _update_status_disk_count(self):
        active = len(self._visible_disks())
        if active:
            self._set_status("disks_detected", count=active)
        elif self._ejected_disks:
            self._set_status("all_ejected")
        else:
            self._set_status("no_disks")

    def _update_ejected_ui(self):
        count = len(self._ejected_disks)
        if self._ejected_toggle_btn is None:
            return
        if count:
            arrow = "\u25BC" if self._ejected_panel_visible else "\u25B6"
            label = t("ejected_drives_count", self.lang, count=count)
            self._ejected_toggle_btn.configure(text=f"{arrow}  {label}")
            self._ejected_toggle_btn.grid()
        else:
            self._ejected_panel_visible = False
            if self._ejected_panel is not None:
                self._ejected_panel.grid_remove()
            self._ejected_toggle_btn.grid_remove()
            return
        self._rebuild_ejected_list()

    def _rebuild_ejected_list(self):
        if self._ejected_items_frame is None:
            return
        for widget in self._ejected_items_frame.winfo_children():
            widget.destroy()
        if not self._ejected_disks:
            ctk.CTkLabel(
                self._ejected_items_frame,
                text=t("ejected_empty_hint", self.lang),
                text_color=COLOR_TEXT_MUTED,
                font=ui_font(size=11),
                anchor="w",
            ).pack(anchor="w")
            return
        for ident, record in self._ejected_disks.items():
            disk = record.disk
            brand = self._disk_brand_label(disk)
            letters = ", ".join(record.letters) if record.letters else "-"
            row = ctk.CTkFrame(self._ejected_items_frame, fg_color="#ffffff", corner_radius=8)
            row.pack(fill="x", pady=(0, 6))
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(
                inner,
                text=f"{brand.upper()}  ·  {letters}",
                font=ui_font(size=12, weight="bold"),
                text_color=COLOR_TEXT_BODY,
                anchor="w",
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                inner,
                text=t("remount", self.lang),
                width=90,
                height=28,
                corner_radius=8,
                fg_color=COLOR_APPLE_BLUE,
                hover_color=COLOR_APPLE_BLUE_HOVER,
                text_color="#ffffff",
                font=ui_font(size=11),
                command=lambda i=ident: self._remount_disk(i),
            ).pack(side="right")

    def _toggle_ejected_panel(self):
        if not self._ejected_disks or self._ejected_panel is None:
            return
        self._ejected_panel_visible = not self._ejected_panel_visible
        if self._ejected_panel_visible:
            self._ejected_panel.grid()
        else:
            self._ejected_panel.grid_remove()
        self._update_ejected_ui()

    def _remount_disk(self, ident: str):
        record = self._ejected_disks.get(ident)
        if not record:
            return

        def worker():
            ok = disk_ops.remount_disk(record)
            self._schedule_ui(self._after_remount, ident, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _after_remount(self, ident: str, ok: bool):
        if ok:
            self._ejected_disks.pop(ident, None)
            self._update_ejected_ui()
        self._show_transient_status("remount_done" if ok else "remount_failed")
        self._scan_disks(silent=True)

    # ---- Navegacion de vistas internas (sin popups) ----
    def _on_refresh_click(self):
        self._show_disks_view()
        self._scan_disks(silent=False)

    def _clear_subview(self):
        self._settings_folder_label = None
        self._cache_clean_btn = None
        self._fmt = {}
        if self._space_scan_cancel is not None:
            self._space_scan_cancel.set()
        self._space_scanning = False
        self._space_view_active = False
        self._space_vlist = None
        self._pm_active = False
        self._act_active = False
        if self._act_cancel is not None:
            self._act_cancel.set()
        self._act_running = False
        self._act_output = None
        self._act_buttons = []
        self._def_active = False
        if self._def_cancel is not None:
            self._def_cancel.set()
        self._def_running = False
        self._def_output = None
        self._def_buttons = []
        self._win_iso_active = False
        self._win_iso_running = False
        self._win_iso_output = None
        self._win_iso_prog_list = None
        self._set_time_active = False
        self._set_time_running = False
        self._set_time_status_label = None
        self._set_time_entry = None
        self._set_time_btn = None
        if self._subview is not None:
            try:
                self._subview.destroy()
            except Exception:
                pass
            self._subview = None

    def _show_disks_view(self):
        if self._space_scan_cancel is not None:
            self._space_scan_cancel.set()
        self._space_scanning = False
        self._clear_subview()
        self.scroll.grid()
        self._show_app_footer()

    def _on_footer_handle_click(self, _event=None):
        self._toggle_footer_body(user_action=True)

    def _toggle_footer_body(self, force: bool | None = None, *, user_action: bool = False):
        if force is not None:
            expanded = force
        else:
            expanded = not self._footer_expanded
        if user_action:
            self._footer_user_pinned = expanded
            self._footer_auto_expanded = False
        self._footer_expanded = expanded
        self.settings["footer_expanded"] = expanded
        save_settings(self.settings)
        self._apply_footer_collapsed_state()
        self._update_footer_toggle_label()

    def _apply_footer_collapsed_state(self):
        if self._footer_body is None:
            return
        if self._footer_expanded:
            self._footer_body.grid(row=2, column=0, sticky="ew")
        else:
            self._footer_body.grid_remove()

    def _update_footer_toggle_label(self):
        if self._footer_chevron_label is not None:
            chevron = "\u25BC" if self._footer_expanded else "\u25B2"
            tip = t(
                "footer_collapse" if self._footer_expanded else "footer_expand",
                self.lang,
            )
            try:
                self._footer_chevron_label.configure(text=chevron)
                self._footer_handle.configure(cursor="hand2")
            except Exception:
                pass
            if self._footer_handle is not None:
                try:
                    self._footer_handle.configure(
                        cursor="hand2",
                    )
                except Exception:
                    pass
            _ = tip
        self._update_footer_handle_summary()

    def _update_footer_handle_summary(self):
        if self._footer_handle_summary is None:
            return
        if self._status_key:
            text = t(self._status_key, self.lang, **self._status_kwargs)
        else:
            active = len(self._visible_disks())
            if active:
                text = t("disks_detected", self.lang, count=active)
            elif self._ejected_disks:
                text = t("all_ejected", self.lang)
            else:
                text = t("no_disks", self.lang)
        try:
            self._footer_handle_summary.configure(text=text)
        except Exception:
            pass

    def _hide_app_footer(self):
        if self._footer is not None:
            try:
                self._footer.grid_remove()
                self._footer_hidden_for_preview = True
            except Exception:
                pass

    def _show_app_footer(self):
        if self._footer is not None and self._footer_hidden_for_preview:
            try:
                self._footer.grid(row=2, column=0, sticky="ew")
                self._footer_hidden_for_preview = False
            except Exception:
                pass

    def _show_tools_menu(self):
        if (self._formatting or self._cleaning_cache or self._space_scanning
                or self._pm_running or self._act_running or self._def_running
                or self._set_time_running or self._win_iso_running):
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label=t("other_tools_clean_cache", self.lang),
            command=self._clean_cache_click,
        )
        menu.add_command(
            label=t("other_tools_space_analyzer", self.lang),
            command=self._show_space_analyzer_view,
        )
        menu.add_command(
            label=t("other_tools_partition_manager", self.lang),
            command=self._show_partition_manager_view,
        )
        win_menu = tk.Menu(menu, tearoff=0)
        win_menu.add_command(
            label=t("windows_set_local_time", self.lang),
            command=self._show_set_local_time_view,
        )
        win_menu.add_command(
            label=t("windows_activation", self.lang),
            command=self._show_windows_activation_view,
        )
        win_menu.add_command(
            label=t("windows_defender_remover", self.lang),
            command=self._show_defender_remover_view,
        )
        win_menu.add_command(
            label=t("other_tools_win_iso", self.lang),
            command=self._show_win_iso_view,
        )
        menu.add_cascade(label=t("other_tools_windows", self.lang), menu=win_menu)
        try:
            x = self.tools_btn.winfo_rootx()
            y = self.tools_btn.winfo_rooty() + self.tools_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _make_back_header(self, parent, title_key):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 12))
        back_btn = ctk.CTkButton(
            bar,
            text=f"\u2190  {t('back', self.lang)}",
            command=self._show_disks_view,
            width=110,
            height=36,
            corner_radius=18,
            fg_color="#ffffff",
            hover_color="#eef2f7",
            border_width=1,
            border_color="#c5d4e4",
            text_color=COLOR_PRIMARY,
            text_color_disabled=COLOR_APPLE_DISABLED,
            font=ui_font(size=13, weight="bold"),
        )
        back_btn.pack(side="left")
        ctk.CTkLabel(
            bar,
            text=t(title_key, self.lang),
            font=ui_font(size=18, weight="bold"),
            text_color=COLOR_SECTION,
        ).pack(side="left", padx=(14, 0))
        return back_btn

    def _show_settings_view(self):
        if self._formatting or self._cleaning_cache:
            return
        self.scroll.grid_remove()
        self._clear_subview()

        panel = ctk.CTkScrollableFrame(
            self,
            fg_color=COLOR_BG,
            scrollbar_button_color=COLOR_PRIMARY,
            scrollbar_button_hover_color=COLOR_PRIMARY_HOVER,
        )
        panel.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))
        panel.grid_columnconfigure(0, weight=1)
        self._subview = panel

        self._make_back_header(panel, "settings_title")

        card = ctk.CTkFrame(panel, fg_color=COLOR_CARD, corner_radius=12,
                            border_width=1, border_color="#c5d4e4")
        card.pack(fill="x", pady=(0, 12))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)

        ctk.CTkLabel(
            inner,
            text=t("settings_reports_section", self.lang),
            font=ui_font(size=14, weight="bold"),
            text_color=COLOR_SECTION,
            anchor="w",
        ).pack(anchor="w")

        self._settings_folder_label = ctk.CTkLabel(
            inner,
            text=get_reports_dir(),
            font=ui_font(size=12),
            text_color=COLOR_TEXT_BODY,
            anchor="w",
            wraplength=560,
            justify="left",
        )
        self._settings_folder_label.pack(anchor="w", pady=(6, 14), fill="x")

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(anchor="w", fill="x")

        ctk.CTkButton(
            btn_row,
            text=t("change_folder", self.lang),
            command=lambda: self._change_reports_dir(parent=self),
            width=160,
            height=34,
            corner_radius=10,
            fg_color=COLOR_APPLE_BLUE,
            hover_color=COLOR_APPLE_BLUE_HOVER,
            text_color="#ffffff",
        ).pack(side="left")

        ctk.CTkButton(
            btn_row,
            text=t("open_folder", self.lang),
            command=self._open_reports_folder,
            width=160,
            height=34,
            corner_radius=10,
            fg_color=COLOR_APPLE_GRAY_BG,
            hover_color=COLOR_APPLE_GRAY_HOVER,
            text_color=COLOR_APPLE_TEXT,
        ).pack(side="left", padx=(10, 0))

        updates = ctk.CTkFrame(panel, fg_color=COLOR_CARD, corner_radius=12,
                               border_width=1, border_color="#c5d4e4")
        updates.pack(fill="x", pady=(0, 12))
        upd_inner = ctk.CTkFrame(updates, fg_color="transparent")
        upd_inner.pack(fill="x", padx=20, pady=18)
        ctk.CTkLabel(
            upd_inner,
            text=t("settings_updates_section", self.lang),
            font=ui_font(size=14, weight="bold"),
            text_color=COLOR_SECTION,
            anchor="w",
        ).pack(anchor="w")
        self._update_status_label = ctk.CTkLabel(
            upd_inner,
            text=f"v{__version__}",
            font=ui_font(size=12),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._update_status_label.pack(anchor="w", pady=(6, 8), fill="x")

        self._update_progress = ctk.CTkProgressBar(
            upd_inner,
            height=12,
            progress_color=COLOR_APPLE_BLUE,
            fg_color=COLOR_APPLE_GRAY_BG,
        )
        self._update_progress.set(0)
        self._update_pct_label = ctk.CTkLabel(
            upd_inner,
            text="",
            font=ui_font(size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )

        btn_row = ctk.CTkFrame(upd_inner, fg_color="transparent")
        btn_row.pack(anchor="w", fill="x")
        self._check_updates_btn = ctk.CTkButton(
            btn_row,
            text=t("check_updates", self.lang),
            command=lambda: self._check_for_updates(manual=True),
            width=200,
            height=34,
            corner_radius=10,
            fg_color=COLOR_APPLE_BLUE,
            hover_color=COLOR_APPLE_BLUE_HOVER,
            text_color="#ffffff",
        )
        self._check_updates_btn.pack(side="left")
        self._update_now_btn = ctk.CTkButton(
            btn_row,
            text=t("update_now", self.lang),
            command=self._on_update_now_clicked,
            width=140,
            height=34,
            corner_radius=10,
            fg_color="#0d9488",
            hover_color="#0f766e",
            text_color="#ffffff",
            state="disabled",
        )
        self._update_now_btn.pack(side="left", padx=(10, 0))
        if getattr(self, "_pending_update", None) is None:
            self._pending_update = None
        self._update_apply_busy = getattr(self, "_update_apply_busy", False)
        pending = self._pending_update
        if pending is not None and not self._update_apply_busy:
            self._update_now_btn.configure(state="normal")
            self._update_status_label.configure(
                text=t(
                    "update_available_status",
                    self.lang,
                    latest=pending.version,
                    current=__version__,
                )
            )

        about = ctk.CTkFrame(panel, fg_color=COLOR_CARD, corner_radius=12,
                             border_width=1, border_color="#c5d4e4")
        about.pack(fill="x")
        about_inner = ctk.CTkFrame(about, fg_color="transparent")
        about_inner.pack(fill="x", padx=20, pady=18)
        ctk.CTkLabel(
            about_inner,
            text=t("settings_about_section", self.lang),
            font=ui_font(size=14, weight="bold"),
            text_color=COLOR_SECTION,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            about_inner,
            text=f"{t('app_title', self.lang)}  v{__version__}",
            font=ui_font(size=12),
            text_color=COLOR_TEXT_BODY,
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))
        ctk.CTkLabel(
            about_inner,
            text=t("tested_by", self.lang),
            font=ui_font(size=12),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(
            about_inner,
            text=t("settings_multiboot_gpl", self.lang),
            font=ui_font(size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(8, 0))

    def _check_for_updates(self, manual: bool = False):
        if getattr(self, "_update_check_busy", False):
            return
        self._update_check_busy = True
        if manual and getattr(self, "_update_status_label", None) is not None:
            try:
                self._update_status_label.configure(text=t("update_checking", self.lang))
            except Exception:
                pass

        def worker():
            import app_updater

            info = None
            try:
                local_dirs = [
                    get_app_dir(),
                    os.path.join(get_app_dir(), "installer"),
                    os.path.join(get_app_dir(), "release"),
                    get_reports_dir(),
                ]
                info = app_updater.check_for_updates(local_dirs=local_dirs)
            except Exception:
                info = None
            self.after(0, lambda: self._on_update_check_done(info, manual))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_done(self, info, manual: bool):
        self._update_check_busy = False
        if getattr(self, "_update_apply_busy", False):
            return
        if info is None:
            self._pending_update = None
            self._set_update_now_enabled(False)
            if manual:
                messagebox.showinfo(
                    t("update_up_to_date_title", self.lang),
                    t("update_up_to_date_body", self.lang, current=__version__),
                    parent=self,
                )
            self._set_update_status(
                t("update_up_to_date_body", self.lang, current=__version__)
                if manual
                else f"v{__version__}"
            )
            return

        self._pending_update = info
        self._set_update_now_enabled(True)
        self._set_update_status(
            t(
                "update_available_status",
                self.lang,
                latest=info.version,
                current=__version__,
            )
        )
        # En búsqueda manual, preguntar; al inicio solo habilitar el botón Actualizar.
        if not manual:
            return
        ok = messagebox.askyesno(
            t("update_available_title", self.lang),
            t(
                "update_available_body",
                self.lang,
                latest=info.version,
                current=__version__,
                source=(
                    t("update_source_github", self.lang)
                    if info.source == "github"
                    else t("update_source_local", self.lang)
                ),
            ),
            parent=self,
        )
        if ok:
            self._apply_update(info)

    def _on_update_now_clicked(self):
        info = getattr(self, "_pending_update", None)
        if not info:
            self._check_for_updates(manual=True)
            return
        self._apply_update(info)

    def _set_update_now_enabled(self, enabled: bool):
        btn = getattr(self, "_update_now_btn", None)
        if btn is None:
            return
        try:
            btn.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass

    def _set_update_status(self, text: str):
        label = getattr(self, "_update_status_label", None)
        if label is None:
            return
        try:
            label.configure(text=text)
        except Exception:
            pass

    def _show_update_progress_ui(self, show: bool):
        bar = getattr(self, "_update_progress", None)
        pct = getattr(self, "_update_pct_label", None)
        btn_row = getattr(self, "_check_updates_btn", None)
        btn_row = btn_row.master if btn_row is not None else None
        if bar is None or pct is None:
            return
        try:
            if show:
                if btn_row is not None:
                    bar.pack(anchor="w", fill="x", pady=(0, 4), before=btn_row)
                    pct.pack(anchor="w", pady=(0, 8), before=btn_row)
                else:
                    bar.pack(anchor="w", fill="x", pady=(0, 4))
                    pct.pack(anchor="w", pady=(0, 8))
            else:
                bar.pack_forget()
                pct.pack_forget()
        except Exception:
            pass

    def _set_update_progress(self, fraction: float, phase: str = "download"):
        frac = max(0.0, min(float(fraction), 1.0))
        pct = int(round(clamp_pct(frac * 100)))
        bar = getattr(self, "_update_progress", None)
        pct_label = getattr(self, "_update_pct_label", None)
        if bar is not None and pct_label is not None:
            self._show_update_progress_ui(True)
            try:
                bar.set(frac)
            except Exception:
                pass
            try:
                pct_label.configure(text=t("update_pct", self.lang, pct=pct))
            except Exception:
                pass
        # También la barra del pie (visible aunque no esté en Ajustes)
        try:
            self._set_progress_pct(float(pct), update_status=False)
        except Exception:
            pass
        if phase == "download":
            msg = t("update_downloading", self.lang, pct=pct)
        elif phase == "done":
            msg = t("update_progress_done", self.lang)
        else:
            msg = t("update_installing", self.lang, pct=pct)
        self._set_update_status(msg)
        try:
            self.status_label.configure(text=msg)
            self._update_footer_handle_summary()
        except Exception:
            pass

    def _apply_update(self, info):
        import app_updater

        if getattr(self, "_update_apply_busy", False):
            self._set_update_status(t("update_busy", self.lang))
            return
        self._update_apply_busy = True
        self._set_update_now_enabled(False)
        try:
            self._check_updates_btn.configure(state="disabled")
        except Exception:
            pass
        self._set_update_progress(0.0, "download")

        def worker():
            try:
                def on_progress(frac: float, phase: str):
                    self.after(0, lambda f=frac, p=phase: self._set_update_progress(f, p))

                app_updater.apply_update(info, progress_callback=on_progress, silent=True)
                self.after(0, self._on_update_apply_done)
            except Exception as exc:
                self.after(0, lambda: self._on_update_apply_failed(exc, info))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_apply_done(self):
        self._set_update_progress(1.0, "done")
        # El instalador silencioso cerrará y reiniciará la app.
        try:
            self.after(800, self.destroy)
        except Exception:
            pass

    def _on_update_apply_failed(self, exc, info):
        import app_updater
        import webbrowser

        self._update_apply_busy = False
        self._show_update_progress_ui(False)
        try:
            self._check_updates_btn.configure(state="normal")
        except Exception:
            pass
        self._set_update_now_enabled(True)
        self._set_update_status(t("update_failed", self.lang))
        err_text = str(exc)
        if "UAC" in err_text or "cancel" in err_text.lower():
            err_text = t("update_uac_cancelled", self.lang)
        messagebox.showerror(
            t("update_failed", self.lang),
            err_text,
            parent=self,
        )
        # Fallback: abrir la página de releases
        try:
            webbrowser.open(info.download_url or app_updater.GITHUB_RELEASES_URL)
        except Exception:
            pass

    def _collect_drive_letters(self) -> list[str]:
        letters: set[str] = set()
        for disk in self._visible_disks():
            for letter in disk_ops.get_drive_letters(disk):
                clean = letter.strip().rstrip(":").upper()
                if clean:
                    letters.add(f"{clean}:")
        return sorted(letters)

    def _format_bytes(self, nbytes: int) -> str:
        return format_bytes(nbytes)

    def _show_space_analyzer_view(self):
        if self._formatting or self._cleaning_cache or self._space_scanning:
            return
        self.scroll.grid_remove()
        self._clear_subview()
        self._space_vlist = None
        self._space_view_active = True

        panel = ctk.CTkFrame(self, fg_color=COLOR_BG)
        panel.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)
        self._subview = panel

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)

        self._make_back_header(top, "space_analyzer_title")

        card = ctk.CTkFrame(
            top, fg_color=COLOR_CARD, corner_radius=12,
            border_width=1, border_color="#c5d4e4",
        )
        card.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)

        ctk.CTkLabel(
            inner,
            text=t("space_analyzer_desc", self.lang),
            font=ui_font(size=12),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        controls = ctk.CTkFrame(inner, fg_color="transparent")
        controls.pack(anchor="w", fill="x")

        letters = self._collect_drive_letters()
        if not letters:
            ctk.CTkLabel(
                inner,
                text=t("space_analyzer_no_drives", self.lang),
                font=ui_font(size=12),
                text_color=COLOR_TEXT_MUTED,
                anchor="w",
            ).pack(anchor="w", pady=(8, 0))
            self._space_drive_var = ctk.StringVar(value="")
            return

        self._space_drive_var = ctk.StringVar(value=letters[0])
        ctk.CTkLabel(
            controls,
            text=t("space_analyzer_select_drive", self.lang),
            font=ui_font(size=12, weight="bold"),
            text_color=COLOR_TEXT_BODY,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkOptionMenu(
            controls,
            values=letters,
            variable=self._space_drive_var,
            width=90,
            fg_color=COLOR_PRIMARY,
            button_color=COLOR_PRIMARY_HOVER,
            button_hover_color="#003366",
            dropdown_fg_color="#ffffff",
            dropdown_text_color=COLOR_TEXT_BODY,
        ).pack(side="left", padx=(0, 12))

        self._space_scan_btn = ctk.CTkButton(
            controls,
            text=t("space_analyzer_scan", self.lang),
            command=self._start_space_scan,
            width=120,
            height=34,
            corner_radius=10,
            fg_color=COLOR_APPLE_BLUE,
            hover_color=COLOR_APPLE_BLUE_HOVER,
            text_color="#ffffff",
        )
        self._space_scan_btn.pack(side="left", padx=(0, 8))

        self._space_cancel_btn = ctk.CTkButton(
            controls,
            text=t("space_analyzer_cancel", self.lang),
            command=self._cancel_space_scan,
            width=100,
            height=34,
            corner_radius=10,
            fg_color=COLOR_APPLE_GRAY_BG,
            hover_color=COLOR_APPLE_GRAY_HOVER,
            text_color=COLOR_TEXT_BODY,
            state="disabled",
        )
        self._space_cancel_btn.pack(side="left")

        self._space_progress_frame = ctk.CTkFrame(inner, fg_color="transparent")
        self._space_progress_bar = ctk.CTkProgressBar(
            self._space_progress_frame,
            mode="determinate",
            progress_color=COLOR_PRIMARY,
            height=12,
            corner_radius=6,
        )
        self._space_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._space_progress_bar.set(0)
        self._space_progress_label = ctk.CTkLabel(
            self._space_progress_frame,
            text="0%",
            font=ui_font(12, weight="bold"),
            text_color=COLOR_PRIMARY,
            width=48,
        )
        self._space_progress_label.pack(side="left")

        self._space_treemap_toggle = ctk.CTkButton(
            top,
            text="",
            command=self._toggle_space_treemap,
            anchor="w",
            height=30,
            corner_radius=8,
            fg_color=COLOR_SECTION_BG,
            hover_color="#dbe4ef",
            text_color=COLOR_SECTION,
            font=ui_font(12, weight="bold"),
        )
        self._space_treemap_toggle.pack(fill="x", pady=(8, 2))

        self._space_treemap_wrap = ctk.CTkFrame(top, fg_color=COLOR_CARD, corner_radius=8)
        self._space_treemap_wrap.pack(fill="x", pady=(0, 4))
        self._space_treemap_canvas = tk.Canvas(
            self._space_treemap_wrap,
            height=TREEMAP_HEIGHT,
            bg="#1e293b",
            highlightthickness=0,
            bd=0,
        )
        self._space_treemap_canvas.pack(fill="x", padx=8, pady=8)
        self._space_treemap_canvas.bind("<Button-1>", self._on_space_treemap_click)
        self._space_treemap_canvas.bind("<Motion>", self._on_space_treemap_motion)
        self._space_treemap_canvas.bind("<Leave>", self._on_space_treemap_leave)
        self._update_treemap_toggle_text()

        sel_panel = ctk.CTkFrame(top, fg_color=COLOR_SECTION_BG, corner_radius=8)
        sel_panel.pack(fill="x", pady=(4, 8))
        sel_inner = ctk.CTkFrame(sel_panel, fg_color="transparent")
        sel_inner.pack(fill="x", padx=12, pady=10)

        self._space_sel_label = ctk.CTkLabel(
            sel_inner,
            text=t("space_analyzer_none_selected", self.lang),
            font=ui_font(12, weight="bold"),
            text_color=COLOR_SECTION,
            anchor="w",
        )
        self._space_sel_label.pack(anchor="w")

        sel_btns = ctk.CTkFrame(sel_inner, fg_color="transparent")
        sel_btns.pack(anchor="w", pady=(8, 0))
        self._space_open_btn = ctk.CTkButton(
            sel_btns,
            text=t("space_analyzer_open", self.lang),
            command=self._open_space_selection,
            width=110,
            height=32,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            state="disabled",
        )
        self._space_open_btn.pack(side="left", padx=(0, 8))
        self._space_delete_btn = ctk.CTkButton(
            sel_btns,
            text=t("space_analyzer_delete", self.lang),
            command=self._delete_space_selection,
            width=110,
            height=32,
            fg_color=COLOR_USAGE_RED,
            hover_color="#b91c1c",
            state="disabled",
        )
        self._space_delete_btn.pack(side="left")

        header_row = ctk.CTkFrame(top, fg_color=COLOR_SECTION_BG, corner_radius=8)
        header_row.pack(fill="x", pady=(4, 4))
        header_inner = ctk.CTkFrame(header_row, fg_color="transparent")
        header_inner.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(
            header_inner, text=t("space_analyzer_col_name", self.lang),
            font=ui_font(size=11, weight="bold"), text_color=COLOR_SECTION, width=320, anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            header_inner, text=t("space_analyzer_col_size", self.lang),
            font=ui_font(size=11, weight="bold"), text_color=COLOR_SECTION, width=100, anchor="e",
        ).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            header_inner, text=t("space_analyzer_col_percent", self.lang),
            font=ui_font(size=11, weight="bold"), text_color=COLOR_SECTION, width=60, anchor="e",
        ).pack(side="left", padx=(8, 0))

        self._space_vlist = VirtualList(
            panel,
            row_height=SPACE_ROW_HEIGHT,
            build_row=self._space_build_row,
            bind_row=self._space_bind_row,
            bg_color=COLOR_BG,
            scrollbar_color=COLOR_PRIMARY,
            scrollbar_hover=COLOR_PRIMARY_HOVER,
        )
        self._space_vlist.grid(row=1, column=0, sticky="nsew", pady=(2, 4))

        self._space_summary_label = ctk.CTkLabel(
            panel,
            text=t("space_analyzer_empty", self.lang),
            font=ui_font(size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._space_summary_label.grid(row=2, column=0, sticky="ew", pady=(6, 0))

    def _start_space_scan(self):
        if self._space_scanning or self._formatting or self._cleaning_cache:
            return
        drive = (self._space_drive_var.get() or "").strip()
        if not drive:
            return

        self._space_scan_drive = drive
        self._space_scanning = True
        self._space_scan_cancel = threading.Event()
        try:
            self._space_scan_btn.configure(state="disabled")
            self._space_cancel_btn.configure(state="normal")
        except Exception:
            pass
        self._begin_progress(0.0)
        self._show_space_progress(0.0)
        self._set_status("space_analyzer_scanning_pct", files=0, dirs=0, pct=0)

        if self._space_vlist is not None:
            self._space_vlist.set_items([])
        self._space_selected_index = None
        self._clear_space_treemap()
        self._update_space_selection_panel()

        def worker():
            def progress(files, dirs, pct):
                self._schedule_ui(
                    self._set_progress_pct, pct,
                    status_key="space_analyzer_scanning_pct",
                    files=files, dirs=dirs,
                )
                self._schedule_ui(self._show_space_progress, pct)

            entries, total = space_analyzer.scan_volume(
                drive,
                progress_cb=progress,
                cancel_event=self._space_scan_cancel,
            )
            cancelled = self._space_scan_cancel.is_set()
            self._schedule_ui(self._after_space_scan, entries, total, cancelled)

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_space_scan(self):
        if self._space_scan_cancel is not None:
            self._space_scan_cancel.set()

    def _after_space_scan(self, entries, total: int, cancelled: bool):
        if not self._space_view_active:
            self._space_scanning = False
            self._space_scan_cancel = None
            return
        self._space_scanning = False
        self._space_scan_cancel = None
        try:
            self._set_progress_pct(100.0, update_status=False)
            self._show_space_progress(100.0)
            self._space_scan_btn.configure(state="normal")
            self._space_cancel_btn.configure(state="disabled")
        except Exception:
            pass
        self.after(400, self._end_progress)
        self.after(400, self._hide_space_progress)

        if self._space_vlist is not None:
            try:
                if not self._space_vlist.winfo_exists():
                    self._space_vlist = None
                else:
                    self._space_vlist.set_items([])
            except Exception:
                self._space_vlist = None

        if cancelled:
            self._set_status("space_analyzer_cancelled")
            self._space_summary_label.configure(text=t("space_analyzer_cancelled", self.lang))
            self._space_entries = []
            self._clear_space_treemap()
            self._update_space_selection_panel()
            return

        if not entries:
            self._set_status("space_analyzer_empty")
            self._space_summary_label.configure(text=t("space_analyzer_empty", self.lang))
            self._space_entries = []
            self._clear_space_treemap()
            self._update_space_selection_panel()
            return

        self._space_entries = list(entries)
        drive = getattr(self, "_space_scan_drive", "") or ""
        self._space_volume_root = space_analyzer.normalize_volume_root(drive) or ""
        total = total or sum(e.size_bytes for e in entries) or 1
        self._space_total_bytes = total

        sizes = [e.size_bytes for e in entries]
        self._space_treemap_layout, self._space_treemap_indices = layout_treemap(
            sizes, max_items=TREEMAP_TOP_N,
        )
        self._draw_space_treemap()

        shown = entries[:SPACE_ANALYZER_TOP_N]
        if self._space_vlist is not None:
            try:
                if self._space_vlist.winfo_exists():
                    self._space_vlist.set_items(shown)
                else:
                    self._space_vlist = None
            except Exception:
                self._space_vlist = None

        self._space_summary_label.configure(
            text=t(
                "space_analyzer_top_n", self.lang,
                shown=len(shown), total=len(entries),
            ),
        )
        self._set_status("space_analyzer_done")

    def _update_treemap_toggle_text(self):
        arrow = "\u25b6" if self._space_treemap_collapsed else "\u25bc"
        try:
            self._space_treemap_toggle.configure(
                text=f"{arrow}  {t('space_analyzer_treemap', self.lang)}"
            )
        except Exception:
            pass

    def _toggle_space_treemap(self):
        self._space_treemap_collapsed = not self._space_treemap_collapsed
        if self._space_treemap_collapsed:
            self._space_treemap_wrap.pack_forget()
        else:
            self._space_treemap_wrap.pack(fill="x", pady=(0, 4),
                                          after=self._space_treemap_toggle)
            self._draw_space_treemap()
        self._update_treemap_toggle_text()

    def _clear_space_treemap(self):
        self._space_treemap_layout = []
        self._space_treemap_indices = []
        self._space_treemap_hit = []
        try:
            self._space_treemap_canvas.delete("all")
        except Exception:
            pass

    def _treemap_fill_color(self, index: int, is_dir: bool) -> str:
        if index == -1:
            return "#64748b"
        palette_dir = ("#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa")
        palette_file = ("#047857", "#059669", "#10b981", "#34d399")
        palette = palette_dir if is_dir else palette_file
        return palette[index % len(palette)]

    def _draw_space_treemap(self):
        canvas = self._space_treemap_canvas
        canvas.delete("all")
        self._space_treemap_hit = []
        if not self._space_treemap_layout:
            return

        canvas.update_idletasks()
        cw = max(canvas.winfo_width(), 200)
        ch = TREEMAP_HEIGHT
        pad = 2

        for rect in self._space_treemap_layout:
            idx = rect.index
            if idx == -1:
                label = t("space_analyzer_other", self.lang)
                is_dir = False
            elif 0 <= idx < len(self._space_entries):
                entry = self._space_entries[idx]
                label = entry.name
                is_dir = entry.is_dir
            else:
                continue

            x1 = rect.x * cw + pad
            y1 = rect.y * ch + pad
            x2 = (rect.x + rect.w) * cw - pad
            y2 = (rect.y + rect.h) * ch - pad
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue

            fill = self._treemap_fill_color(idx, is_dir)
            outline = "#ffffff" if self._space_selected_index == idx else "#334155"
            width = 2 if self._space_selected_index == idx else 1
            rid = canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width)
            self._space_treemap_hit.append((rid, idx, x1, y1, x2, y2, label))

            if (x2 - x1) > 36 and (y2 - y1) > 18:
                short = label if len(label) <= 14 else label[:11] + "..."
                canvas.create_text(
                    (x1 + x2) / 2, (y1 + y2) / 2,
                    text=short, fill="#ffffff", font=("Segoe UI", 9),
                )

    def _on_space_treemap_click(self, event):
        for rid, idx, x1, y1, x2, y2, _ in self._space_treemap_hit:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._select_space_entry(idx)
                return

    def _on_space_treemap_motion(self, event):
        for rid, idx, x1, y1, x2, y2, label in self._space_treemap_hit:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                if idx == -1:
                    size = sum(
                        e.size_bytes for e in self._space_entries[TREEMAP_TOP_N:]
                    )
                    tip = f"{label} — {self._format_bytes(size)}"
                elif 0 <= idx < len(self._space_entries):
                    entry = self._space_entries[idx]
                    tip = f"{entry.name} — {self._format_bytes(entry.size_bytes)}"
                else:
                    tip = label
                self._space_treemap_canvas.configure(cursor="hand2")
                self._space_sel_label.configure(text=tip)
                return
        self._space_treemap_canvas.configure(cursor="")
        self._update_space_selection_panel()

    def _on_space_treemap_leave(self, _event):
        self._space_treemap_canvas.configure(cursor="")
        self._update_space_selection_panel()

    def _select_space_entry(self, index: int):
        if index == -1:
            self._space_selected_index = -1
        elif 0 <= index < len(self._space_entries):
            self._space_selected_index = index
        else:
            return

        self._draw_space_treemap()
        self._update_space_selection_panel()
        if self._space_vlist is not None:
            self._space_vlist.refresh()

    def _update_space_selection_panel(self):
        idx = self._space_selected_index
        if idx is None:
            text = t("space_analyzer_none_selected", self.lang)
            open_state = "disabled"
            del_state = "disabled"
        elif idx == -1:
            other_bytes = sum(e.size_bytes for e in self._space_entries[TREEMAP_TOP_N:])
            pct = (other_bytes / self._space_total_bytes) * 100.0 if self._space_total_bytes else 0
            text = t(
                "space_analyzer_selected", self.lang,
                name=t("space_analyzer_other", self.lang),
                size=self._format_bytes(other_bytes),
                pct=pct,
            )
            open_state = "disabled"
            del_state = "disabled"
        else:
            entry = self._space_entries[idx]
            pct = (entry.size_bytes / self._space_total_bytes) * 100.0 if self._space_total_bytes else 0
            text = t(
                "space_analyzer_selected", self.lang,
                name=entry.name,
                size=self._format_bytes(entry.size_bytes),
                pct=pct,
            )
            open_state = "normal"
            del_state = "normal"
        try:
            self._space_sel_label.configure(text=text)
            self._space_open_btn.configure(state=open_state)
            self._space_delete_btn.configure(state=del_state)
        except Exception:
            pass

    def _space_build_row(self, parent):
        """Crea una fila reutilizable para la lista virtualizada."""
        row = ctk.CTkFrame(
            parent, fg_color=COLOR_CARD,
            corner_radius=8, border_width=1, border_color="#e2e8f0",
            height=SPACE_ROW_HEIGHT - 6,
        )
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=10, pady=4)

        name_btn = ctk.CTkButton(
            inner,
            text="",
            anchor="w",
            width=320,
            height=28,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#eef2f7",
            text_color=COLOR_TEXT_BODY,
            font=ui_font(12),
        )
        name_btn.pack(side="left")

        size_lbl = ctk.CTkLabel(
            inner, text="", font=ui_font(12, weight="bold"),
            text_color=COLOR_PRIMARY, width=100, anchor="e",
        )
        size_lbl.pack(side="left", padx=(8, 0))

        pct_lbl = ctk.CTkLabel(
            inner, text="", font=ui_font(12),
            text_color=COLOR_TEXT_MUTED, width=60, anchor="e",
        )
        pct_lbl.pack(side="left", padx=(8, 0))

        row._name_btn = name_btn
        row._size_lbl = size_lbl
        row._pct_lbl = pct_lbl
        return row

    def _space_bind_row(self, row, index: int, entry):
        """Rellena una fila del pool con los datos de la entrada."""
        total = self._space_total_bytes or 1
        pct = (entry.size_bytes / total) * 100.0

        prefix = "\u25bc " if entry.is_dir else "\u2022 "
        name_text = prefix + entry.name
        if len(name_text) > 48:
            name_text = name_text[:45] + "..."

        row._name_btn.configure(
            text=name_text,
            command=lambda i=index: self._select_space_entry(i),
        )
        row._size_lbl.configure(text=self._format_bytes(entry.size_bytes))
        row._pct_lbl.configure(text=f"{pct:.1f}%")

        if index == self._space_selected_index:
            row.configure(border_color=COLOR_PRIMARY, border_width=2)
        else:
            row.configure(border_color="#e2e8f0", border_width=1)

        row.bind("<Button-1>", lambda _e, i=index: self._select_space_entry(i))

    def _open_space_selection(self):
        idx = self._space_selected_index
        if idx is None or idx < 0 or idx >= len(self._space_entries):
            return
        self._open_space_path(self._space_entries[idx].path)

    def _delete_space_selection(self):
        idx = self._space_selected_index
        if idx is None or idx < 0 or idx >= len(self._space_entries):
            return
        entry = self._space_entries[idx]
        pct = (entry.size_bytes / self._space_total_bytes) * 100.0 if self._space_total_bytes else 0
        msg = t(
            "space_analyzer_delete_confirm", self.lang,
            path=entry.path,
            size=self._format_bytes(entry.size_bytes),
        )
        if not messagebox.askyesno(t("space_analyzer_delete", self.lang), msg):
            return

        ok = disk_ops.send_to_recycle_bin(entry.path, self._space_volume_root)
        if not ok:
            messagebox.showerror(
                t("space_analyzer_delete", self.lang),
                t("space_analyzer_delete_failed", self.lang),
            )
            return

        messagebox.showinfo(
            t("space_analyzer_delete", self.lang),
            t("space_analyzer_delete_ok", self.lang),
        )
        self._space_entries.pop(idx)
        self._space_total_bytes = max(
            self._space_total_bytes - entry.size_bytes, 1,
        )
        self._space_selected_index = None

        sizes = [e.size_bytes for e in self._space_entries]
        self._space_treemap_layout, self._space_treemap_indices = layout_treemap(
            sizes, max_items=TREEMAP_TOP_N,
        )
        self._draw_space_treemap()

        shown = self._space_entries[:SPACE_ANALYZER_TOP_N]
        if self._space_vlist is not None:
            self._space_vlist.set_items(shown)

        self._space_summary_label.configure(
            text=t(
                "space_analyzer_top_n", self.lang,
                shown=len(shown), total=len(self._space_entries),
            ),
        )
        self._update_space_selection_panel()

    def _open_space_path(self, path: str):
        try:
            if os.path.isdir(path):
                os.startfile(path)
            else:
                os.startfile(os.path.dirname(path) or path)
        except OSError:
            pass

    # ======================= Partition Manager =======================
    def _show_partition_manager_view(self):
        if (self._formatting or self._cleaning_cache or self._space_scanning
                or self._pm_running):
            return
        self.scroll.grid_remove()
        self._clear_subview()
        self._pm_disks = []
        self._pm_current_disk = None
        self._pm_selected = None
        self._pm_seg_hit = []
        self._pm_vlist = None
        self._pm_disk_labels = {}

        panel = ctk.CTkFrame(self, fg_color=COLOR_BG)
        panel.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)
        self._subview = panel

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)

        self._make_back_header(top, "partition_manager_title")

        card = ctk.CTkFrame(
            top, fg_color=COLOR_CARD, corner_radius=12,
            border_width=1, border_color="#c5d4e4",
        )
        card.pack(fill="x", pady=(0, 10))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(
            inner, text=t("partition_manager_desc", self.lang),
            font=ui_font(12), text_color=COLOR_TEXT_MUTED,
            anchor="w", wraplength=640, justify="left",
        ).pack(anchor="w", pady=(0, 12))

        controls = ctk.CTkFrame(inner, fg_color="transparent")
        controls.pack(anchor="w", fill="x")
        ctk.CTkLabel(
            controls, text=t("pm_select_disk", self.lang),
            font=ui_font(12, weight="bold"), text_color=COLOR_TEXT_BODY,
        ).pack(side="left", padx=(0, 8))
        self._pm_disk_var = ctk.StringVar(value="")
        self._pm_disk_menu = ctk.CTkOptionMenu(
            controls, values=[""], variable=self._pm_disk_var,
            width=320, command=self._pm_on_disk_change,
            fg_color=COLOR_PRIMARY, button_color=COLOR_PRIMARY_HOVER,
            button_hover_color="#003366", dropdown_fg_color="#ffffff",
            dropdown_text_color=COLOR_TEXT_BODY,
        )
        self._pm_disk_menu.pack(side="left", padx=(0, 12))

        self._pm_summary_label = ctk.CTkLabel(
            inner, text="", font=ui_font(11), text_color=COLOR_TEXT_MUTED, anchor="w",
        )
        self._pm_summary_label.pack(anchor="w", pady=(10, 0))

        bar_wrap = ctk.CTkFrame(top, fg_color=COLOR_CARD, corner_radius=8)
        bar_wrap.pack(fill="x", pady=(2, 8))
        self._pm_canvas = tk.Canvas(
            bar_wrap, height=PM_BAR_HEIGHT, bg="#0f172a",
            highlightthickness=0, bd=0,
        )
        self._pm_canvas.pack(fill="x", padx=8, pady=8)
        self._pm_canvas.bind("<Button-1>", self._pm_on_bar_click)
        self._pm_canvas.bind("<Configure>", lambda _e: self._pm_draw_bar())

        sel_panel = ctk.CTkFrame(top, fg_color=COLOR_SECTION_BG, corner_radius=8)
        sel_panel.pack(fill="x", pady=(0, 8))
        sel_inner = ctk.CTkFrame(sel_panel, fg_color="transparent")
        sel_inner.pack(fill="x", padx=12, pady=10)
        self._pm_sel_label = ctk.CTkLabel(
            sel_inner, text=t("pm_none_selected", self.lang),
            font=ui_font(12, weight="bold"), text_color=COLOR_SECTION, anchor="w",
        )
        self._pm_sel_label.pack(anchor="w")

        toolbar = ctk.CTkFrame(sel_inner, fg_color="transparent")
        toolbar.pack(anchor="w", pady=(8, 0))
        self._pm_buttons = {}
        actions = [
            ("create", "pm_create", COLOR_APPLE_BLUE, COLOR_APPLE_BLUE_HOVER, self._pm_create),
            ("delete", "pm_delete", COLOR_USAGE_RED, "#b91c1c", self._pm_delete),
            ("format", "pm_format", COLOR_PRIMARY, COLOR_PRIMARY_HOVER, self._pm_format),
            ("resize", "pm_resize", COLOR_PRIMARY, COLOR_PRIMARY_HOVER, self._pm_resize),
            ("label", "pm_label", COLOR_APPLE_GRAY_BG, COLOR_APPLE_GRAY_HOVER, self._pm_label),
            ("letter", "pm_letter", COLOR_APPLE_GRAY_BG, COLOR_APPLE_GRAY_HOVER, self._pm_letter),
            ("attributes", "pm_attributes", COLOR_APPLE_GRAY_BG, COLOR_APPLE_GRAY_HOVER, self._pm_attributes),
        ]
        for key, label_key, fg, hover, cmd in actions:
            text_color = "#ffffff" if fg not in (COLOR_APPLE_GRAY_BG,) else COLOR_TEXT_BODY
            btn = ctk.CTkButton(
                toolbar, text=t(label_key, self.lang), command=cmd,
                width=104, height=32, corner_radius=10,
                fg_color=fg, hover_color=hover, text_color=text_color,
                state="disabled",
            )
            btn.pack(side="left", padx=(0, 8))
            self._pm_buttons[key] = btn

        header_row = ctk.CTkFrame(top, fg_color=COLOR_SECTION_BG, corner_radius=8)
        header_row.pack(fill="x", pady=(2, 4))
        hi = ctk.CTkFrame(header_row, fg_color="transparent")
        hi.pack(fill="x", padx=12, pady=6)
        for txt, w, anchor in (
            ("pm_col_letter", 60, "w"), ("pm_col_label", 180, "w"),
            ("pm_col_fs", 90, "w"), ("pm_col_size", 100, "e"),
            ("pm_col_used", 100, "e"), ("pm_col_flags", 140, "w"),
        ):
            ctk.CTkLabel(
                hi, text=t(txt, self.lang), font=ui_font(11, weight="bold"),
                text_color=COLOR_SECTION, width=w, anchor=anchor,
            ).pack(side="left", padx=(0, 6))

        self._pm_vlist = VirtualList(
            panel, row_height=PM_ROW_HEIGHT,
            build_row=self._pm_build_row, bind_row=self._pm_bind_row,
            bg_color=COLOR_BG, scrollbar_color=COLOR_PRIMARY,
            scrollbar_hover=COLOR_PRIMARY_HOVER,
        )
        self._pm_vlist.grid(row=1, column=0, sticky="nsew", pady=(2, 4))

        self._pm_status_label = ctk.CTkLabel(
            panel, text=t("pm_loading", self.lang),
            font=ui_font(11), text_color=COLOR_TEXT_MUTED, anchor="w",
        )
        self._pm_status_label.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        self._pm_active = True
        self._pm_load_disks()

    def _pm_load_disks(self, keep_number: int | None = None):
        self._begin_pseudo_progress(status_key="pm_loading")
        try:
            self._pm_status_label.configure(text=t("pm_loading", self.lang))
        except Exception:
            pass

        def worker():
            disks = partition_ops.list_disks_with_partitions()
            self._schedule_ui(self._pm_after_load, disks, keep_number)

        threading.Thread(target=worker, daemon=True).start()

    def _pm_after_load(self, disks: list, keep_number: int | None):
        if not self._pm_active:
            return
        self._finish_pseudo_progress()
        self._pm_disks = disks or []
        if not self._pm_disks:
            self._pm_disk_menu.configure(values=[""])
            self._pm_disk_var.set("")
            self._pm_status_label.configure(text=t("pm_no_disks", self.lang))
            self._pm_current_disk = None
            self._pm_selected = None
            self._clear_pm_bar()
            if self._pm_vlist is not None:
                self._pm_vlist.set_items([])
            self._pm_update_panel()
            return

        self._pm_disk_labels = {}
        labels = []
        for d in self._pm_disks:
            lbl = f"#{d['number']}  {d['model'] or 'Disk'}  ({self._format_bytes(d['size'])})"
            self._pm_disk_labels[lbl] = d["number"]
            labels.append(lbl)
        self._pm_disk_menu.configure(values=labels)

        target = keep_number if keep_number is not None else self._pm_disks[0]["number"]
        target_label = next(
            (l for l, n in self._pm_disk_labels.items() if n == target), labels[0]
        )
        self._pm_disk_var.set(target_label)
        self._pm_status_label.configure(text="")
        self._pm_select_disk_by_number(self._pm_disk_labels[target_label])

    def _pm_on_disk_change(self, label: str):
        number = self._pm_disk_labels.get(label)
        if number is not None:
            self._pm_select_disk_by_number(number)

    def _pm_select_disk_by_number(self, number: int):
        self._pm_current_disk = next(
            (d for d in self._pm_disks if d["number"] == number), None
        )
        self._pm_selected = None
        if self._pm_current_disk is None:
            return
        d = self._pm_current_disk
        self._pm_summary_label.configure(
            text=t("pm_disk_summary", self.lang, model=d["model"] or "Disk",
                   size=self._format_bytes(d["size"]),
                   style=d["partition_style"] or "-"),
        )
        self._pm_part_by_offset = {
            p["offset"]: p for p in d["partitions"]
        }
        self._pm_draw_bar()
        if self._pm_vlist is not None:
            self._pm_vlist.set_items(list(d["segments"]))
        self._pm_update_panel()

    def _pm_fs_color(self, seg: dict) -> str:
        if seg["kind"] == "unallocated":
            return "#cbd5e1"
        part = self._pm_part_by_offset.get(seg["offset"], {})
        fs = (part.get("filesystem") or "").upper()
        return {
            "NTFS": COLOR_PRIMARY,
            "EXFAT": "#0d9488",
            "FAT32": "#7c3aed",
            "FAT": "#7c3aed",
        }.get(fs, "#64748b")

    def _clear_pm_bar(self):
        self._pm_seg_hit = []
        try:
            self._pm_canvas.delete("all")
        except Exception:
            pass

    def _pm_draw_bar(self):
        if self._pm_current_disk is None:
            return
        canvas = self._pm_canvas
        canvas.delete("all")
        self._pm_seg_hit = []
        canvas.update_idletasks()
        cw = max(canvas.winfo_width(), 200)
        ch = PM_BAR_HEIGHT
        segments = self._pm_current_disk["segments"]
        total = self._pm_current_disk["size"] or 1
        pad = 3
        x = pad
        avail = cw - pad * 2
        sel_off = self._pm_selected["offset"] if self._pm_selected else None

        for seg in segments:
            w = max(int(avail * (seg["size"] / total)), 3)
            x1, y1, x2, y2 = x, pad, x + w, ch - pad
            fill = self._pm_fs_color(seg)
            selected = sel_off == seg["offset"]
            outline = "#ffffff" if selected else "#1e293b"
            width = 3 if selected else 1
            canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width)
            self._pm_seg_hit.append((x1, x2, seg))

            if w > 46:
                if seg["kind"] == "unallocated":
                    label = t("pm_unallocated", self.lang)
                else:
                    part = self._pm_part_by_offset.get(seg["offset"], {})
                    label = part.get("letter") or part.get("label") or part.get("filesystem") or "-"
                text_color = "#0f172a" if seg["kind"] == "unallocated" else "#ffffff"
                canvas.create_text(
                    (x1 + x2) / 2, ch / 2 - 8, text=label,
                    fill=text_color, font=("Segoe UI", 9, "bold"),
                )
                canvas.create_text(
                    (x1 + x2) / 2, ch / 2 + 10, text=self._format_bytes(seg["size"]),
                    fill=text_color, font=("Segoe UI", 8),
                )
            x += w

    def _pm_on_bar_click(self, event):
        for x1, x2, seg in self._pm_seg_hit:
            if x1 <= event.x <= x2:
                self._pm_select_segment(seg)
                return

    def _pm_select_segment(self, seg: dict):
        part = self._pm_part_by_offset.get(seg["offset"]) if seg["kind"] == "partition" else None
        self._pm_selected = {
            "kind": seg["kind"],
            "offset": seg["offset"],
            "size": seg["size"],
            "partition_number": seg.get("partition_number"),
            "partition": part,
        }
        self._pm_draw_bar()
        if self._pm_vlist is not None:
            self._pm_vlist.refresh()
        self._pm_update_panel()

    def _pm_disk_protected(self) -> bool:
        d = self._pm_current_disk
        return bool(d and (d["is_system"] or d["is_boot"]))

    def _pm_update_panel(self):
        sel = self._pm_selected
        protected = self._pm_disk_protected()
        if sel is None:
            self._pm_sel_label.configure(text=t("pm_none_selected", self.lang))
        elif sel["kind"] == "unallocated":
            self._pm_sel_label.configure(
                text=t("pm_selected_free", self.lang,
                       size=self._format_bytes(sel["size"])),
            )
        else:
            p = sel["partition"] or {}
            self._pm_sel_label.configure(
                text=t("pm_selected_part", self.lang,
                       label=p.get("label") or "-",
                       fs=p.get("filesystem") or "-",
                       size=self._format_bytes(sel["size"]),
                       letter=(p.get("letter") + ":") if p.get("letter") else "-"),
            )

        is_free = bool(sel and sel["kind"] == "unallocated")
        is_part = bool(sel and sel["kind"] == "partition")
        states = {
            "create": "normal" if (is_free and not protected) else "disabled",
            "delete": "normal" if (is_part and not protected) else "disabled",
            "format": "normal" if (is_part and not protected) else "disabled",
            "resize": "normal" if (is_part and not protected) else "disabled",
            "label": "normal" if (is_part and not protected) else "disabled",
            "letter": "normal" if (is_part and not protected) else "disabled",
            "attributes": "normal" if (is_part and not protected) else "disabled",
        }
        for key, st in states.items():
            try:
                self._pm_buttons[key].configure(state=st)
            except Exception:
                pass

    def _pm_set_buttons_state(self, state: str):
        for btn in self._pm_buttons.values():
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _pm_build_row(self, parent):
        row = ctk.CTkFrame(
            parent, fg_color=COLOR_CARD, corner_radius=8,
            border_width=1, border_color="#e2e8f0", height=PM_ROW_HEIGHT - 6,
        )
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=10, pady=4)
        cols = {}
        for key, w, anchor in (
            ("letter", 60, "w"), ("label", 180, "w"), ("fs", 90, "w"),
            ("size", 100, "e"), ("used", 100, "e"), ("flags", 140, "w"),
        ):
            lbl = ctk.CTkLabel(inner, text="", font=ui_font(12), width=w, anchor=anchor,
                               text_color=COLOR_TEXT_BODY)
            lbl.pack(side="left", padx=(0, 6))
            cols[key] = lbl
        row._cols = cols
        return row

    def _pm_bind_row(self, row, index, seg):
        if seg["kind"] == "unallocated":
            row._cols["letter"].configure(text="")
            row._cols["label"].configure(text=t("pm_unallocated", self.lang),
                                         text_color=COLOR_TEXT_MUTED)
            row._cols["fs"].configure(text="")
            row._cols["size"].configure(text=self._format_bytes(seg["size"]))
            row._cols["used"].configure(text="")
            row._cols["flags"].configure(text="")
        else:
            p = self._pm_part_by_offset.get(seg["offset"], {})
            flags = []
            if p.get("is_active"):
                flags.append(t("pm_flag_active", self.lang))
            if p.get("is_hidden"):
                flags.append(t("pm_flag_hidden", self.lang))
            row._cols["letter"].configure(
                text=(p.get("letter") + ":") if p.get("letter") else "-",
                text_color=COLOR_TEXT_BODY)
            row._cols["label"].configure(text=p.get("label") or "-", text_color=COLOR_TEXT_BODY)
            row._cols["fs"].configure(text=p.get("filesystem") or "-")
            row._cols["size"].configure(text=self._format_bytes(seg["size"]))
            row._cols["used"].configure(
                text=self._format_bytes(p.get("used", 0)) if p.get("used") else "-")
            row._cols["flags"].configure(text=", ".join(flags))

        selected = bool(self._pm_selected and self._pm_selected["offset"] == seg["offset"])
        row.configure(border_color=COLOR_PRIMARY if selected else "#e2e8f0",
                      border_width=2 if selected else 1)
        row.bind("<Button-1>", lambda _e, s=seg: self._pm_select_segment(s))
        for lbl in row._cols.values():
            lbl.bind("<Button-1>", lambda _e, s=seg: self._pm_select_segment(s))

    # ---------------- diálogos temáticos ----------------
    def _pm_form_dialog(self, title_key: str, fields: list, info_text: str = "") -> dict | None:
        dlg = ctk.CTkToplevel(self)
        dlg.title(t(title_key, self.lang))
        dlg.configure(fg_color=COLOR_BG)
        dlg.transient(self)
        dlg.resizable(False, False)
        dlg.grab_set()

        wrap = ctk.CTkFrame(dlg, fg_color=COLOR_CARD, corner_radius=12)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)
        ctk.CTkLabel(
            wrap, text=t(title_key, self.lang),
            font=ui_font(16, weight="bold"), text_color=COLOR_SECTION,
        ).pack(anchor="w", padx=18, pady=(16, 8))

        if info_text:
            ctk.CTkLabel(
                wrap, text=info_text, font=ui_font(11),
                text_color=COLOR_TEXT_MUTED, anchor="w", justify="left", wraplength=360,
            ).pack(anchor="w", padx=18, pady=(0, 8))

        vars_map: dict = {}
        for spec in fields:
            kind = spec[0]
            key = spec[1]
            row = ctk.CTkFrame(wrap, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=6)
            if kind == "check":
                var = ctk.BooleanVar(value=spec[3])
                ctk.CTkCheckBox(row, text=spec[2], variable=var, font=ui_font(12),
                                text_color=COLOR_TEXT_BODY).pack(anchor="w")
                vars_map[key] = var
            elif kind == "option":
                ctk.CTkLabel(row, text=spec[2], font=ui_font(12, weight="bold"),
                             text_color=COLOR_TEXT_BODY, anchor="w").pack(anchor="w")
                var = ctk.StringVar(value=spec[4])
                ctk.CTkOptionMenu(row, values=spec[3], variable=var, width=200,
                                  fg_color=COLOR_PRIMARY, button_color=COLOR_PRIMARY_HOVER,
                                  button_hover_color="#003366",
                                  dropdown_fg_color="#ffffff",
                                  dropdown_text_color=COLOR_TEXT_BODY).pack(anchor="w", pady=(4, 0))
                vars_map[key] = var
            else:  # entry
                ctk.CTkLabel(row, text=spec[2], font=ui_font(12, weight="bold"),
                             text_color=COLOR_TEXT_BODY, anchor="w").pack(anchor="w")
                var = ctk.StringVar(value=str(spec[3]))
                ctk.CTkEntry(row, textvariable=var, width=200).pack(anchor="w", pady=(4, 0))
                vars_map[key] = var

        result: dict = {}
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x", padx=18, pady=(12, 16))

        def on_ok():
            for k, v in vars_map.items():
                result[k] = v.get()
            result["_ok"] = True
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        ctk.CTkButton(btns, text=t("pm_cancel", self.lang), command=on_cancel,
                      width=100, height=36, fg_color="#94a3b8",
                      hover_color="#64748b").pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text=t("pm_ok", self.lang), command=on_ok,
                      width=100, height=36, fg_color=COLOR_PRIMARY,
                      hover_color=COLOR_PRIMARY_HOVER).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", on_cancel)
        self.update_idletasks()
        self.wait_window(dlg)
        return result if result.get("_ok") else None

    def _pm_error_text(self, info: str) -> str:
        if info in ("SYSTEM", "system"):
            return t("pm_protected_system", self.lang)
        known = ("pm_op_failed", "pm_invalid_letter", "pm_invalid_size",
                 "no_letter", "no_disk")
        if info in known:
            return t("pm_op_failed", self.lang) if info in ("no_letter", "no_disk") else t(info, self.lang)
        return info or t("pm_op_failed", self.lang)

    def _pm_run_op(self, func, args, confirm_text: str = ""):
        if self._pm_running:
            return
        if confirm_text and not messagebox.askyesno(
                t("pm_confirm_title", self.lang), confirm_text):
            return
        self._pm_running = True
        self._pm_set_buttons_state("disabled")
        self._begin_pseudo_progress(status_key="pm_running")

        def worker():
            try:
                ok, info = func(*args)
            except Exception as e:
                ok, info = False, str(e)
            self._schedule_ui(self._pm_after_op, ok, info)

        threading.Thread(target=worker, daemon=True).start()

    def _pm_after_op(self, ok: bool, info: str):
        self._pm_running = False
        self._finish_pseudo_progress()
        if ok:
            messagebox.showinfo(t("partition_manager_title", self.lang),
                                t("pm_op_ok", self.lang))
        else:
            messagebox.showerror(t("partition_manager_title", self.lang),
                                 self._pm_error_text(info))
        if not self._pm_active:
            return
        keep = self._pm_current_disk["number"] if self._pm_current_disk else None
        self._pm_load_disks(keep_number=keep)

    # ---------------- acciones ----------------
    def _pm_create(self):
        sel = self._pm_selected
        if not sel or sel["kind"] != "unallocated" or self._pm_current_disk is None:
            return
        max_mb = sel["size"] // (1024 * 1024)
        res = self._pm_form_dialog(
            "pm_dialog_create",
            [
                ("check", "use_max", t("pm_use_max", self.lang), True),
                ("entry", "size", t("pm_size_mb", self.lang), max_mb),
                ("option", "fs", t("pm_filesystem", self.lang),
                 list(partition_ops.FILESYSTEMS), "NTFS"),
                ("entry", "label", t("pm_label", self.lang), ""),
                ("entry", "letter", t("pm_letter_optional", self.lang), ""),
            ],
            info_text=t("pm_size_range", self.lang, min=1, max=max_mb),
        )
        if not res:
            return
        size_mb = None
        if not res["use_max"]:
            try:
                size_mb = int(str(res["size"]).strip())
            except ValueError:
                messagebox.showerror(t("partition_manager_title", self.lang),
                                     t("pm_invalid_size", self.lang))
                return
            if size_mb <= 0 or size_mb > max_mb:
                messagebox.showerror(t("partition_manager_title", self.lang),
                                     t("pm_invalid_size", self.lang))
                return
        self._pm_run_op(
            partition_ops.create_partition,
            (self._pm_current_disk["number"], size_mb, res["fs"],
             res["label"], res["letter"]),
        )

    def _pm_delete(self):
        sel = self._pm_selected
        if not sel or sel["kind"] != "partition" or self._pm_current_disk is None:
            return
        p = sel["partition"] or {}
        confirm = t("pm_confirm_delete", self.lang,
                    letter=(p.get("letter") + ":") if p.get("letter") else "-",
                    label=p.get("label") or "-",
                    size=self._format_bytes(sel["size"]))
        self._pm_run_op(
            partition_ops.delete_partition,
            (self._pm_current_disk["number"], sel["partition_number"]),
            confirm_text=confirm,
        )

    def _pm_format(self):
        sel = self._pm_selected
        if not sel or sel["kind"] != "partition" or self._pm_current_disk is None:
            return
        p = sel["partition"] or {}
        res = self._pm_form_dialog(
            "pm_dialog_format",
            [
                ("option", "fs", t("pm_filesystem", self.lang),
                 list(partition_ops.FILESYSTEMS), p.get("filesystem") or "NTFS"),
                ("entry", "label", t("pm_label", self.lang), p.get("label") or ""),
                ("check", "quick", t("pm_quick", self.lang), True),
            ],
        )
        if not res:
            return
        confirm = t("pm_confirm_format", self.lang,
                    letter=(p.get("letter") + ":") if p.get("letter") else "-",
                    size=self._format_bytes(sel["size"]), fs=res["fs"])
        self._pm_run_op(
            partition_ops.format_partition,
            (self._pm_current_disk["number"], sel["partition_number"],
             res["fs"], res["label"], bool(res["quick"])),
            confirm_text=confirm,
        )

    def _pm_resize(self):
        sel = self._pm_selected
        if not sel or sel["kind"] != "partition" or self._pm_current_disk is None:
            return
        n = self._pm_current_disk["number"]
        pn = sel["partition_number"]

        def worker():
            mn, mx = partition_ops.get_supported_size(n, pn)
            self._schedule_ui(self._pm_resize_dialog, sel, mn, mx)

        threading.Thread(target=worker, daemon=True).start()

    def _pm_resize_dialog(self, sel: dict, min_bytes: int, max_bytes: int):
        if max_bytes <= 0:
            messagebox.showerror(t("partition_manager_title", self.lang),
                                 t("pm_op_failed", self.lang))
            return
        min_mb = max(min_bytes // (1024 * 1024), 1)
        max_mb = max_bytes // (1024 * 1024)
        cur_mb = sel["size"] // (1024 * 1024)
        res = self._pm_form_dialog(
            "pm_dialog_resize",
            [("entry", "size", t("pm_new_size_mb", self.lang), cur_mb)],
            info_text=t("pm_size_range", self.lang, min=min_mb, max=max_mb),
        )
        if not res:
            return
        try:
            new_mb = int(str(res["size"]).strip())
        except ValueError:
            messagebox.showerror(t("partition_manager_title", self.lang),
                                 t("pm_invalid_size", self.lang))
            return
        if new_mb < min_mb or new_mb > max_mb:
            messagebox.showerror(t("partition_manager_title", self.lang),
                                 t("pm_invalid_size", self.lang))
            return
        p = sel["partition"] or {}
        confirm = t("pm_confirm_resize", self.lang,
                    letter=(p.get("letter") + ":") if p.get("letter") else "-",
                    size=self._format_bytes(new_mb * 1024 * 1024))
        self._pm_run_op(
            partition_ops.resize_partition,
            (self._pm_current_disk["number"], sel["partition_number"],
             new_mb * 1024 * 1024),
            confirm_text=confirm,
        )

    def _pm_label(self):
        sel = self._pm_selected
        if not sel or sel["kind"] != "partition" or self._pm_current_disk is None:
            return
        p = sel["partition"] or {}
        res = self._pm_form_dialog(
            "pm_dialog_label",
            [("entry", "label", t("pm_label", self.lang), p.get("label") or "")],
        )
        if not res:
            return
        self._pm_run_op(
            partition_ops.set_label,
            (self._pm_current_disk["number"], sel["partition_number"], res["label"]),
        )

    def _pm_letter(self):
        sel = self._pm_selected
        if not sel or sel["kind"] != "partition" or self._pm_current_disk is None:
            return
        p = sel["partition"] or {}
        res = self._pm_form_dialog(
            "pm_dialog_letter",
            [("entry", "letter", t("pm_letter", self.lang), p.get("letter") or "")],
        )
        if not res:
            return
        if not partition_ops.normalize_letter(res["letter"]):
            messagebox.showerror(t("partition_manager_title", self.lang),
                                 t("pm_invalid_letter", self.lang))
            return
        self._pm_run_op(
            partition_ops.set_drive_letter,
            (self._pm_current_disk["number"], sel["partition_number"], res["letter"]),
        )

    def _pm_attributes(self):
        sel = self._pm_selected
        if not sel or sel["kind"] != "partition" or self._pm_current_disk is None:
            return
        p = sel["partition"] or {}
        style = (self._pm_current_disk["partition_style"] or "").upper()
        fields = []
        if style == "MBR":
            fields.append(("check", "active", t("pm_flag_active", self.lang),
                           bool(p.get("is_active"))))
        else:
            fields.append(("check", "hidden", t("pm_flag_hidden", self.lang),
                           bool(p.get("is_hidden"))))
            fields.append(("check", "readonly", t("pm_flag_readonly", self.lang), False))
        res = self._pm_form_dialog("pm_dialog_attributes", fields)
        if not res:
            return
        kwargs = {}
        if "active" in res:
            kwargs["active"] = bool(res["active"])
        if "hidden" in res:
            kwargs["hidden"] = bool(res["hidden"])
        if "readonly" in res:
            kwargs["readonly"] = bool(res["readonly"])

        def call():
            return partition_ops.set_attributes(
                self._pm_current_disk["number"], sel["partition_number"], **kwargs)

        self._pm_run_op(call, ())

    def _clean_cache_click(self):
        if self._cleaning_cache or self._formatting:
            return
        self._cleaning_cache = True
        if self._cache_clean_btn is not None:
            try:
                self._cache_clean_btn.configure(state="disabled")
            except Exception:
                pass
        self._begin_pseudo_progress(status_key="clean_cache_running")

        def worker():
            try:
                result = system_cache.clean_system_cache()
            except Exception:
                result = {"deleted": 0, "skipped": 0, "bytes_freed": 0}
            self._schedule_ui(self._after_cache_clean, result)

        threading.Thread(target=worker, daemon=True).start()

    def _after_cache_clean(self, result: dict):
        self._cleaning_cache = False
        self._finish_pseudo_progress()
        if self._cache_clean_btn is not None:
            try:
                self._cache_clean_btn.configure(state="normal")
            except Exception:
                pass
        deleted = int(result.get("deleted", 0) or 0)
        if result.get("recycle_emptied"):
            self._set_status("clean_cache_done_recycle", count=deleted)
        else:
            self._set_status("clean_cache_done", count=deleted)

    def _show_set_local_time_view(self):
        if (self._formatting or self._cleaning_cache or self._space_scanning
                or self._pm_running or self._act_running or self._def_running
                or self._set_time_running):
            return
        self.scroll.grid_remove()
        self._clear_subview()
        self._set_time_active = True

        panel = ctk.CTkScrollableFrame(
            self,
            fg_color=COLOR_BG,
            scrollbar_button_color=COLOR_PRIMARY,
            scrollbar_button_hover_color=COLOR_PRIMARY_HOVER,
        )
        panel.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))
        panel.grid_columnconfigure(0, weight=1)
        self._subview = panel

        self._make_back_header(panel, "set_time_title")

        card = ctk.CTkFrame(panel, fg_color=COLOR_CARD, corner_radius=12,
                            border_width=1, border_color="#c5d4e4")
        card.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)

        ctk.CTkLabel(
            inner,
            text=t("set_time_prompt", self.lang),
            font=ui_font(size=13),
            text_color=COLOR_TEXT_BODY,
            anchor="w",
            justify="left",
            wraplength=560,
        ).pack(anchor="w", pady=(0, 12))

        self._set_time_entry = ctk.CTkEntry(
            inner, width=360, height=36, corner_radius=8,
            placeholder_text="Miami, Madrid, Tokyo...",
        )
        self._set_time_entry.pack(anchor="w", pady=(0, 12))
        self._set_time_entry.bind("<Return>", lambda _e: self._do_set_local_time())

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(anchor="w", fill="x")
        self._set_time_btn = ctk.CTkButton(
            btn_row,
            text=t("set_time_apply", self.lang),
            command=self._do_set_local_time,
            width=160,
            height=38,
            corner_radius=10,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            text_color="#ffffff",
            font=ui_font(size=13, weight="bold"),
        )
        self._set_time_btn.pack(side="left")

        self._set_time_status_label = ctk.CTkLabel(
            inner,
            text="",
            font=ui_font(size=12),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self._set_time_status_label.pack(anchor="w", pady=(14, 0), fill="x")

    def _set_time_ui_running(self, running: bool):
        self._set_time_running = running
        state = "disabled" if running else "normal"
        for w in (self._set_time_entry, self._set_time_btn):
            if w is not None:
                try:
                    w.configure(state=state)
                except Exception:
                    pass

    def _do_set_local_time(self):
        if self._set_time_running or not self._set_time_active:
            return
        entry = self._set_time_entry
        if entry is None:
            return
        location = (entry.get() or "").strip()
        if not location:
            if self._set_time_status_label is not None:
                self._set_time_status_label.configure(
                    text=t("set_time_invalid", self.lang),
                    text_color=COLOR_APPLE_RED,
                )
            return

        if self._set_time_status_label is not None:
            self._set_time_status_label.configure(
                text=t("set_time_searching", self.lang),
                text_color=COLOR_TEXT_BODY,
            )
        self._set_time_ui_running(True)
        self._begin_pseudo_progress(status_key="set_time_searching")

        def worker():
            ok, info = win_time.set_time_for_location(location)
            self._schedule_ui(self._after_set_time, ok, info)

        threading.Thread(target=worker, daemon=True).start()

    def _after_set_time(self, ok: bool, info: str):
        self._finish_pseudo_progress()
        self._set_time_ui_running(False)
        if self.disks:
            self._update_status_disk_count()
        if self._set_time_status_label is not None and self._set_time_active:
            if ok:
                self._set_time_status_label.configure(
                    text=t("set_time_ok", self.lang).format(info=info),
                    text_color="#1b7f3a",
                )
            else:
                error_keys = (
                    "set_time_invalid", "set_time_no_internet",
                    "set_time_not_found", "set_time_failed",
                )
                msg = t(info, self.lang) if info in error_keys else info
                self._set_time_status_label.configure(
                    text=msg,
                    text_color=COLOR_APPLE_RED,
                )
            return
        if ok:
            messagebox.showinfo(
                t("set_time_title", self.lang),
                t("set_time_ok", self.lang).format(info=info),
            )
        else:
            error_keys = (
                "set_time_invalid", "set_time_no_internet",
                "set_time_not_found", "set_time_failed",
            )
            msg = t(info, self.lang) if info in error_keys else info
            messagebox.showerror(t("set_time_title", self.lang), msg)

    def _show_windows_activation_view(self):
        if (self._formatting or self._cleaning_cache or self._space_scanning
                or self._pm_running or self._act_running or self._def_running
                or self._set_time_running):
            return
        self.scroll.grid_remove()
        self._clear_subview()
        self._act_active = True
        self._act_cancel = None

        panel = ctk.CTkFrame(self, fg_color=COLOR_BG)
        panel.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=0)
        panel.grid_rowconfigure(2, weight=1)
        self._subview = panel

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        self._make_back_header(top, "activation_title")

        card = ctk.CTkScrollableFrame(
            panel, fg_color=COLOR_CARD, corner_radius=12,
            border_width=1, border_color="#c5d4e4",
            scrollbar_button_color=COLOR_PRIMARY,
            scrollbar_button_hover_color=COLOR_PRIMARY_HOVER,
            height=320,
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        card.grid_columnconfigure((0, 1), weight=1)

        self._act_buttons = []
        btn_kw = dict(
            height=40, corner_radius=10,
            fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER,
            text_color="#ffffff", font=ui_font(13, weight="bold"),
        )

        def add_btn(parent, row, col, label, desc, command, colspan=1):
            cell = ctk.CTkFrame(parent, fg_color="transparent")
            cell.grid(row=row, column=col, columnspan=colspan, sticky="ew",
                      padx=12, pady=6)
            cell.grid_columnconfigure(0, weight=1)
            btn = ctk.CTkButton(cell, text=label, command=command, **btn_kw)
            btn.grid(row=0, column=0, sticky="ew")
            if desc:
                ctk.CTkLabel(cell, text=desc, font=ui_font(11),
                             text_color=COLOR_TEXT_MUTED, anchor="w").grid(
                    row=1, column=0, sticky="w", padx=2, pady=(2, 0))
            self._act_buttons.append(btn)
            return btn

        row = 0
        ctk.CTkLabel(
            card, text=t("activation_section_methods", self.lang),
            font=ui_font(14, weight="bold"), text_color=COLOR_SECTION,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=(8, 4))
        row += 1

        methods = [
            ("hwid", "[1] " + t("activation_method_hwid", self.lang),
             t("activation_desc_hwid", self.lang)),
            ("ohook", "[2] " + t("activation_method_ohook", self.lang),
             t("activation_desc_ohook", self.lang)),
            ("tsforge", "[3] " + t("activation_method_tsforge", self.lang),
             t("activation_desc_tsforge", self.lang)),
            ("kms", "[4] " + t("activation_method_kms", self.lang),
             t("activation_desc_kms", self.lang)),
        ]
        for idx, (mid, label, desc) in enumerate(methods):
            add_btn(card, row + idx // 2, idx % 2, label, desc,
                    lambda m=mid, l=label: self._act_run(m, l))
        row += 2

        ctk.CTkLabel(
            card, text=t("activation_section_tools", self.lang),
            font=ui_font(14, weight="bold"), text_color=COLOR_SECTION,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=(12, 4))
        row += 1

        tools = [
            ("5", "[5] " + t("activation_check_status", self.lang),
             "", self._act_check_status),
            ("6", "[6] " + t("activation_change_win_edition", self.lang),
             "", lambda: self._act_open_interactive("6")),
            ("7", "[7] " + t("activation_change_off_edition", self.lang),
             "", lambda: self._act_open_interactive("7")),
            ("8", "[8] " + t("activation_troubleshoot", self.lang),
             "", lambda: self._act_open_interactive("8")),
            ("E", "[E] " + t("activation_extras", self.lang),
             "", lambda: self._act_open_interactive("E")),
            ("H", "[H] " + t("activation_help", self.lang),
             "", lambda: self._act_open_interactive("H")),
        ]
        for idx, (_key, label, desc, cmd) in enumerate(tools):
            add_btn(card, row + idx // 2, idx % 2, label, desc, cmd)
        row += 3

        console_row = ctk.CTkFrame(card, fg_color="transparent")
        console_row.grid(row=row, column=0, columnspan=2, sticky="ew",
                         padx=12, pady=(8, 14))
        console_btn = ctk.CTkButton(
            console_row, text=t("activation_open_console", self.lang),
            command=self._act_open_full_console, height=36, corner_radius=18,
            fg_color="#ffffff", hover_color="#eef2f7",
            border_width=1, border_color="#c5d4e4",
            text_color=COLOR_PRIMARY, font=ui_font(12, weight="bold"),
        )
        console_btn.pack(fill="x")

        out_wrap = ctk.CTkFrame(panel, fg_color=COLOR_CARD, corner_radius=12,
                                border_width=1, border_color="#c5d4e4")
        out_wrap.grid(row=2, column=0, sticky="nsew")
        out_wrap.grid_rowconfigure(1, weight=1)
        out_wrap.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            out_wrap, text=t("activation_output_title", self.lang),
            font=ui_font(12, weight="bold"), text_color=COLOR_SECTION, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 4))

        text = tk.Text(
            out_wrap, bg="#0b1320", fg="#39ff9a", insertbackground="#39ff9a",
            font=("Consolas", 11), state="disabled", wrap="word",
            relief="flat", bd=0, padx=10, pady=8, highlightthickness=0,
        )
        text.grid(row=1, column=0, sticky="nsew", padx=(14, 0), pady=(0, 12))
        sb = ctk.CTkScrollbar(out_wrap, command=text.yview)
        sb.grid(row=1, column=1, sticky="ns", padx=(2, 10), pady=(0, 12))
        text.configure(yscrollcommand=sb.set)
        self._act_output = text

    def _act_append(self, text: str):
        if not self._act_active or self._act_output is None:
            return
        try:
            self._act_output.configure(state="normal")
            self._act_output.insert("end", text + "\n")
            self._act_output.see("end")
            self._act_output.configure(state="disabled")
        except Exception:
            pass

    def _act_clear_output(self):
        if self._act_output is None:
            return
        try:
            self._act_output.configure(state="normal")
            self._act_output.delete("1.0", "end")
            self._act_output.configure(state="disabled")
        except Exception:
            pass

    def _act_set_buttons(self, state: str):
        for btn in self._act_buttons:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _act_run(self, method_id: str, label: str):
        if self._act_running:
            return
        if not messagebox.askyesno(t("activation_title", self.lang),
                                   t("activation_confirm_run", self.lang)):
            return
        self._act_clear_output()
        self._act_append(t("activation_running", self.lang, method=label))
        self._act_running = True
        self._act_set_buttons("disabled")
        self._begin_pseudo_progress(status_key="activation_launching")
        self._act_cancel = threading.Event()
        switches = windows_activation.METHOD_SWITCHES[method_id]
        cancel = self._act_cancel

        def worker():
            ok, err = windows_activation.run_mas_action(
                switches, lambda s: self._schedule_ui(self._act_append, s), cancel)
            self._schedule_ui(self._act_finished, ok, err)

        threading.Thread(target=worker, daemon=True).start()

    def _act_check_status(self):
        if self._act_running:
            return
        self._act_clear_output()
        self._act_append(t("activation_running", self.lang,
                           method=t("activation_check_status", self.lang)))
        self._act_running = True
        self._act_set_buttons("disabled")
        self._begin_pseudo_progress(status_key="activation_launching")
        self._act_cancel = threading.Event()
        cancel = self._act_cancel

        def worker():
            ok, err = windows_activation.run_status(
                lambda s: self._schedule_ui(self._act_append, s), cancel)
            self._schedule_ui(self._act_finished, ok, err)

        threading.Thread(target=worker, daemon=True).start()

    def _act_open_interactive(self, menu_key: str):
        if self._act_running:
            return
        messagebox.showinfo(
            t("activation_title", self.lang),
            t("activation_interactive_hint", self.lang, key=menu_key),
        )
        self._act_open_full_console()

    def _act_open_full_console(self):
        ok, info = windows_activation.launch_mas()
        if ok:
            key = ("activation_launched_offline" if info == "offline"
                   else "activation_launched_online")
            messagebox.showinfo(t("activation_title", self.lang), t(key, self.lang))
        else:
            error_keys = ("activation_no_internet", "activation_failed")
            msg = t(info, self.lang) if info in error_keys else info
            messagebox.showerror(t("activation_title", self.lang), msg)

    def _act_finished(self, ok: bool, err: str):
        self._finish_pseudo_progress()
        self._act_running = False
        self._act_cancel = None
        self._act_set_buttons("normal")
        self._act_append(t("activation_done_ok", self.lang) if ok
                         else t("activation_done_fail", self.lang))
        if self.disks:
            self._update_status_disk_count()

    def _show_defender_remover_view(self):
        if (self._formatting or self._cleaning_cache or self._space_scanning
                or self._pm_running or self._act_running or self._def_running
                or self._set_time_running):
            return
        self.scroll.grid_remove()
        self._clear_subview()
        self._def_active = True
        self._def_cancel = None

        panel = ctk.CTkFrame(self, fg_color=COLOR_BG)
        panel.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=0)
        panel.grid_rowconfigure(2, weight=1)
        self._subview = panel

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        self._make_back_header(top, "defender_title")

        card = ctk.CTkScrollableFrame(
            panel, fg_color=COLOR_CARD, corner_radius=12,
            border_width=1, border_color="#c5d4e4",
            scrollbar_button_color=COLOR_PRIMARY,
            scrollbar_button_hover_color=COLOR_PRIMARY_HOVER,
            height=320,
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        card.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(
            card, text=t("defender_warning", self.lang),
            font=ui_font(11), text_color=COLOR_TEXT_MUTED, anchor="w",
            wraplength=680, justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 6))

        self._def_buttons = []
        btn_kw = dict(
            height=40, corner_radius=10,
            fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER,
            text_color="#ffffff", font=ui_font(13, weight="bold"),
        )

        def add_btn(parent, row, col, label, desc, command, colspan=1):
            cell = ctk.CTkFrame(parent, fg_color="transparent")
            cell.grid(row=row, column=col, columnspan=colspan, sticky="ew",
                      padx=12, pady=6)
            cell.grid_columnconfigure(0, weight=1)
            btn = ctk.CTkButton(cell, text=label, command=command, **btn_kw)
            btn.grid(row=0, column=0, sticky="ew")
            if desc:
                ctk.CTkLabel(cell, text=desc, font=ui_font(11),
                             text_color=COLOR_TEXT_MUTED, anchor="w").grid(
                    row=1, column=0, sticky="w", padx=2, pady=(2, 0))
            self._def_buttons.append(btn)
            return btn

        row = 1
        ctk.CTkLabel(
            card, text=t("defender_section_actions", self.lang),
            font=ui_font(14, weight="bold"), text_color=COLOR_SECTION,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=(8, 4))
        row += 1

        actions = [
            ("full", t("defender_action_full", self.lang),
             t("defender_desc_full", self.lang)),
            ("engine", t("defender_action_engine", self.lang),
             t("defender_desc_engine", self.lang)),
            ("security", t("defender_action_security", self.lang),
             t("defender_desc_security", self.lang)),
            ("files", t("defender_action_files", self.lang),
             t("defender_desc_files", self.lang)),
        ]
        for idx, (aid, label, desc) in enumerate(actions):
            add_btn(card, row + idx // 2, idx % 2, label, desc,
                    lambda a=aid, l=label: self._def_run(a, l))
        row += 2

        out_wrap = ctk.CTkFrame(panel, fg_color=COLOR_CARD, corner_radius=12,
                                border_width=1, border_color="#c5d4e4")
        out_wrap.grid(row=2, column=0, sticky="nsew")
        out_wrap.grid_rowconfigure(1, weight=1)
        out_wrap.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            out_wrap, text=t("defender_output_title", self.lang),
            font=ui_font(12, weight="bold"), text_color=COLOR_SECTION, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 4))

        text = tk.Text(
            out_wrap, bg="#0b1320", fg="#39ff9a", insertbackground="#39ff9a",
            font=("Consolas", 11), state="disabled", wrap="word",
            relief="flat", bd=0, padx=10, pady=8, highlightthickness=0,
        )
        text.grid(row=1, column=0, sticky="nsew", padx=(14, 0), pady=(0, 12))
        sb = ctk.CTkScrollbar(out_wrap, command=text.yview)
        sb.grid(row=1, column=1, sticky="ns", padx=(2, 10), pady=(0, 12))
        text.configure(yscrollcommand=sb.set)
        self._def_output = text

    def _def_append(self, text: str):
        if not self._def_active or self._def_output is None:
            return
        try:
            self._def_output.configure(state="normal")
            self._def_output.insert("end", text + "\n")
            self._def_output.see("end")
            self._def_output.configure(state="disabled")
        except Exception:
            pass

    def _def_clear_output(self):
        if self._def_output is None:
            return
        try:
            self._def_output.configure(state="normal")
            self._def_output.delete("1.0", "end")
            self._def_output.configure(state="disabled")
        except Exception:
            pass

    def _def_set_buttons(self, state: str):
        for btn in self._def_buttons:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _def_run(self, action_id: str, label: str):
        if self._def_running:
            return
        if not is_admin():
            messagebox.showerror(
                t("defender_title", self.lang),
                t("defender_not_admin", self.lang),
            )
            return
        if not messagebox.askyesno(t("defender_title", self.lang),
                                   t("defender_confirm_run", self.lang)):
            return
        self._def_clear_output()
        self._def_append(t("defender_running", self.lang, method=label))
        self._def_running = True
        self._def_set_buttons("disabled")
        self._begin_pseudo_progress(status_key="defender_launching")
        self._def_cancel = threading.Event()
        cancel = self._def_cancel

        def worker():
            ok, err = windows_defender_remover.run_action(
                action_id, lambda s: self._schedule_ui(self._def_append, s), cancel)
            self._schedule_ui(self._def_finished, ok, err)

        threading.Thread(target=worker, daemon=True).start()

    def _def_finished(self, ok: bool, err: str):
        self._finish_pseudo_progress()
        self._def_running = False
        self._def_cancel = None
        self._def_set_buttons("normal")
        if ok:
            self._def_append(t("defender_done_ok", self.lang))
            self._def_append(t("defender_reboot_hint", self.lang))
        else:
            self._def_append(t("defender_done_fail", self.lang))
            if err == "defender_tamper_enabled":
                self._def_append(t("defender_tamper_enabled", self.lang))
            elif err == "defender_bundle_missing":
                self._def_append(t("defender_bundle_missing", self.lang))
            elif err in ("defender_failed", "defender_no_powerrun"):
                self._def_append(t("defender_tamper_hint", self.lang))
            elif err == "defender_not_admin":
                self._def_append(t("defender_not_admin", self.lang))
        if self.disks:
            self._update_status_disk_count()

    def _show_win_iso_view(self):
        if (self._formatting or self._cleaning_cache or self._space_scanning
                or self._pm_running or self._act_running or self._def_running
                or self._set_time_running or self._win_iso_running):
            return
        self.scroll.grid_remove()
        self._clear_subview()
        self._win_iso_active = True
        self._win_iso_job = win_image_job.latest_job() or win_image_job.create_job()
        self._win_iso_base_path = None
        self._win_iso_wim_path = None
        default_out = os.path.join(
            get_app_dir(), f"DiskHealth_Custom_{self._win_iso_job['id']}.iso",
        )
        self._win_iso_out_path = default_out

        panel = ctk.CTkFrame(self, fg_color=COLOR_BG)
        panel.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)
        self._subview = panel

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        self._make_back_header(top, "win_iso_title")

        card = ctk.CTkScrollableFrame(
            panel, fg_color=COLOR_CARD, corner_radius=12,
            border_width=1, border_color="#c5d4e4",
            height=280,
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        card.grid_columnconfigure(1, weight=1)

        row = 0
        ctk.CTkLabel(
            card, text=t("win_iso_desc", self.lang),
            font=ui_font(11), text_color=COLOR_TEXT_MUTED, anchor="w",
            wraplength=700, justify="left",
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 4))
        row += 1
        ctk.CTkLabel(
            card, text=t("win_iso_warning", self.lang),
            font=ui_font(11, weight="bold"), text_color=COLOR_APPLE_RED, anchor="w",
            wraplength=700, justify="left",
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 8))
        row += 1

        adk = windows_imaging.detect_adk()
        adk_text = t("win_iso_adk_ok", self.lang) if adk else t("win_iso_adk_missing", self.lang)
        adk_color = COLOR_USAGE_GREEN if adk else COLOR_APPLE_RED
        ctk.CTkLabel(
            card, text=adk_text, font=ui_font(11), text_color=adk_color,
            anchor="w", wraplength=680, justify="left",
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 8))
        row += 1

        ctk.CTkLabel(
            card, text=t("win_iso_step_inventory", self.lang),
            font=ui_font(13, weight="bold"), text_color=COLOR_SECTION,
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(4, 4))
        row += 1
        ctk.CTkButton(
            card, text=t("win_iso_scan", self.lang),
            command=self._win_iso_scan,
            height=36, fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER,
            font=ui_font(12, weight="bold"),
        ).grid(row=row, column=0, padx=12, pady=4, sticky="w")
        row += 1

        self._win_iso_prog_list = ctk.CTkTextbox(
            card, height=100, font=ui_font(family="Consolas", size=10),
            fg_color="#f8fafc", text_color=COLOR_TEXT_BODY,
        )
        self._win_iso_prog_list.grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=12, pady=(4, 10),
        )
        row += 1

        ctk.CTkLabel(
            card, text=t("win_iso_step_capture", self.lang),
            font=ui_font(13, weight="bold"), text_color=COLOR_SECTION,
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(4, 4))
        row += 1

        usb_opts = self._win_iso_usb_options()
        self._win_iso_usb_var = tk.StringVar(value=usb_opts[0] if usb_opts else "")
        ctk.CTkLabel(card, text=t("win_iso_usb_disk", self.lang)).grid(
            row=row, column=0, sticky="w", padx=12, pady=4,
        )
        ctk.CTkComboBox(
            card, variable=self._win_iso_usb_var, values=usb_opts, width=320,
        ).grid(row=row, column=1, sticky="w", padx=4, pady=4)
        row += 1
        cap_row = ctk.CTkFrame(card, fg_color="transparent")
        cap_row.grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=4)
        ctk.CTkButton(
            cap_row, text=t("win_iso_create_winpe", self.lang),
            command=self._win_iso_create_winpe,
            height=34, fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            cap_row, text=t("win_iso_sysprep", self.lang),
            command=self._win_iso_sysprep,
            height=34, fg_color=COLOR_APPLE_GRAY_BG, hover_color=COLOR_APPLE_GRAY_HOVER,
            text_color=COLOR_APPLE_TEXT,
        ).pack(side="left")
        row += 1

        ctk.CTkLabel(
            card, text=t("win_iso_step_assemble", self.lang),
            font=ui_font(13, weight="bold"), text_color=COLOR_SECTION,
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 4))
        row += 1

        def file_row(lbl_key, pick_cmd, r):
            ctk.CTkLabel(card, text=t(lbl_key, self.lang)).grid(
                row=r, column=0, sticky="w", padx=12, pady=4,
            )
            ent = ctk.CTkEntry(card, width=360)
            ent.grid(row=r, column=1, sticky="ew", padx=4, pady=4)
            ctk.CTkButton(
                card, text=t("win_iso_browse", self.lang), width=90,
                command=pick_cmd,
            ).grid(row=r, column=2, padx=12, pady=4)
            return ent

        self._win_iso_base_entry = file_row("win_iso_base_iso", self._win_iso_pick_base, row)
        row += 1
        self._win_iso_wim_entry = file_row("win_iso_custom_wim", self._win_iso_pick_wim, row)
        row += 1
        self._win_iso_out_entry = file_row("win_iso_output_iso", self._win_iso_pick_out, row)
        self._win_iso_out_entry.insert(0, default_out)
        row += 1
        ctk.CTkButton(
            card, text=t("win_iso_assemble", self.lang),
            command=self._win_iso_assemble,
            height=40, fg_color=COLOR_APPLE_BLUE, hover_color=COLOR_APPLE_BLUE_HOVER,
            font=ui_font(13, weight="bold"),
        ).grid(row=row, column=0, columnspan=3, padx=12, pady=(8, 12), sticky="w")

        out_wrap = ctk.CTkFrame(panel, fg_color=COLOR_CARD, corner_radius=12,
                                border_width=1, border_color="#c5d4e4")
        out_wrap.grid(row=2, column=0, sticky="nsew")
        out_wrap.grid_rowconfigure(0, weight=1)
        out_wrap.grid_columnconfigure(0, weight=1)
        self._win_iso_output = ctk.CTkTextbox(
            out_wrap, font=ui_font(family="Consolas", size=11),
            fg_color="#0b1320", text_color="#39ff9a",
        )
        self._win_iso_output.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

    def _win_iso_usb_options(self) -> list[str]:
        opts: list[str] = []
        for d in self._visible_disks():
            win = disk_ops.resolve_windows_disk(d)
            if win is None or win.is_system or win.is_boot:
                continue
            label = d.model if d.model and not d.model.startswith("/dev") else d.description
            opts.append(f"#{win.number}  {label}")
        return opts

    def _win_iso_usb_number(self) -> int | None:
        raw = (self._win_iso_usb_var.get() if self._win_iso_usb_var else "") or ""
        if raw.startswith("#"):
            try:
                return int(raw.split()[0].lstrip("#"))
            except ValueError:
                return None
        return None

    def _win_iso_append(self, text: str):
        if not self._win_iso_active or self._win_iso_output is None:
            return
        try:
            self._win_iso_output.insert("end", text + "\n")
            self._win_iso_output.see("end")
        except Exception:
            pass

    def _win_iso_inventory_line(self, key: str):
        self._win_iso_append(t(key, self.lang))

    def _win_iso_scan(self):
        if self._win_iso_running or not self._win_iso_job:
            return
        self._win_iso_running = True
        self._begin_progress()
        self._set_status("win_iso_scanning")
        job = self._win_iso_job

        def worker():
            def on_line(msg: str):
                self._schedule_ui(self._win_iso_inventory_line, msg)

            inv = windows_inventory.run_inventory(job["id"], on_line)
            self._schedule_ui(self._win_iso_scan_done, inv)

        threading.Thread(target=worker, daemon=True).start()

    def _win_iso_scan_done(self, inv: dict):
        self._win_iso_running = False
        self._end_progress()
        if not self._win_iso_job:
            return
        self._win_iso_job["inventory"] = inv
        win_image_job.save_job(self._win_iso_job)
        win_image_job.set_stage(self._win_iso_job, "inventory")
        count = inv.get("program_count", 0)
        self._win_iso_append(t("win_iso_scan_done", self.lang, count=count))
        if self._win_iso_prog_list is not None:
            try:
                self._win_iso_prog_list.delete("1.0", "end")
                for prog in windows_inventory.merge_program_lists(
                    inv.get("programs", []), inv.get("store_apps", []),
                )[:80]:
                    src = prog.get("source", "")
                    src_lbl = t("win_iso_source_store", self.lang) if src == "store" else t(
                        "win_iso_source_msi", self.lang,
                    )
                    line = f"{prog.get('name', '')}  |  {prog.get('version', '')}  |  {src_lbl}\n"
                    self._win_iso_prog_list.insert("end", line)
                if count > 80:
                    self._win_iso_prog_list.insert("end", f"... +{count - 80}\n")
            except Exception:
                pass

    def _win_iso_pick_base(self):
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("ISO", "*.iso"), ("All", "*.*")],
        )
        if path:
            self._win_iso_base_path = path
            self._win_iso_base_entry.delete(0, "end")
            self._win_iso_base_entry.insert(0, path)

    def _win_iso_pick_wim(self):
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("WIM", "*.wim"), ("All", "*.*")],
        )
        if path:
            self._win_iso_wim_path = path
            self._win_iso_wim_entry.delete(0, "end")
            self._win_iso_wim_entry.insert(0, path)

    def _win_iso_pick_out(self):
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".iso",
            filetypes=[("ISO", "*.iso")],
        )
        if path:
            self._win_iso_out_path = path
            self._win_iso_out_entry.delete(0, "end")
            self._win_iso_out_entry.insert(0, path)

    def _win_iso_err_text(self, code: str) -> str:
        key = f"win_iso_error_{code}"
        msg = t(key, self.lang)
        if msg == key:
            return code
        return msg

    def _win_iso_assemble(self):
        if self._win_iso_running:
            return
        if not self._require_admin_for_disk_ops():
            self._win_iso_append(t("win_iso_not_admin", self.lang))
            return
        base = self._win_iso_base_entry.get().strip() if hasattr(self, "_win_iso_base_entry") else ""
        wim = self._win_iso_wim_entry.get().strip() if hasattr(self, "_win_iso_wim_entry") else ""
        out = self._win_iso_out_entry.get().strip() if hasattr(self, "_win_iso_out_entry") else ""
        if not base:
            messagebox.showwarning(t("win_iso_title", self.lang),
                                   t("win_iso_error_iso_missing", self.lang), parent=self)
            return
        if not wim:
            messagebox.showwarning(t("win_iso_title", self.lang),
                                   t("win_iso_error_wim_missing", self.lang), parent=self)
            return
        if not out:
            out = self._win_iso_out_path or ""
        self._win_iso_running = True
        self._begin_progress()
        self._set_status("win_iso_assembling")
        job = self._win_iso_job

        def progress(stage, frac=None):
            if frac is not None:
                self._schedule_ui(self._set_progress_pct, frac * 100.0, update_status=False)

        def worker():
            ok, info = windows_imaging.inject_wim_into_iso(
                base, wim, out, job=job, progress_cb=progress,
            )
            self._schedule_ui(self._win_iso_assemble_done, ok, info)

        threading.Thread(target=worker, daemon=True).start()

    def _win_iso_assemble_done(self, ok: bool, info: str):
        self._win_iso_running = False
        self._end_progress()
        if ok:
            if self._win_iso_job:
                win_image_job.set_stage(self._win_iso_job, "iso_done")
            self._win_iso_append(t("win_iso_done", self.lang, path=info))
            self._iso_path = info
            self._iso_type = disk_image.detect_iso_type_for_file(info)
        else:
            self._win_iso_append(t("win_iso_failed", self.lang,
                                   error=self._win_iso_err_text(info)))

    def _win_iso_create_winpe(self):
        if self._win_iso_running:
            return
        if not self._require_admin_for_disk_ops():
            return
        adk = windows_imaging.detect_adk()
        if not adk:
            messagebox.showwarning(
                t("win_iso_title", self.lang),
                t("win_iso_adk_missing", self.lang),
                parent=self,
            )
            return
        num = self._win_iso_usb_number()
        if num is None:
            messagebox.showwarning(
                t("win_iso_title", self.lang),
                t("pm_no_disks", self.lang),
                parent=self,
            )
            return
        self._win_iso_running = True
        self._begin_progress()
        self._set_status("win_iso_winpe_running")

        def progress(stage, frac=None):
            if frac is not None:
                self._schedule_ui(self._set_progress_pct, frac * 100.0, update_status=False)

        def worker():
            ok, info = windows_imaging.create_winpe_usb(num, adk, progress_cb=progress)
            self._schedule_ui(self._win_iso_winpe_done, ok, info)

        threading.Thread(target=worker, daemon=True).start()

    def _win_iso_winpe_done(self, ok: bool, info: str):
        self._win_iso_running = False
        self._end_progress()
        if ok:
            if self._win_iso_job:
                win_image_job.set_stage(self._win_iso_job, "winpe_ready")
            self._win_iso_append(t("win_iso_winpe_done", self.lang, letter=info))
        else:
            self._win_iso_append(t("win_iso_failed", self.lang,
                                   error=self._win_iso_err_text(info)))

    def _win_iso_sysprep(self):
        if not self._win_iso_job:
            return
        dest = win_image_job.job_dir(self._win_iso_job["id"])
        path = windows_imaging.generate_sysprep_script(dest)
        self._win_iso_append(t("win_iso_sysprep_done", self.lang))
        self._win_iso_append(path)
        try:
            os.startfile(dest)
        except Exception:
            pass

    def _on_close(self):
        if self._clock_job:
            try:
                self.after_cancel(self._clock_job)
            except Exception:
                pass
            self._clock_job = None
        self._stop_usage_poll()
        if self._disk_watcher:
            self._disk_watcher.stop()
        self.destroy()

    def _on_devices_changed(self):
        if self._scanning or self._building or self._formatting or self._cleaning_cache:
            return
        self._scan_disks(silent=True)

    def _show_transient_status(self, key: str, duration_ms: int = 4000):
        if self._toast_job:
            try:
                self.after_cancel(self._toast_job)
            except Exception:
                pass
        self.status_label.configure(text=t(key, self.lang))
        self._toast_job = self.after(duration_ms, self._apply_status)

    def _update_admin_badge(self):
        if not hasattr(self, "admin_badge"):
            return
        if is_admin():
            self.admin_badge.configure(
                text=t("admin_badge_ok", self.lang),
                fg_color="#2d8a4e",
                text_color="#ffffff",
            )
        else:
            self.admin_badge.configure(
                text=t("admin_badge_no", self.lang),
                fg_color="#c0392b",
                text_color="#ffffff",
            )

    def _on_admin_badge_click(self):
        """Clic en la insignia: elevar si aún no es administrador."""
        if is_admin():
            return
        if messagebox.askyesno(
            t("admin_elevate_title", self.lang),
            t("admin_elevate_body", self.lang),
            parent=self,
        ):
            restart_as_admin()

    def _require_admin_for_disk_ops(self) -> bool:
        if is_admin():
            return True
        if messagebox.askyesno(
            t("format_error_title", self.lang),
            f"{t('format_not_admin', self.lang)}\n\n{t('format_restart_admin', self.lang)}",
            parent=self,
        ):
            restart_as_admin()
        return False

    def _drive_type(self, disk: DiskInfo) -> tuple[str, str]:
        rot = (disk.rotation or "").lower()
        model = (disk.model or "").lower()
        if "ssd" in rot or "solid state" in rot or "ssd" in model or disk.transport == "NVMe":
            return t("drive_type_ssd", self.lang), COLOR_SSD
        if disk.rotation and "rpm" in rot:
            return t("drive_type_hdd", self.lang), COLOR_HDD
        return t("drive_type_other", self.lang), COLOR_HDD

    def _format_capacity(self, capacity: str) -> str:
        if not capacity or capacity.lower() in ("unknown", "desconocida"):
            return t("unknown_capacity", self.lang)
        return capacity

    def _on_lang_change(self, choice: str):
        if self._formatting or self._cleaning_cache:
            return
        self.lang = "es" if choice == t("lang_es", "es") else "en"
        self.settings["lang"] = self.lang
        save_settings(self.settings)
        self.lang_var.set(self._lang_display())
        self._refresh_texts()
        if self._subview is not None:
            self._show_disks_view()
        self._render_disks()

    def _refresh_texts(self):
        self.title(f"{t('app_title', self.lang)} v{__version__}")
        self.title_label.configure(text=t("app_title", self.lang))
        self.subtitle_label.configure(text=t("app_subtitle", self.lang))
        self.refresh_btn.configure(text=t("refresh", self.lang))
        self._update_admin_badge()
        self.settings_btn.configure(text=f"\u2699  {t('settings', self.lang)}")
        if self._tools_btn is not None:
            self._tools_btn.configure(text=f"{t('other_tools', self.lang)}  \u25bc")
        self.lang_menu.configure(values=[t("lang_es", "es"), t("lang_en", "en")])
        self.reports_label.configure(
            text=f"{t('reports_folder', self.lang)}: {get_reports_dir()}"
        )
        self._update_footer_toggle_label()
        self._update_ejected_ui()
        if self._status_key:
            self._apply_status()

    def _set_footer_state(self, state: str):
        self._footer_state = state
        colors = {
            "idle": COLOR_USAGE_GREEN,
            "working": COLOR_PRIMARY,
            "error": COLOR_USAGE_RED,
        }
        color = colors.get(state, COLOR_USAGE_GREEN)
        if self._status_dot is not None:
            try:
                self._status_dot.configure(text_color=color)
            except Exception:
                pass
        if self._footer_handle_dot is not None:
            try:
                self._footer_handle_dot.configure(text_color=color)
            except Exception:
                pass
        if state == "error" and not self._footer_expanded:
            self._footer_auto_expanded = True
            self._toggle_footer_body(force=True)

    def _set_status(self, key: str, **kwargs):
        self._status_key = key
        self._status_kwargs = kwargs
        self._apply_status()

    def _apply_status(self):
        if self._status_key:
            self.status_label.configure(
                text=t(self._status_key, self.lang, **self._status_kwargs)
            )
        self._update_footer_handle_summary()

    def _end_pseudo_progress_timer(self):
        if self._pseudo_progress_job is not None:
            try:
                self.after_cancel(self._pseudo_progress_job)
            except Exception:
                pass
            self._pseudo_progress_job = None

    def _begin_progress(self, pct: float = 0.0, mode: str = "determinate"):
        self._set_footer_state("working")
        if not self._footer_expanded:
            self._footer_auto_expanded = True
            self._toggle_footer_body(force=True)
        self._pseudo_progress_active = False
        self._end_pseudo_progress_timer()
        try:
            self.progress.configure(mode=mode)
            if mode == "indeterminate":
                self.progress.start()
            else:
                try:
                    self.progress.stop()
                except Exception:
                    pass
                self._set_progress_pct(pct, update_status=False)
            self._progress_frame.grid()
        except Exception:
            pass

    def _set_progress_pct(self, pct: float, status_key: str | None = None,
                          update_status: bool = True, **kwargs):
        pct = clamp_pct(pct)
        try:
            if self.progress.cget("mode") == "indeterminate":
                self.progress.configure(mode="determinate")
                try:
                    self.progress.stop()
                except Exception:
                    pass
            self.progress.set(pct / 100.0)
            self.progress_pct_label.configure(
                text=t("progress_percent", self.lang, pct=int(round(pct)))
            )
            self._progress_frame.grid()
        except Exception:
            pass
        if update_status and status_key:
            self._set_status(status_key, pct=int(round(pct)), **kwargs)

    def _begin_pseudo_progress(self, status_key: str | None = None, **kwargs):
        self._pseudo_progress_active = True
        self._pseudo_progress_pct = 0.0
        self._begin_progress(0.0)
        if status_key:
            self._set_status(status_key, **kwargs)
        self._tick_pseudo_progress()

    def _tick_pseudo_progress(self):
        if not self._pseudo_progress_active:
            return
        delta = max(0.4, (90.0 - self._pseudo_progress_pct) * 0.07)
        self._pseudo_progress_pct = min(90.0, self._pseudo_progress_pct + delta)
        self._set_progress_pct(
            self._pseudo_progress_pct,
            status_key="progress_processing",
        )
        self._pseudo_progress_job = self.after(400, self._tick_pseudo_progress)

    def _finish_pseudo_progress(self, status_key: str | None = None, **kwargs):
        self._pseudo_progress_active = False
        self._end_pseudo_progress_timer()
        self._set_progress_pct(100.0, update_status=False)
        if status_key:
            self._set_status(status_key, **kwargs)
        self.after(350, self._end_progress)

    def _end_progress(self):
        self._pseudo_progress_active = False
        self._end_pseudo_progress_timer()
        self._set_footer_state("idle")
        try:
            self.progress.stop()
            self._progress_frame.grid_remove()
        except Exception:
            pass
        if footer_should_collapse_after_progress(
            user_pinned=self._footer_user_pinned,
            auto_expanded=self._footer_auto_expanded,
        ):
            self._toggle_footer_body(force=False)
        self._footer_auto_expanded = False

    def _show_space_progress(self, pct: float):
        if self._space_progress_frame is None:
            return
        pct = clamp_pct(pct)
        try:
            self._space_progress_frame.pack(fill="x", pady=(8, 4))
            self._space_progress_bar.set(pct / 100.0)
            self._space_progress_label.configure(
                text=t("progress_percent", self.lang, pct=int(round(pct)))
            )
        except Exception:
            pass

    def _hide_space_progress(self):
        if self._space_progress_frame is None:
            return
        try:
            self._space_progress_frame.pack_forget()
            self._space_progress_bar.set(0)
            self._space_progress_label.configure(text="0%")
        except Exception:
            pass

    def _scan_disks(self, silent: bool = False):
        if self._scanning:
            return
        self._scanning = True
        self._silent_scan = silent

        if not silent:
            self.refresh_btn.configure(state="disabled")
            self._begin_progress(0.0)
            self._set_status("scanning", pct=0)
            for widget in self.scroll.winfo_children():
                widget.destroy()
            self.empty_label = ctk.CTkLabel(
                self.scroll,
                text=t("scanning", self.lang, pct=0),
                text_color=COLOR_TEXT_MUTED,
                font=ui_font(size=14),
            )
            self.empty_label.grid(row=0, column=0, pady=60)

        def worker():
            try:
                smartctl = get_smartctl_path()
                if not smartctl:
                    self._schedule_ui(self._on_scan_error, "no_smartctl")
                    return

                def disk_progress(current: int, total: int):
                    pct = (current / total) * 100.0 if total else 0.0
                    self._schedule_ui(
                        self._set_progress_pct, pct,
                        status_key="scanning",
                    )

                disks = scan_disks_with_info(smartctl, progress_cb=disk_progress)
                self._schedule_ui(self._on_scan_complete, disks)
            except Exception:
                from app_logging import log_exception
                import sys
                log_exception(*sys.exc_info(), context="scan_disks")
                self._schedule_ui(self._on_scan_error, "scan_failed")

        threading.Thread(target=worker, daemon=True).start()

    def _ensure_watcher(self, disks: list[DiskInfo]):
        if self._disk_watcher is None:
            self._disk_watcher = DiskWatcher(self, on_change=self._on_devices_changed)
        self._disk_watcher.sync(frozenset(d.path for d in disks))

    def _on_scan_error(self, error: str):
        self._scanning = False
        self._silent_scan = False
        self._end_progress()
        self.refresh_btn.configure(state="normal")
        self.disks = []
        self._prev_disk_ids = set()
        msg_key = error if error in ("no_smartctl", "scan_failed") else None
        for widget in self.scroll.winfo_children():
            widget.destroy()
        if msg_key:
            self._set_status(msg_key)
            self.empty_label = ctk.CTkLabel(
                self.scroll,
                text=t(msg_key, self.lang),
                text_color=COLOR_TEXT_MUTED,
                font=ui_font(size=14),
                wraplength=560,
            )
        else:
            self.status_label.configure(text=error)
            self.empty_label = ctk.CTkLabel(
                self.scroll,
                text=error,
                text_color=COLOR_TEXT_MUTED,
                font=ui_font(size=14),
                wraplength=560,
            )
        self.empty_label.grid(row=0, column=0, pady=60)
        self._ensure_watcher([])
        self._stop_usage_poll()

    def _on_scan_complete(self, disks: list[DiskInfo]):
        silent = self._silent_scan
        had_previous = bool(self._prev_disk_ids)
        new_ids = {disk_identity(d) for d in disks}
        added = new_ids - self._prev_disk_ids
        removed = self._prev_disk_ids - new_ids

        self._scanning = False
        self._silent_scan = False
        if not silent:
            self._set_progress_pct(100.0, update_status=False)
            self.after(350, self._end_progress)
        self.refresh_btn.configure(state="normal")
        self.disks = disks
        self._prev_disk_ids = new_ids
        self._prune_ejected_disks()
        self._ensure_watcher(disks)
        self._render_disks()
        self._update_ejected_ui()
        self._update_status_disk_count()
        self._start_usage_poll()

        if had_previous and added:
            self._flash_cards(added)

        if silent and had_previous:
            if added and not removed:
                self._show_transient_status("disk_connected")
            elif removed and not added:
                self._show_transient_status("disk_removed")
            elif added and removed:
                self._show_transient_status("disk_connected")

    def _cancel_flash_jobs(self):
        for job in getattr(self, "_flash_jobs", []):
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._flash_jobs = []

    def _flash_cards(self, ids):
        cards = [self._disk_cards.get(i) for i in ids if self._disk_cards.get(i) is not None]
        if not cards:
            return

        flash_color = COLOR_SSD
        normal_border = "#c5d4e4"
        normal_bg = COLOR_CARD
        highlight_bg = "#e6f4fd"
        cycles = 6

        def step(n: int):
            on = (n % 2 == 0)
            for card in cards:
                if not card.winfo_exists():
                    continue
                try:
                    card.configure(
                        border_color=flash_color if on else normal_border,
                        border_width=3 if on else 1,
                        fg_color=highlight_bg if on else normal_bg,
                    )
                except Exception:
                    pass
            if n + 1 < cycles:
                job = self.after(280, lambda: step(n + 1))
                self._flash_jobs.append(job)

        self._cancel_flash_jobs()
        step(0)

    def _render_disks(self):
        self._cancel_flash_jobs()
        self._disk_cards = {}
        self._disk_action_btns = {}
        self._disk_rings = {}
        self._disk_usage_labels = {}
        self._usage_last_pct = {}
        self._usage_last_bytes = {}
        for widget in self.scroll.winfo_children():
            widget.destroy()

        if not self._visible_disks():
            hint = t("all_ejected", self.lang) if self._ejected_disks else t("no_disks", self.lang)
            self.empty_label = ctk.CTkLabel(
                self.scroll,
                text=hint,
                text_color=COLOR_TEXT_MUTED,
                font=ui_font(size=14),
                wraplength=560,
            )
            self.empty_label.grid(row=0, column=0, pady=60)
            return

        grouped = group_disks_by_category(self._visible_disks())
        row = 0
        sections = (
            ("system", "category_system"),
            ("external", "category_external"),
        )
        self._category_sections = {}

        for cat_key, label_key in sections:
            cat_disks = grouped.get(cat_key, [])
            if not cat_disks:
                continue

            expanded = self._category_expanded.get(cat_key, True)
            arrow = "\u25bc" if expanded else "\u25b6"
            section = ctk.CTkButton(
                self.scroll,
                text=f"{arrow}  {t(label_key, self.lang).upper()}  ({len(cat_disks)})",
                font=ui_font(size=12, weight="bold"),
                text_color=COLOR_SECTION,
                fg_color=COLOR_SECTION_BG,
                hover_color="#dce6f2",
                anchor="w",
                height=36,
                corner_radius=8,
                command=lambda k=cat_key: self._toggle_category(k),
            )
            section.grid(row=row, column=0, sticky="ew", pady=(12 if row else 4, 4), padx=2)
            row += 1

            body = ctk.CTkFrame(self.scroll, fg_color="transparent")
            body.grid(row=row, column=0, sticky="ew", padx=2)
            body.grid_columnconfigure(0, weight=1)
            if not expanded:
                body.grid_remove()

            for disk in cat_disks:
                self._build_disk_card(disk, body)

            self._category_sections[cat_key] = {"header": section, "body": body}
            row += 1

        self._refresh_disk_actions()
        self._refresh_disk_usage()

    def _toggle_category(self, cat_key: str):
        self._category_expanded[cat_key] = not self._category_expanded.get(cat_key, True)
        section = self._category_sections.get(cat_key)
        if not section:
            self._render_disks()
            return
        expanded = self._category_expanded[cat_key]
        arrow = "\u25bc" if expanded else "\u25b6"
        body = section["body"]
        header = section["header"]
        count = len(body.winfo_children())
        label_key = "category_system" if cat_key == "system" else "category_external"
        header.configure(
            text=f"{arrow}  {t(label_key, self.lang).upper()}  ({count})",
        )
        if expanded:
            body.grid()
        else:
            body.grid_remove()

    def _build_disk_card(self, disk: DiskInfo, parent):
        type_label, accent = self._drive_type(disk)
        capacity = self._format_capacity(disk.capacity)
        brand = self._disk_brand_label(disk)
        model_text = disk.model if disk.model and not disk.model.startswith("/dev") else disk.description
        serial_text = disk.serial.strip() if disk.serial else t("not_available", self.lang)

        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR_CARD,
            corner_radius=12,
            border_width=1,
            border_color="#c5d4e4",
        )
        card.pack(fill="x", pady=6, padx=2)
        card.grid_columnconfigure(1, weight=1)
        self._disk_cards[disk_identity(disk)] = card

        stripe = ctk.CTkFrame(card, fg_color=accent, width=5, corner_radius=4)
        stripe.grid(row=0, column=0, rowspan=1, sticky="ns")
        stripe.grid_propagate(False)

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=0, column=1, sticky="nsew", padx=(14, 18), pady=16)
        body.grid_columnconfigure(0, weight=1)

        info_col = ctk.CTkFrame(body, fg_color="transparent")
        info_col.grid(row=0, column=0, sticky="nsew")
        info_col.grid_columnconfigure(0, weight=1)

        badge_row = ctk.CTkFrame(info_col, fg_color="transparent")
        badge_row.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            badge_row,
            text=f"  {type_label}  ",
            font=ui_font(size=10, weight="bold"),
            text_color="#ffffff",
            fg_color=accent,
            corner_radius=5,
        ).pack(side="left")

        if disk.transport:
            ctk.CTkLabel(
                badge_row,
                text=f"  {disk.transport}  ",
                font=ui_font(size=10),
                text_color=COLOR_TEXT_MUTED,
                fg_color="#f1f5f9",
                corner_radius=5,
            ).pack(side="left", padx=(6, 0))

        ctk.CTkLabel(
            info_col,
            text=brand.upper(),
            font=ui_font(size=18, weight="bold"),
            text_color=COLOR_TEXT_BODY,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(10, 0))

        ctk.CTkLabel(
            info_col,
            text=model_text,
            font=ui_font(size=13),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
            wraplength=420,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        ctk.CTkLabel(
            info_col,
            text=f"{t('serial', self.lang)}  {serial_text}",
            font=ui_font(family="Consolas", size=12),
            text_color=COLOR_TEXT_BODY,
            anchor="w",
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))

        ctk.CTkLabel(
            info_col,
            text=capacity,
            font=ui_font(size=22, weight="bold"),
            text_color=COLOR_PRIMARY,
            anchor="w",
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))

        gauge_col = ctk.CTkFrame(body, fg_color="transparent")
        gauge_col.grid(row=0, column=1, sticky="", padx=(8, 8))
        gauge_row = ctk.CTkFrame(gauge_col, fg_color="transparent")
        gauge_row.pack()
        gauge = tk.Canvas(
            gauge_row, width=RING_SIZE, height=RING_SIZE, highlightthickness=0, bd=0,
            bg=COLOR_CARD,
        )
        gauge.pack(side="left")
        usage_size_lbl = ctk.CTkLabel(
            gauge_row,
            text="\u2014",
            font=ui_font(size=12, weight="bold"),
            text_color=COLOR_TEXT_BODY,
            anchor="w",
            justify="left",
            wraplength=140,
        )
        usage_size_lbl.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            gauge_col, text=t("usage", self.lang),
            font=ui_font(size=10), text_color=COLOR_TEXT_MUTED,
        ).pack(pady=(2, 0))
        ident = disk_identity(disk)
        self._disk_rings[ident] = gauge
        self._disk_usage_labels[ident] = usage_size_lbl
        self._draw_ring(gauge, None)

        action_col = ctk.CTkFrame(body, fg_color="transparent")
        action_col.grid(row=0, column=2, sticky="e", padx=(12, 0))

        if not disk.smart_available:
            ctk.CTkLabel(
                action_col,
                text=t("smart_unavailable", self.lang),
                text_color="#fd7e14",
                font=ui_font(size=11, weight="bold"),
                wraplength=140,
                justify="right",
            ).pack(anchor="e", pady=(0, 8))

        BTN_W = 184
        btn_state = "normal" if disk.smart_available else "disabled"
        ctk.CTkButton(
            action_col,
            text=t("create_report", self.lang),
            command=lambda d=disk: self._create_report(d),
            width=BTN_W,
            height=38,
            corner_radius=10,
            fg_color=COLOR_APPLE_BLUE,
            hover_color=COLOR_APPLE_BLUE_HOVER,
            text_color="#ffffff",
            text_color_disabled="#ffffff",
            font=ui_font(size=13, weight="bold"),
            state=btn_state,
        ).pack(anchor="e")

        tools = ctk.CTkFrame(action_col, fg_color="transparent")
        tools.pack(anchor="e", pady=(10, 0))

        def _pill(text, command, text_color):
            return ctk.CTkButton(
                tools,
                text=text,
                command=command,
                width=BTN_W,
                height=32,
                corner_radius=10,
                fg_color=COLOR_APPLE_GRAY_BG,
                hover_color=COLOR_APPLE_GRAY_HOVER,
                text_color=text_color,
                text_color_disabled=COLOR_APPLE_DISABLED,
                border_width=0,
                font=ui_font(size=12),
            )

        open_btn = _pill(
            t("open_explorer", self.lang),
            lambda d=disk: self._open_explorer(d),
            COLOR_APPLE_TEXT,
        )
        open_btn.pack(anchor="e", pady=(0, 6))

        eject_btn = _pill(
            "\u23cf  " + t("eject", self.lang),
            lambda d=disk: self._eject_disk(d),
            COLOR_APPLE_TEXT,
        )
        eject_btn.configure(state="disabled")
        eject_btn.pack(anchor="e", pady=(0, 6))

        format_btn = _pill(
            t("format_rufus", self.lang),
            lambda d=disk: self._show_format_view(d),
            COLOR_APPLE_RED,
        )
        format_btn.configure(state="disabled")
        format_btn.pack(anchor="e")

        self._disk_action_btns[disk_identity(disk)] = {
            "open": open_btn,
            "eject": eject_btn,
            "format": format_btn,
        }

    def _refresh_disk_actions(self):
        disks = list(self.disks)
        if not disks:
            return

        def worker():
            results = {}
            for d in disks:
                try:
                    win = disk_ops.resolve_windows_disk(d)
                except Exception:
                    win = None
                ident = disk_identity(d)
                if win is None:
                    results[ident] = (False, False)
                else:
                    is_sys = win.is_system or win.is_boot
                    results[ident] = (
                        win.removable and not is_sys,
                        not is_sys,
                    )
            self._schedule_ui(self._apply_disk_actions, results)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_disk_actions(self, results: dict):
        for ident, (can_eject, can_format) in results.items():
            btns = self._disk_action_btns.get(ident)
            if not btns:
                continue
            try:
                btns["eject"].configure(state="normal" if can_eject else "disabled")
                btns["format"].configure(state="normal" if can_format else "disabled")
            except Exception:
                pass

    def _disk_brand_label(self, disk: DiskInfo) -> str:
        if disk.brand and disk.brand != "Unknown":
            return disk.brand.upper()
        return t("unknown_brand", self.lang).upper()

    def _usage_color(self, pct: float) -> str:
        if pct < 25:
            return COLOR_USAGE_GREEN
        if pct < 76:
            return COLOR_USAGE_YELLOW
        return COLOR_USAGE_RED

    def _ring_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        windir = os.environ.get("WINDIR", "C:\\Windows")
        for name in ("seguisb.ttf", "segoeui.ttf", "arialbd.ttf"):
            path = os.path.join(windir, "Fonts", name)
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
        return ImageFont.load_default()

    def _render_usage_ring_image(self, percent, downscale: bool = True) -> Image.Image:
        size = RING_SIZE * RING_SCALE
        pad = 12 * RING_SCALE
        width = 12 * RING_SCALE
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        bbox = (pad, pad, size - pad, size - pad)

        draw.arc(bbox, start=0, end=360, fill=COLOR_RING_TRACK, width=width)

        if percent is None:
            font = self._ring_font(28)
            text = "--"
            text_color = COLOR_TEXT_MUTED
        else:
            pct = max(0, min(100, int(round(percent))))
            color = self._usage_color(pct)
            if pct > 0:
                start, end = usage_ring_arc_angles(pct)
                draw.arc(bbox, start=start, end=end, fill=color, width=width)
            font = self._ring_font(34)
            text = f"{pct}%"
            text_color = COLOR_APPLE_TEXT

        try:
            bbox_text = draw.textbbox((0, 0), text, font=font)
            tw = bbox_text[2] - bbox_text[0]
            th = bbox_text[3] - bbox_text[1]
        except AttributeError:
            tw, th = draw.textsize(text, font=font)
        tx = (size - tw) / 2
        ty = (size - th) / 2 - 2
        draw.text((tx, ty), text, fill=text_color, font=font)

        if downscale:
            return img.resize((RING_SIZE, RING_SIZE), Image.Resampling.LANCZOS)
        return img

    def _draw_ring(self, canvas, percent):
        try:
            canvas.delete("all")
            img = self._render_usage_ring_image(percent)
            photo = ImageTk.PhotoImage(img)
            canvas._ring_photo = photo
            canvas.create_image(RING_SIZE / 2, RING_SIZE / 2, image=photo)
        except Exception:
            return

    def _reset_usage_poll_busy(self):
        self._usage_poll_busy = False
        self._usage_poll_busy_since = None

    def _maybe_reset_stale_usage_poll_busy(self):
        if not self._usage_poll_busy or self._usage_poll_busy_since is None:
            return
        if (time.monotonic() - self._usage_poll_busy_since) * 1000 >= USAGE_POLL_BUSY_TIMEOUT_MS:
            self._reset_usage_poll_busy()

    def _start_usage_poll(self):
        self._stop_usage_poll()
        self._schedule_usage_poll()

    def _stop_usage_poll(self):
        if self._usage_poll_job is not None:
            try:
                self.after_cancel(self._usage_poll_job)
            except Exception:
                pass
            self._usage_poll_job = None

    def _schedule_usage_poll(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._usage_poll_job = self.after(
            USAGE_POLL_INTERVAL_MS, self._on_usage_poll_tick)

    def _on_usage_poll_tick(self):
        self._usage_poll_job = None
        self._maybe_reset_stale_usage_poll_busy()
        if self.disks and self._disk_rings:
            self._refresh_disk_usage()
        self._schedule_usage_poll()

    def _refresh_disk_usage(self):
        self._maybe_reset_stale_usage_poll_busy()
        disks = list(self.disks)
        if not disks or self._usage_poll_busy:
            return
        self._usage_poll_busy = True
        self._usage_poll_busy_since = time.monotonic()

        def worker():
            results = {}
            try:
                for d in disks:
                    try:
                        usage = disk_ops.get_disk_usage(d)
                    except Exception:
                        usage = None
                    results[disk_identity(d)] = usage
            finally:
                self._schedule_ui(self._apply_disk_usage, results)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_disk_usage(self, results: dict):
        self._reset_usage_poll_busy()
        for ident, usage in results.items():
            canvas = self._disk_rings.get(ident)
            size_lbl = self._disk_usage_labels.get(ident)
            if usage is None:
                pct = None
            else:
                used, total, pct = usage
            if size_lbl is not None:
                try:
                    if not size_lbl.winfo_exists():
                        size_lbl = None
                except Exception:
                    size_lbl = None
            if size_lbl is not None:
                if usage is None:
                    if self._usage_last_bytes.get(ident) is not None:
                        self._usage_last_bytes[ident] = None
                        try:
                            size_lbl.configure(text="\u2014")
                        except Exception:
                            pass
                elif usage_size_needs_update(
                    self._usage_last_bytes.get(ident), used, total,
                ):
                    self._usage_last_bytes[ident] = (used, total)
                    try:
                        size_lbl.configure(text=format_usage_size_text(used, total))
                    except Exception:
                        pass
            if canvas is None:
                continue
            if not usage_ring_needs_redraw(self._usage_last_pct.get(ident), pct):
                continue
            self._usage_last_pct[ident] = usage_ring_rounded_pct(pct)
            try:
                if canvas.winfo_exists():
                    self._draw_ring(canvas, pct)
            except Exception:
                pass

    def _open_explorer(self, disk: DiskInfo):
        def worker():
            ok = disk_ops.open_in_explorer(disk)
            if not ok:
                self._schedule_ui(self._show_transient_status, "no_drive_letter")
        threading.Thread(target=worker, daemon=True).start()

    def _eject_disk(self, disk: DiskInfo):
        letters = ", ".join(disk_ops.get_drive_letters(disk)) or "-"
        model = disk.model if disk.model and not disk.model.startswith("/dev") else disk.description
        if not messagebox.askyesno(
            t("confirm_eject_title", self.lang),
            t("confirm_eject_body", self.lang, model=model, letters=letters),
            parent=self,
        ):
            return

        def worker():
            win = disk_ops.resolve_windows_disk(disk)
            ok = disk_ops.safe_eject(disk)
            self._schedule_ui(self._after_eject, disk, ok, win)

        threading.Thread(target=worker, daemon=True).start()

    def _after_eject(self, disk: DiskInfo, ok: bool, win):
        if ok and win is not None:
            ident = disk_identity(disk)
            self._ejected_disks[ident] = disk_ops.make_ejected_record(disk, win)
            self._ejected_panel_visible = True
            if self._ejected_panel is not None:
                self._ejected_panel.grid()
            self._update_ejected_ui()
        self._show_transient_status("eject_done" if ok else "eject_failed")
        self._render_disks()
        self._update_status_disk_count()

    def _show_format_view(self, disk: DiskInfo):
        win = disk_ops.resolve_windows_disk(disk)
        if win is None or win.is_system or win.is_boot:
            messagebox.showwarning(
                t("app_title", self.lang),
                t("system_disk_protected", self.lang),
                parent=self,
            )
            return

        self.scroll.grid_remove()
        self._clear_subview()
        self._iso_path = None
        self._iso_type = None

        panel = ctk.CTkScrollableFrame(
            self,
            fg_color=COLOR_BG,
            scrollbar_button_color=COLOR_PRIMARY,
            scrollbar_button_hover_color=COLOR_PRIMARY_HOVER,
        )
        panel.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))
        panel.grid_columnconfigure(0, weight=1)
        self._subview = panel

        threading.Thread(target=ventoy_runner.ensure_ventoy, daemon=True).start()

        back_btn = self._make_back_header(panel, "format_title")

        # Aviso de peligro (ambos modos borran el disco)
        warn = ctk.CTkFrame(panel, fg_color="#fdecea", corner_radius=10,
                            border_width=1, border_color="#f5b3ab")
        warn.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            warn,
            text="\u26a0  " + t("format_warning", self.lang),
            font=ui_font(size=12, weight="bold"),
            text_color=COLOR_APPLE_RED,
            anchor="w",
            justify="left",
            wraplength=600,
        ).pack(anchor="w", padx=16, pady=12)

        # Datos del disco
        model_text = win.model or (disk.model if not disk.model.startswith("/dev") else disk.description)
        letters = ", ".join(win.letters) or "-"
        info_card = ctk.CTkFrame(panel, fg_color=COLOR_CARD, corner_radius=12,
                                 border_width=1, border_color="#c5d4e4")
        info_card.pack(fill="x", pady=(0, 12))
        info_inner = ctk.CTkFrame(info_card, fg_color="transparent")
        info_inner.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(
            info_inner, text=model_text.upper(),
            font=ui_font(size=16, weight="bold"),
            text_color=COLOR_TEXT_BODY, anchor="w",
        ).pack(anchor="w")
        details = (
            f"{t('serial', self.lang)} {disk.serial or '-'}   ·   "
            f"{self._format_capacity(disk.capacity)}   ·   "
            f"{t('interface', self.lang)}: {win.bus_type}\n"
            f"Disco #{win.number}   ·   {letters}"
        )
        ctk.CTkLabel(
            info_inner, text=details,
            font=ui_font(size=12), text_color=COLOR_TEXT_MUTED,
            anchor="w", justify="left",
        ).pack(anchor="w", pady=(6, 0))

        # Selector de modo: Formatear / USB booteable
        mode_seg = ctk.CTkSegmentedButton(
            panel,
            values=[t("mode_format", self.lang), t("mode_bootable", self.lang)],
            command=lambda _v: self._set_format_mode(),
            selected_color=COLOR_APPLE_BLUE,
            selected_hover_color=COLOR_APPLE_BLUE_HOVER,
            font=ui_font(size=13, weight="bold"),
        )
        mode_seg.set(t("mode_format", self.lang))
        mode_seg.pack(anchor="w", pady=(0, 12))

        ventoy_note = ctk.CTkFrame(
            panel, fg_color="#fff8e6", corner_radius=10,
            border_width=1, border_color="#f0d78c",
        )
        ctk.CTkLabel(
            ventoy_note,
            text="\u2139  " + t("format_ventoy_detected", self.lang),
            font=ui_font(size=11),
            text_color="#7a5c00",
            anchor="w",
            justify="left",
            wraplength=600,
        ).pack(anchor="w", padx=16, pady=10)

        def _check_ventoy():
            try:
                if disk_ops.disk_has_ventoy(win.number):
                    self._schedule_ui(
                        lambda: ventoy_note.pack(
                            fill="x", pady=(0, 12), before=mode_seg,
                        ),
                    )
            except Exception:
                pass

        threading.Thread(target=_check_ventoy, daemon=True).start()

        # Contenedor de contenido por modo
        content = ctk.CTkFrame(panel, fg_color="transparent")
        content.pack(fill="x")
        content.grid_columnconfigure(0, weight=1)

        format_frame = ctk.CTkFrame(content, fg_color="transparent")
        boot_frame = ctk.CTkFrame(content, fg_color="transparent")
        format_frame.grid(row=0, column=0, sticky="ew")
        boot_frame.grid(row=0, column=0, sticky="ew")

        # Estado + progreso compartidos
        status_lbl = ctk.CTkLabel(
            panel, text="", font=ui_font(size=12, weight="bold"),
            text_color=COLOR_TEXT_BODY, anchor="w", justify="left", wraplength=600,
        )
        status_lbl.pack(anchor="w", pady=(12, 4))
        progress = ctk.CTkProgressBar(panel, progress_color=COLOR_APPLE_BLUE)
        progress.pack(fill="x", pady=(0, 12))
        progress.set(0)
        progress.pack_forget()

        self._fmt = {
            "back": back_btn,
            "mode": mode_seg,
            "format_frame": format_frame,
            "boot_frame": boot_frame,
            "status": status_lbl,
            "progress": progress,
        }
        self._build_format_options(format_frame, disk, win)
        self._build_boot_options(boot_frame, disk, win)
        self._set_format_mode()

    def _build_format_options(self, parent, disk, win):
        opts = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=12,
                            border_width=1, border_color="#c5d4e4")
        opts.pack(fill="x")
        opts_inner = ctk.CTkFrame(opts, fg_color="transparent")
        opts_inner.pack(fill="x", padx=20, pady=18)
        opts_inner.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            opts_inner, text=t("format_section_options", self.lang),
            font=ui_font(size=14, weight="bold"),
            text_color=COLOR_SECTION, anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        ctk.CTkLabel(
            opts_inner, text=t("format_scheme", self.lang),
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY, anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=6, padx=(0, 16))
        scheme_seg = ctk.CTkSegmentedButton(
            opts_inner, values=list(disk_ops.SCHEMES),
            selected_color=COLOR_APPLE_BLUE, selected_hover_color=COLOR_APPLE_BLUE_HOVER,
        )
        scheme_seg.set("MBR")
        scheme_seg.grid(row=1, column=1, sticky="w", pady=6)

        ctk.CTkLabel(
            opts_inner, text=t("format_filesystem", self.lang),
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY, anchor="w",
        ).grid(row=2, column=0, sticky="w", pady=6, padx=(0, 16))
        fs_menu = ctk.CTkOptionMenu(
            opts_inner, values=list(disk_ops.FILESYSTEMS),
            width=160, fg_color=COLOR_APPLE_BLUE, button_color=COLOR_APPLE_BLUE_HOVER,
            button_hover_color="#005bbb", command=lambda _v: self._fmt_update_fat32_note(),
        )
        fs_menu.set("NTFS")
        fs_menu.grid(row=2, column=1, sticky="w", pady=6)

        ctk.CTkLabel(
            opts_inner, text=t("format_label", self.lang),
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY, anchor="w",
        ).grid(row=3, column=0, sticky="w", pady=6, padx=(0, 16))
        label_entry = ctk.CTkEntry(opts_inner, width=220, placeholder_text="DISK")
        label_entry.grid(row=3, column=1, sticky="w", pady=6)

        quick_var = ctk.BooleanVar(value=True)
        quick_chk = ctk.CTkCheckBox(
            opts_inner, text=t("format_quick", self.lang), variable=quick_var,
            fg_color=COLOR_APPLE_BLUE, hover_color=COLOR_APPLE_BLUE_HOVER,
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY,
        )
        quick_chk.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

        fat32_note = ctk.CTkLabel(
            opts_inner, text=t("format_fat32_note", self.lang),
            font=ui_font(size=11), text_color="#b45309",
            anchor="w", justify="left", wraplength=560,
        )
        fat32_note.grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        fat32_note.grid_remove()

        format_now = ctk.CTkButton(
            parent, text=t("format_button", self.lang),
            command=lambda d=disk, w=win: self._do_format(d, w),
            width=200, height=40, corner_radius=10,
            fg_color=COLOR_APPLE_RED, hover_color="#b30012",
            text_color="#ffffff", text_color_disabled="#f0c4c7",
            font=ui_font(size=13, weight="bold"),
        )
        format_now.pack(anchor="w", pady=(12, 0))

        self._fmt.update({
            "scheme": scheme_seg,
            "fs": fs_menu,
            "label": label_entry,
            "quick": quick_var,
            "quick_chk": quick_chk,
            "fat32_note": fat32_note,
            "format_btn": format_now,
        })

    def _build_boot_options(self, parent, disk, win):
        card = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=12,
                            border_width=1, border_color="#c5d4e4")
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=18)

        ctk.CTkLabel(
            inner, text=t("boot_section", self.lang),
            font=ui_font(size=14, weight="bold"),
            text_color=COLOR_SECTION, anchor="w",
        ).pack(anchor="w", pady=(0, 12))

        boot_submode = ctk.CTkSegmentedButton(
            inner,
            values=[t("boot_mode_iso", self.lang), t("boot_mode_multiboot", self.lang)],
            command=lambda _v: self._set_boot_submode(),
            selected_color=COLOR_APPLE_BLUE,
            selected_hover_color=COLOR_APPLE_BLUE_HOVER,
            font=ui_font(size=12, weight="bold"),
        )
        boot_submode.set(t("boot_mode_iso", self.lang))
        boot_submode.pack(anchor="w", pady=(0, 12))

        iso_panel = ctk.CTkFrame(inner, fg_color="transparent")
        iso_panel.pack(fill="x")
        multiboot_panel = ctk.CTkFrame(inner, fg_color="transparent")

        pick_row = ctk.CTkFrame(iso_panel, fg_color="transparent")
        pick_row.pack(fill="x")
        ctk.CTkButton(
            pick_row, text=t("select_iso", self.lang),
            command=lambda: self._select_iso(),
            width=160, height=34, corner_radius=10,
            fg_color=COLOR_APPLE_BLUE, hover_color=COLOR_APPLE_BLUE_HOVER,
            text_color="#ffffff",
        ).pack(side="left")
        iso_label = ctk.CTkLabel(
            pick_row, text=t("iso_none", self.lang),
            font=ui_font(size=12), text_color=COLOR_TEXT_MUTED,
            anchor="w", justify="left", wraplength=420,
        )
        iso_label.pack(side="left", padx=(12, 0), fill="x", expand=True)

        type_label = ctk.CTkLabel(
            iso_panel, text="", font=ui_font(size=12, weight="bold"),
            text_color=COLOR_APPLE_BLUE, anchor="w",
        )
        type_label.pack(anchor="w", pady=(10, 0))

        create_btn = ctk.CTkButton(
            parent, text=t("create_bootable", self.lang),
            command=lambda d=disk, w=win: self._do_create_bootable(d, w),
            width=220, height=40, corner_radius=10,
            fg_color=COLOR_APPLE_RED, hover_color="#b30012",
            text_color="#ffffff", text_color_disabled="#f0c4c7",
            font=ui_font(size=13, weight="bold"),
            state="disabled",
        )
        create_btn.pack(anchor="w", pady=(12, 0))

        multiboot_panel.pack_forget()
        ctk.CTkLabel(
            multiboot_panel, text=t("boot_multiboot_info", self.lang),
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY,
            anchor="w", justify="left", wraplength=560,
        ).pack(anchor="w", pady=(0, 12))

        multiboot_adv_btn = ctk.CTkButton(
            multiboot_panel, text=t("boot_advanced_options", self.lang),
            command=self._toggle_multiboot_advanced,
            width=180, height=30, corner_radius=8,
            fg_color=COLOR_APPLE_GRAY_BG, hover_color=COLOR_APPLE_GRAY_HOVER,
            text_color=COLOR_APPLE_TEXT, font=ui_font(size=12),
        )
        multiboot_adv_btn.pack(anchor="w", pady=(0, 8))

        multiboot_advanced = ctk.CTkFrame(multiboot_panel, fg_color="transparent")
        multiboot_advanced.pack_forget()
        multiboot_advanced.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            multiboot_advanced, text=t("format_scheme", self.lang),
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY, anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=6, padx=(0, 16))
        multiboot_scheme = ctk.CTkSegmentedButton(
            multiboot_advanced, values=list(disk_ops.SCHEMES),
            selected_color=COLOR_APPLE_BLUE, selected_hover_color=COLOR_APPLE_BLUE_HOVER,
        )
        multiboot_scheme.set("GPT")
        multiboot_scheme.grid(row=0, column=1, sticky="w", pady=6)

        ctk.CTkLabel(
            multiboot_advanced, text=t("format_filesystem", self.lang),
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY, anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=6, padx=(0, 16))
        multiboot_fs = ctk.CTkOptionMenu(
            multiboot_advanced, values=list(ventoy_runner.VENTOY_FILESYSTEMS),
            width=160, fg_color=COLOR_APPLE_BLUE, button_color=COLOR_APPLE_BLUE_HOVER,
            button_hover_color="#005bbb",
        )
        multiboot_fs.set("exFAT")
        multiboot_fs.grid(row=1, column=1, sticky="w", pady=6)

        ctk.CTkLabel(
            multiboot_advanced, text=t("ventoy_reserve", self.lang),
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY, anchor="w",
        ).grid(row=2, column=0, sticky="w", pady=6, padx=(0, 16))
        multiboot_reserve = ctk.CTkEntry(multiboot_advanced, width=100, placeholder_text="0")
        multiboot_reserve.insert(0, "0")
        multiboot_reserve.grid(row=2, column=1, sticky="w", pady=6)

        multiboot_secure_var = ctk.BooleanVar(value=True)
        multiboot_secure_chk = ctk.CTkCheckBox(
            multiboot_advanced, text=t("ventoy_secure_boot", self.lang),
            variable=multiboot_secure_var,
            fg_color=COLOR_APPLE_BLUE, hover_color=COLOR_APPLE_BLUE_HOVER,
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY,
        )
        multiboot_secure_chk.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        multiboot_no_usb_var = ctk.BooleanVar(value=False)
        multiboot_no_usb_chk = ctk.CTkCheckBox(
            multiboot_advanced, text=t("ventoy_no_usb_check", self.lang),
            variable=multiboot_no_usb_var,
            fg_color=COLOR_APPLE_BLUE, hover_color=COLOR_APPLE_BLUE_HOVER,
            font=ui_font(size=12), text_color=COLOR_TEXT_BODY,
        )
        multiboot_no_usb_chk.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ctk.CTkLabel(
            multiboot_panel, text=t("boot_multiboot_gpl", self.lang),
            font=ui_font(size=10), text_color=COLOR_TEXT_MUTED,
            anchor="w", justify="left", wraplength=560,
        ).pack(anchor="w", pady=(8, 0))

        multiboot_btn = ctk.CTkButton(
            parent, text=t("boot_multiboot_prepare", self.lang),
            command=lambda d=disk, w=win: self._do_prepare_multiboot(d, w),
            width=220, height=40, corner_radius=10,
            fg_color=COLOR_APPLE_RED, hover_color="#b30012",
            text_color="#ffffff", text_color_disabled="#f0c4c7",
            font=ui_font(size=13, weight="bold"),
        )
        multiboot_btn.pack(anchor="w", pady=(12, 0))
        multiboot_btn.pack_forget()

        self._fmt.update({
            "boot_submode": boot_submode,
            "iso_panel": iso_panel,
            "multiboot_panel": multiboot_panel,
            "iso_label": iso_label,
            "type_label": type_label,
            "create_btn": create_btn,
            "multiboot_btn": multiboot_btn,
            "multiboot_advanced": multiboot_advanced,
            "multiboot_adv_btn": multiboot_adv_btn,
            "multiboot_advanced_visible": False,
            "multiboot_scheme": multiboot_scheme,
            "multiboot_fs": multiboot_fs,
            "multiboot_reserve": multiboot_reserve,
            "multiboot_secure": multiboot_secure_var,
            "multiboot_secure_chk": multiboot_secure_chk,
            "multiboot_no_usb": multiboot_no_usb_var,
            "multiboot_no_usb_chk": multiboot_no_usb_chk,
        })
        self._set_boot_submode()

    def _toggle_multiboot_advanced(self):
        if not self._fmt:
            return
        adv = self._fmt.get("multiboot_advanced")
        btn = self._fmt.get("multiboot_adv_btn")
        if adv is None or btn is None:
            return
        visible = bool(self._fmt.get("multiboot_advanced_visible"))
        visible = not visible
        self._fmt["multiboot_advanced_visible"] = visible
        try:
            if visible:
                adv.pack(fill="x", pady=(0, 4))
                btn.configure(text=t("boot_advanced_hide", self.lang))
            else:
                adv.pack_forget()
                btn.configure(text=t("boot_advanced_options", self.lang))
        except Exception:
            pass

    def _multiboot_opts(self) -> dict:
        """Opciones multiboot: defaults si avanzado está colapsado."""
        if self._fmt and self._fmt.get("multiboot_advanced_visible"):
            scheme = self._fmt["multiboot_scheme"].get()
            fs = self._fmt["multiboot_fs"].get()
            secure = bool(self._fmt["multiboot_secure"].get())
            no_usb = bool(self._fmt["multiboot_no_usb"].get())
            try:
                reserve_mb = int(self._fmt["multiboot_reserve"].get().strip() or "0")
            except ValueError:
                reserve_mb = 0
            reserve_mb = max(0, reserve_mb)
        else:
            scheme, fs, secure, no_usb, reserve_mb = "GPT", "exFAT", True, False, 0
        return {
            "gpt": scheme.upper() == "GPT",
            "filesystem": fs,
            "secure_boot": secure,
            "no_usb_check": no_usb,
            "reserve_mb": reserve_mb,
        }

    def _set_boot_submode(self):
        if not self._fmt:
            return
        sub = self._fmt.get("boot_submode")
        if sub is None:
            return
        mode = sub.get()
        is_multiboot = mode == t("boot_mode_multiboot", self.lang)
        iso_panel = self._fmt.get("iso_panel")
        multiboot_panel = self._fmt.get("multiboot_panel")
        create_btn = self._fmt.get("create_btn")
        multiboot_btn = self._fmt.get("multiboot_btn")
        try:
            if is_multiboot:
                if iso_panel is not None:
                    iso_panel.pack_forget()
                if multiboot_panel is not None:
                    multiboot_panel.pack(fill="x")
                if create_btn is not None:
                    create_btn.pack_forget()
                if multiboot_btn is not None:
                    multiboot_btn.pack(anchor="w", pady=(12, 0))
            else:
                if multiboot_panel is not None:
                    multiboot_panel.pack_forget()
                if iso_panel is not None:
                    iso_panel.pack(fill="x")
                if multiboot_btn is not None:
                    multiboot_btn.pack_forget()
                if create_btn is not None:
                    create_btn.pack(anchor="w", pady=(12, 0))
        except Exception:
            pass

    def _set_format_mode(self):
        if not self._fmt:
            return
        mode = self._fmt["mode"].get()
        if mode == t("mode_bootable", self.lang):
            self._fmt["format_frame"].grid_remove()
            self._fmt["boot_frame"].grid()
        else:
            self._fmt["boot_frame"].grid_remove()
            self._fmt["format_frame"].grid()
        try:
            self._fmt["status"].configure(text="")
        except Exception:
            pass

    def _select_iso(self):
        path = filedialog.askopenfilename(
            parent=self,
            title=t("select_iso", self.lang),
            filetypes=[("ISO / IMG", "*.iso *.img"), ("All files", "*.*")],
        )
        if not path:
            return
        self._iso_path = path
        self._iso_type = None
        if self._fmt.get("iso_label"):
            self._fmt["iso_label"].configure(text=os.path.basename(path))
        if self._fmt.get("type_label"):
            self._fmt["type_label"].configure(text=t("iso_detecting", self.lang))
        if self._fmt.get("create_btn"):
            self._fmt["create_btn"].configure(state="disabled")

        def worker():
            try:
                itype = disk_image.detect_iso_type_for_file(path)
            except Exception:
                itype = "linux"
            self._schedule_ui(self._on_iso_detected, itype)

        threading.Thread(target=worker, daemon=True).start()

    def _on_iso_detected(self, itype: str):
        self._iso_type = itype
        if not self._fmt:
            return
        key = "iso_detected_windows" if itype == "windows" else "iso_detected_linux"
        try:
            self._fmt["type_label"].configure(text=t(key, self.lang))
            self._fmt["create_btn"].configure(state="normal")
        except Exception:
            pass

    def _fmt_update_fat32_note(self):
        if not self._fmt:
            return
        note = self._fmt.get("fat32_note")
        fs = self._fmt.get("fs")
        if note is None or fs is None:
            return
        try:
            if fs.get() == "FAT32":
                note.grid()
            else:
                note.grid_remove()
        except Exception:
            pass

    def _do_create_bootable(self, disk: DiskInfo, win):
        if self._formatting or not self._fmt:
            return
        if not self._require_admin_for_disk_ops():
            return
        if not self._iso_path or not self._iso_type:
            messagebox.showwarning(
                t("app_title", self.lang), t("boot_no_iso", self.lang), parent=self
            )
            return
        letters = ", ".join(win.letters) or "-"
        if not messagebox.askyesno(
            t("boot_confirm_title", self.lang),
            t(
                "boot_confirm_prompt", self.lang,
                iso=os.path.basename(self._iso_path),
                model=win.model or disk.model, letters=letters,
                number=win.number,
            ),
            parent=self,
        ):
            self._fmt["status"].configure(text=t("format_cancelled", self.lang))
            return

        self._fmt_set_running(True)
        self._fmt["status"].configure(text=t("boot_preparing", self.lang))

        iso = self._iso_path
        itype = self._iso_type

        def worker():
            ok, info = disk_image.create_bootable(
                iso, win.number, itype, label="WIN_USB",
                progress_cb=lambda s, f=None: self._schedule_ui(self._boot_progress, s, f),
            )
            self._schedule_ui(self._after_bootable, ok, info)

        threading.Thread(target=worker, daemon=True).start()

    def _boot_progress(self, stage: str, fraction=None):
        if not self._fmt:
            return
        keys = {
            "boot_preparing": "boot_preparing",
            "boot_mounting": "boot_mounting",
            "boot_copying": "boot_copying",
            "boot_splitting": "boot_splitting",
            "boot_writing": "boot_writing",
            "boot_finalizing": "boot_finalizing",
            "done": "boot_finalizing",
        }
        key = keys.get(stage)
        try:
            prog = self._fmt["progress"]
            if fraction is not None:
                if prog.cget("mode") != "determinate":
                    prog.configure(mode="determinate")
                    prog.stop()
                prog.set(fraction)
                pct = int(fraction * 100)
                base = t(key, self.lang) if key else ""
                self._fmt["status"].configure(text=f"{base}  {pct}%")
                self._set_progress_pct(pct, update_status=False)
            elif key:
                self._fmt["status"].configure(text=t(key, self.lang))
        except Exception:
            pass

    def _after_bootable(self, ok: bool, info: str):
        self._fmt_set_running(False)
        if ok:
            msg = t("boot_done_msg", self.lang)
            if self._fmt:
                try:
                    self._fmt["status"].configure(text=msg)
                except Exception:
                    pass
            messagebox.showinfo(t("app_title", self.lang), msg, parent=self)
            self._show_disks_view()
            self._scan_disks(silent=True)
        else:
            error_text = self._format_error_text(info)
            if self._fmt:
                try:
                    self._fmt["status"].configure(
                        text=t("boot_failed_msg", self.lang, error=error_text)
                    )
                except Exception:
                    pass
            messagebox.showerror(
                t("boot_error_title", self.lang),
                t("boot_failed_msg", self.lang, error=error_text),
                parent=self,
            )

    def _do_prepare_multiboot(self, disk: DiskInfo, win):
        if self._formatting or not self._fmt:
            return
        if not self._require_admin_for_disk_ops():
            return
        letters = ", ".join(win.letters) or "-"
        model_text = win.model or disk.model
        if not messagebox.askyesno(
            t("boot_multiboot_confirm_title", self.lang),
            t(
                "boot_multiboot_confirm_prompt", self.lang,
                model=model_text, letters=letters, number=win.number,
            ),
            parent=self,
        ):
            self._fmt["status"].configure(text=t("format_cancelled", self.lang))
            return

        opts = self._multiboot_opts()
        self._fmt_set_running(True)
        self._fmt["status"].configure(text=t("boot_multiboot_running", self.lang))

        def on_line(line: str):
            if self._fmt and line.strip():
                short = line.strip()[-120:]
                self._schedule_ui(
                    lambda s=short: self._fmt["status"].configure(
                        text=f"{t('boot_multiboot_running', self.lang)}  {s}"
                    ),
                )

        def worker():
            ok, info, detail = ventoy_runner.prepare_multiboot_usb(
                win.number,
                on_line=on_line,
                progress_cb=lambda pct: self._schedule_ui(self._multiboot_progress, pct),
                **opts,
            )
            self._schedule_ui(self._after_multiboot, ok, info, detail)

        threading.Thread(target=worker, daemon=True).start()

    def _multiboot_progress(self, pct: float):
        if not self._fmt:
            return
        try:
            prog = self._fmt["progress"]
            if prog.cget("mode") != "determinate":
                prog.configure(mode="determinate")
                try:
                    prog.stop()
                except Exception:
                    pass
            prog.set(clamp_pct(pct) / 100.0)
            ipct = int(round(pct))
            self._fmt["status"].configure(
                text=f"{t('boot_multiboot_running', self.lang)}  {ipct}%"
            )
            self._set_progress_pct(pct, update_status=False)
        except Exception:
            pass

    def _after_multiboot(self, ok: bool, info: str, detail: str = ""):
        self._fmt_set_running(False)
        if ok:
            msg = t("boot_multiboot_done", self.lang)
            if self._fmt:
                try:
                    self._fmt["status"].configure(text=msg)
                except Exception:
                    pass
            messagebox.showinfo(t("app_title", self.lang), msg, parent=self)
            self._show_disks_view()
            self._scan_disks(silent=True)
            return
        err_key = info if info.startswith("ventoy_") or info.startswith("boot_") else "boot_multiboot_failed"
        known = {
            "boot_multiboot_failed", "ventoy_failed", "ventoy_not_bundled", "ventoy_not_admin",
            "ventoy_not_usb", "ventoy_system_disk", "ventoy_no_disk",
            "ventoy_cancelled", "ventoy_disk_locked",
        }
        detail = (detail or "").strip()
        if err_key in known:
            if detail and err_key == "ventoy_failed":
                err_text = t("ventoy_failed_detail", self.lang, detail=detail)
            elif detail and err_key not in ("ventoy_disk_locked",):
                err_text = f"{t(err_key, self.lang)}\n\n{detail}"
            else:
                err_text = t(err_key, self.lang)
        else:
            err_text = t("boot_multiboot_failed", self.lang)
            if detail:
                err_text = f"{err_text}\n\n{detail}"
        if self._fmt:
            try:
                self._fmt["status"].configure(text=err_text)
            except Exception:
                pass
        messagebox.showerror(t("boot_multiboot_error_title", self.lang), err_text, parent=self)

    def _do_format(self, disk: DiskInfo, win):
        if self._formatting or not self._fmt:
            return
        if not self._require_admin_for_disk_ops():
            return
        scheme = self._fmt["scheme"].get()
        fs = self._fmt["fs"].get()
        label = self._fmt["label"].get().strip()
        quick = bool(self._fmt["quick"].get())
        letters = ", ".join(win.letters) or "-"

        if not messagebox.askyesno(
            t("format_confirm_title", self.lang),
            t(
                "format_confirm_prompt", self.lang,
                model=win.model or disk.model, letters=letters,
                number=win.number, fs=fs, scheme=scheme,
            ),
            parent=self,
        ):
            self._fmt["status"].configure(text=t("format_cancelled", self.lang))
            return

        self._fmt_set_running(True)

        def worker():
            ok, info = disk_ops.format_disk(
                win.number, scheme, fs, label, quick,
                progress_cb=lambda s, f=None: self._schedule_ui(self._fmt_progress, s, f),
            )
            self._schedule_ui(self._after_format, ok, info)

        threading.Thread(target=worker, daemon=True).start()

    def _fmt_progress(self, stage: str, fraction=None):
        if not self._fmt:
            return
        mapping = {
            "checking": "format_preparing",
            "partitioning": "format_partitioning",
            "formatting": "format_running",
            "retry_mbr": "format_retry_mbr",
            "done": "format_running",
        }
        key = mapping.get(stage)
        try:
            prog = self._fmt["progress"]
            if fraction is not None:
                if prog.cget("mode") != "determinate":
                    prog.configure(mode="determinate")
                    try:
                        prog.stop()
                    except Exception:
                        pass
                prog.set(fraction)
                pct = int(fraction * 100)
                base = t(key, self.lang) if key else ""
                self._fmt["status"].configure(
                    text=f"{base}  {pct}%" if base else f"{pct}%"
                )
                self._set_progress_pct(pct, update_status=False)
            elif key:
                self._fmt["status"].configure(text=t(key, self.lang))
        except Exception:
            pass

    def _fmt_set_running(self, running: bool):
        self._formatting = running
        state = "disabled" if running else "normal"
        for key in ("back", "format_btn", "create_btn", "multiboot_btn", "fs", "quick_chk",
                    "scheme", "mode", "label", "boot_submode", "multiboot_scheme",
                    "multiboot_fs", "multiboot_reserve", "multiboot_secure_chk",
                    "multiboot_no_usb_chk", "multiboot_adv_btn"):
            w = self._fmt.get(key)
            if w is not None:
                try:
                    w.configure(state=state)
                except Exception:
                    pass
        self.refresh_btn.configure(state=state)
        self.settings_btn.configure(state=state)
        prog = self._fmt.get("progress")
        if prog is not None:
            if running:
                prog.pack(fill="x", pady=(0, 12))
                try:
                    prog.configure(mode="determinate")
                    prog.set(0)
                    try:
                        prog.stop()
                    except Exception:
                        pass
                except Exception:
                    pass
            else:
                try:
                    prog.stop()
                    prog.configure(mode="determinate")
                    prog.set(0)
                except Exception:
                    pass
                prog.pack_forget()
        if running:
            self._begin_pseudo_progress()
        else:
            self._end_progress()

    def _after_format(self, ok: bool, info: str):
        if ok:
            if self._fmt:
                try:
                    prog = self._fmt["progress"]
                    prog.configure(mode="determinate")
                    prog.set(1.0)
                    self._fmt["status"].configure(
                        text=f"{t('format_running', self.lang)}  100%"
                    )
                except Exception:
                    pass

            def _finish_format_success():
                self._fmt_set_running(False)
                if self._fmt:
                    try:
                        self._fmt["status"].configure(
                            text=t("format_done_msg", self.lang, letter=info)
                        )
                    except Exception:
                        pass
                messagebox.showinfo(
                    t("app_title", self.lang),
                    t("format_done_msg", self.lang, letter=info),
                    parent=self,
                )
                self._show_disks_view()
                self._scan_disks(silent=True)

            self.after(1500, _finish_format_success)
            return

        self._fmt_set_running(False)
        error_text = self._format_error_text(info)
        if self._fmt:
            try:
                self._fmt["status"].configure(
                    text=t("format_failed_msg", self.lang, error=error_text)
                )
            except Exception:
                pass
        messagebox.showerror(
            t("format_error_title", self.lang),
            t("format_failed_msg", self.lang, error=error_text),
            parent=self,
        )

    def _format_error_text(self, info: str) -> str:
        generic = t("format_generic_error", self.lang)
        known = {
            "system": t("system_disk_protected", self.lang),
            "SYSTEM": t("system_disk_protected", self.lang),
            "no_disk": generic,
            "no_letter": generic,
            "format_failed": generic,
            "iso_invalid": t("iso_invalid", self.lang),
            "iso_mount_failed": t("iso_invalid", self.lang),
            "copy_failed": generic,
            "wim_split_failed": generic,
            "prepare_failed": generic,
            "open_failed": generic,
            "write_failed": generic,
            "format_not_admin": t("format_not_admin", self.lang),
        }
        if info in known:
            return known[info]
        low = (info or "").lower()
        if "access is denied" in low or "acceso denegado" in low:
            return t("format_error_access_denied", self.lang)
        if "no volume" in low:
            return t("format_error_no_volume", self.lang)
        if "virtual disk service" in low:
            detail = info.strip()
            while detail.endswith(":"):
                detail = detail[:-1].strip()
            base = t("format_error_vds", self.lang)
            if detail.lower().startswith("virtual disk service"):
                tail = detail.split(":", 1)[-1].strip()
                if tail:
                    return f"{base}\n{tail}"
            return base
        if "partitiontype" in low:
            base = t("format_error_storage_compat", self.lang)
            if "diskpart:" in low or "storage:" in low:
                return f"{base}\n\n{info}"
            return base
        if "cannot find" in low or "no se encuentra" in low or "not found" in low:
            return t("format_error_drive_not_found", self.lang)
        return info or generic

    def _create_report(self, disk: DiskInfo):
        if self._building:
            return
        self._building = True
        self._begin_progress(0.0)
        self._set_status("creating_report")

        def worker():
            smartctl = get_smartctl_path()
            if not smartctl:
                self._schedule_ui(self._on_report_error, t("no_smartctl", self.lang))
                return
            self._schedule_ui(self._set_progress_pct, 33.0, update_status=False)
            raw = get_smart_data(smartctl, disk.path)
            if not raw or "SMART" not in raw:
                msg = t("smart_unavailable", self.lang)
                self._schedule_ui(self._on_report_error, msg)
                return
            self._schedule_ui(self._set_progress_pct, 66.0, update_status=False)
            try:
                report = parsear_smartctl(raw)
                self._schedule_ui(self._set_progress_pct, 100.0, update_status=False)
                self._schedule_ui(self._show_report_preview, report)
            except Exception as e:
                self._schedule_ui(self._on_report_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _show_report_preview(self, report: DiskReport):
        self._end_progress()
        if self.disks:
            self._update_status_disk_count()

        self._clear_subview()
        self.scroll.grid_remove()

        def on_back():
            self._building = False
            self._show_disks_view()

        frame = ReportPreviewFrame(self, report, self.lang, on_back=on_back)
        frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self._subview = frame
        self._building = False
        self._hide_app_footer()

    def _on_report_error(self, msg: str):
        self._building = False
        self._end_progress()
        self._set_footer_state("error")
        self._set_status("report_error")
        messagebox.showerror(t("report_error", self.lang), msg)


def _enable_dpi_awareness():
    """Declara la app como Per-Monitor DPI Aware (sin blur, rescala por monitor)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)  # PER_MONITOR_AWARE_V2
        )
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    _enable_dpi_awareness()
    app = DiskHealthApp()
    app.mainloop()


if __name__ == "__main__":
    main()
