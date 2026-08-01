# -*- coding: utf-8 -*-
"""Vista previa WYSIWYG del reporte PDF a pantalla completa con zoom y paneo."""

from __future__ import annotations

import os
import shutil
import tempfile
import tkinter as tk
import tkinter.messagebox as messagebox
from typing import Callable, Optional

import customtkinter as ctk

from disk_service import get_reports_dir, load_settings, resolve_report_day_dir, save_settings
from i18n import t
from report_builder import (
    build_report_pdf_path,
    build_screenshot_paths,
    exportar_pdf,
    generar_html,
)
from share_utils import copy_to_clipboard, open_file_in_explorer, whatsapp_share_summary
from smart_parser import DiskReport
from ui_theme import ui_font

COLOR_BG = "#eef2f7"
COLOR_PRIMARY = "#0056b3"
COLOR_PRIMARY_HOVER = "#004494"
COLOR_TEXT_MUTED = "#64748b"
COLOR_CANVAS = "#525659"

MIN_SCALE = 0.10
MAX_SCALE = 5.0
ZOOM_STEP = 1.25
SUPERSAMPLE = 2.0
MAX_PIXMAP_PX = 4000


class ReportPreviewFrame(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        report: DiskReport,
        lang: str,
        on_back: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent, fg_color=COLOR_BG, corner_radius=0)
        self.report = report
        self.lang = lang
        self._on_back_cb = on_back
        self._html = generar_html(report, lang)
        self._preview_pdf: str | None = None
        self._exported_pdf: str | None = None

        self._doc = None
        self._pages_meta: list[tuple[float, float]] = []
        self._photo_images: list[tk.PhotoImage] = []
        self._page_frames: list[tk.Widget] = []
        self._scale = 1.0
        self._base_scale = 1.0
        self._fit_mode: str | None = "page"
        self._resize_job: str | None = None
        self._win_id = None

        self._build_chrome()
        self._install_wheel_bindings()
        self.after(60, self._load_pdf_preview)

    # ----------------------------- UI -----------------------------
    def _build_chrome(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(self, fg_color=COLOR_PRIMARY, corner_radius=0, height=48)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)

        self._back_btn = ctk.CTkButton(
            toolbar,
            text=f"\u2190  {t('back', self.lang)}",
            command=self._cancel,
            width=110,
            height=32,
            corner_radius=16,
            fg_color="#ffffff",
            text_color=COLOR_PRIMARY,
            hover_color="#e8f0fa",
            font=ui_font(12, weight="bold"),
        )
        self._back_btn.pack(side="left", anchor="center", padx=12, pady=7)

        tb = ctk.CTkFrame(toolbar, fg_color="transparent")
        tb.pack(anchor="center", pady=7)

        btn_kw = dict(
            width=40,
            height=32,
            fg_color="#ffffff",
            text_color=COLOR_PRIMARY,
            hover_color="#e8f0fa",
            font=ui_font(16, weight="bold"),
        )
        wide_kw = dict(
            height=32,
            fg_color="#ffffff",
            text_color=COLOR_PRIMARY,
            hover_color="#e8f0fa",
            font=ui_font(12),
        )

        self._zoom_out_btn = ctk.CTkButton(tb, text="\u2212", command=self._zoom_out, **btn_kw)
        self._zoom_out_btn.pack(side="left", padx=(0, 6))

        self._zoom_label = ctk.CTkLabel(
            tb,
            text="100%",
            width=64,
            font=ui_font(13, weight="bold"),
            text_color="#ffffff",
        )
        self._zoom_label.pack(side="left", padx=2)

        self._zoom_in_btn = ctk.CTkButton(tb, text="+", command=self._zoom_in, **btn_kw)
        self._zoom_in_btn.pack(side="left", padx=(6, 16))

        self._fit_width_btn = ctk.CTkButton(
            tb, text=t("fit_width", self.lang), width=120, command=self._set_fit_width, **wide_kw
        )
        self._fit_width_btn.pack(side="left", padx=(0, 8))

        self._fit_page_btn = ctk.CTkButton(
            tb, text=t("fit_page", self.lang), width=120, command=self._set_fit_page, **wide_kw
        )
        self._fit_page_btn.pack(side="left", padx=(0, 8))

        self._screenshot_btn = ctk.CTkButton(
            tb, text=t("screenshot", self.lang), width=120, command=self._screenshot, **wide_kw
        )
        self._screenshot_btn.pack(side="left")

        container = ctk.CTkFrame(self, fg_color=COLOR_CANVAS, corner_radius=0)
        container.grid(row=1, column=0, sticky="nsew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(
            container, bg=COLOR_CANVAS, highlightthickness=0, bd=0
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")

        self._vbar = ctk.CTkScrollbar(container, orientation="vertical", command=self._canvas.yview)
        self._vbar.grid(row=0, column=1, sticky="ns")
        self._hbar = ctk.CTkScrollbar(container, orientation="horizontal", command=self._canvas.xview)
        self._hbar.grid(row=1, column=0, sticky="ew")
        self._canvas.configure(yscrollcommand=self._vbar.set, xscrollcommand=self._hbar.set)

        self._pages_host = tk.Frame(self._canvas, bg=COLOR_CANVAS)
        self._win_id = self._canvas.create_window(0, 0, window=self._pages_host, anchor="nw")
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._loading = tk.Label(
            self._pages_host,
            text=t("preview_loading", self.lang),
            fg="white",
            bg=COLOR_CANVAS,
            font=("Segoe UI", 15),
        )
        self._loading.pack(pady=40, padx=80)

        self._footer = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        self._footer.grid(row=2, column=0, sticky="ew")
        self._footer.grid_propagate(False)

        inner = ctk.CTkFrame(self._footer, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=12)

        settings = load_settings()
        self._open_after_var = ctk.BooleanVar(value=settings.get("open_after_export", True))
        ctk.CTkCheckBox(
            inner,
            text=t("open_after_export", self.lang),
            variable=self._open_after_var,
            font=ui_font(12),
            text_color=COLOR_TEXT_MUTED,
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkButton(
            inner,
            text=t("export_pdf", self.lang),
            command=self._export_pdf,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            height=48,
            font=ui_font(14, weight="bold"),
            text_color="#ffffff",
        ).pack(fill="x", pady=(0, 8))

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x")
        btn_row.columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_row,
            text=t("share_whatsapp", self.lang),
            command=self._share_whatsapp,
            fg_color="#25D366",
            hover_color="#1da851",
            height=40,
            font=ui_font(13),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            btn_row,
            text=t("preview_cancel", self.lang),
            command=self._cancel,
            fg_color="#94a3b8",
            hover_color="#64748b",
            height=40,
            font=ui_font(13),
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ctk.CTkLabel(
            inner,
            text=t("share_whatsapp_hint", self.lang),
            font=ui_font(11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        self.grid_rowconfigure(2, minsize=150)

    # --------------------------- PDF ------------------------------
    def _preview_dir(self) -> str:
        path = os.path.join(tempfile.gettempdir(), "DiskHealthReport")
        os.makedirs(path, exist_ok=True)
        return path

    def _build_preview_pdf(self) -> str:
        if self._preview_pdf and os.path.isfile(self._preview_pdf):
            return self._preview_pdf
        fd, path = tempfile.mkstemp(suffix=".pdf", dir=self._preview_dir(), prefix="preview_")
        os.close(fd)
        if not exportar_pdf(self._html, path):
            raise RuntimeError(t("pdf_error", self.lang))
        self._preview_pdf = path
        return path

    def _load_pdf_preview(self):
        try:
            import pymupdf as fitz

            pdf_path = self._build_preview_pdf()
            self._loading.destroy()

            self._doc = fitz.open(pdf_path)
            self._pages_meta = [
                (page.rect.width or 1, page.rect.height or 1) for page in self._doc
            ]
            self._base_scale = self._fit_scale("width")
            self._scale = self._fit_scale("page")
            self._fit_mode = "page"
            self._render_pages()
        except Exception as e:
            messagebox.showerror(t("report_error", self.lang), str(e), parent=self)
            self._cancel()

    # --------------------------- Zoom -----------------------------
    def _viewport(self) -> tuple[int, int]:
        self.update_idletasks()
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w < 100:
            w = self.winfo_screenwidth()
        if h < 100:
            footer_h = self._footer.winfo_height() if self._footer.winfo_exists() else 160
            h = self.winfo_screenheight() - footer_h - 60
        return w, h

    def _dpi_supersample(self) -> float:
        try:
            dpi_scale = float(self.tk.call("tk", "scaling"))
        except Exception:
            dpi_scale = 1.0
        return min(SUPERSAMPLE * max(1.0, dpi_scale), 3.5)

    def _fit_scale(self, mode: str) -> float:
        if not self._pages_meta:
            return 1.0
        pw, ph = self._pages_meta[0]
        vw, vh = self._viewport()
        width_scale = (vw - 40) / pw
        if mode == "page":
            height_scale = (vh - 36) / ph
            return max(min(width_scale, height_scale), MIN_SCALE)
        return max(width_scale, MIN_SCALE)

    def _clamp(self, scale: float) -> float:
        return max(min(scale, MAX_SCALE), MIN_SCALE)

    def _render_pages(self):
        if not self._doc:
            return
        import pymupdf as fitz
        from PIL import Image, ImageTk

        for frame in self._page_frames:
            frame.destroy()
        self._page_frames = []
        self._photo_images = []

        scale = self._scale
        for i, page in enumerate(self._doc):
            pw, ph = self._pages_meta[i]
            disp_w = max(int(pw * scale), 1)
            disp_h = max(int(ph * scale), 1)

            render_scale = scale * self._dpi_supersample()
            if pw * render_scale > MAX_PIXMAP_PX:
                render_scale = MAX_PIXMAP_PX / pw

            matrix = fitz.Matrix(render_scale, render_scale)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            if (pix.width, pix.height) != (disp_w, disp_h):
                img = img.resize((disp_w, disp_h), Image.LANCZOS)

            photo = ImageTk.PhotoImage(img)
            self._photo_images.append(photo)

            frame = tk.Frame(
                self._pages_host,
                bg="white",
                highlightbackground="#2f3133",
                highlightthickness=1,
                bd=0,
            )
            frame.pack(pady=12)
            lbl = tk.Label(frame, image=photo, bg="white", bd=0)
            lbl.pack(padx=2, pady=2)
            self._page_frames.append(frame)
            self._tag_wheel_widgets(frame)

        self._update_zoom_label()
        self.after_idle(self._update_scrollregion)

    def _update_scrollregion(self):
        if not self._canvas.winfo_exists():
            return
        self._pages_host.update_idletasks()
        bbox = self._canvas.bbox("all")
        if bbox:
            self._canvas.configure(scrollregion=bbox)
        self._recenter()

    def _recenter(self):
        if self._win_id is None:
            return
        cw = self._canvas.winfo_width()
        hw = self._pages_host.winfo_reqwidth()
        x = max((cw - hw) // 2, 0)
        self._canvas.coords(self._win_id, x, 0)

    def _update_zoom_label(self):
        base = self._base_scale or 1.0
        pct = round(self._scale / base * 100)
        self._zoom_label.configure(text=f"{pct}%")

    def _zoom_in(self):
        self._fit_mode = None
        self._scale = self._clamp(self._scale * ZOOM_STEP)
        self._render_pages()

    def _zoom_out(self):
        self._fit_mode = None
        self._scale = self._clamp(self._scale / ZOOM_STEP)
        self._render_pages()

    def _set_fit_width(self):
        self._fit_mode = "width"
        self._base_scale = self._fit_scale("width")
        self._scale = self._base_scale
        self._render_pages()

    def _set_fit_page(self):
        self._fit_mode = "page"
        self._scale = self._fit_scale("page")
        self._render_pages()

    # --------------------------- Scroll / wheel -------------------
    _WHEEL_TAG = "ReportPreviewWheel"
    _WHEEL_SEQS = ("<MouseWheel>", "<Shift-MouseWheel>", "<Control-MouseWheel>")

    def _install_wheel_bindings(self) -> None:
        self._wheel_handlers = {
            "<MouseWheel>": self._on_wheel,
            "<Shift-MouseWheel>": self._on_shift_wheel,
            "<Control-MouseWheel>": self._on_ctrl_wheel,
        }
        for seq, handler in self._wheel_handlers.items():
            self._canvas.bind_class(self._WHEEL_TAG, seq, handler)
        self._tag_wheel_widgets(self._canvas)
        self._tag_wheel_widgets(self._pages_host)

    def _tag_wheel_widgets(self, widget) -> None:
        try:
            tags = tuple(widget.bindtags())
            if self._WHEEL_TAG not in tags:
                widget.bindtags((self._WHEEL_TAG,) + tags)
            for child in widget.winfo_children():
                self._tag_wheel_widgets(child)
        except Exception:
            pass

    def _unbind_wheel(self) -> None:
        try:
            for seq in self._WHEEL_SEQS:
                self._canvas.bind_class(self._WHEEL_TAG, seq, "")
        except Exception:
            pass

    def _on_wheel(self, event):
        if self._canvas.winfo_exists():
            self._canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _on_shift_wheel(self, event):
        if self._canvas.winfo_exists():
            self._canvas.xview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _on_ctrl_wheel(self, event):
        if getattr(event, "delta", 0) >= 0:
            self._zoom_in()
        else:
            self._zoom_out()
        return "break"

    def _on_canvas_configure(self, _event=None):
        self._update_scrollregion()
        if not self._doc or not self._fit_mode:
            return
        if self._resize_job:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(150, self._apply_fit)

    def _apply_fit(self):
        self._resize_job = None
        if not self._doc or not self._fit_mode:
            return
        new_scale = self._fit_scale(self._fit_mode)
        if self._fit_mode == "width":
            self._base_scale = new_scale
        if abs(new_scale - self._scale) < 0.01:
            return
        self._scale = new_scale
        self._render_pages()

    # --------------------------- Export ---------------------------
    def _screenshot(self):
        """Guarda un PNG por página del PDF en la carpeta del día."""
        try:
            import pymupdf as fitz
            from PIL import Image

            pdf_path = self._build_preview_pdf()
            doc = fitz.open(pdf_path)
            zoom = 2.0
            matrix = fitz.Matrix(zoom, zoom)
            images = []
            for page in doc:
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            doc.close()
            if not images:
                raise RuntimeError("empty pdf")

            output_dir = resolve_report_day_dir(get_reports_dir())
            paths = build_screenshot_paths(
                self.report, output_dir, len(images), self.lang
            )
            for im, path in zip(images, paths):
                im.save(path, format="PNG")

            if len(paths) == 1:
                body = t("screenshot_ok_body", self.lang, path=paths[0])
            else:
                listed = "\n".join(paths)
                body = t(
                    "screenshot_ok_body_multi",
                    self.lang,
                    count=len(paths),
                    paths=listed,
                )
            messagebox.showinfo(t("screenshot_ok", self.lang), body, parent=self)
        except Exception as e:
            messagebox.showerror(
                t("report_error", self.lang),
                f"{t('screenshot_error', self.lang)}\n\n{e}",
                parent=self,
            )

    def _export_final_pdf(self) -> str:
        if self._exported_pdf and os.path.isfile(self._exported_pdf):
            return self._exported_pdf
        output_dir = resolve_report_day_dir(get_reports_dir())
        pdf_path = build_report_pdf_path(self.report, output_dir, self.lang)
        shutil.copy2(self._build_preview_pdf(), pdf_path)
        self._exported_pdf = pdf_path
        return pdf_path

    def _export_pdf(self):
        try:
            pdf_path = self._export_final_pdf()
            settings = load_settings()
            settings["open_after_export"] = self._open_after_var.get()
            save_settings(settings)
            if self._open_after_var.get():
                try:
                    os.startfile(pdf_path)
                except OSError:
                    pass
            messagebox.showinfo(
                t("report_success", self.lang),
                f"{t('report_success', self.lang)}\n\n{pdf_path}",
                parent=self,
            )
        except Exception as e:
            messagebox.showerror(t("report_error", self.lang), str(e), parent=self)

    def _share_whatsapp(self):
        try:
            pdf_path = self._export_final_pdf()
            summary = whatsapp_share_summary(self.report, pdf_path, self.lang)
            copy_to_clipboard(self, summary)
            open_file_in_explorer(pdf_path)
            messagebox.showinfo(
                t("share_whatsapp", self.lang),
                t("share_whatsapp_done", self.lang),
                parent=self,
            )
        except Exception as e:
            messagebox.showerror(t("report_error", self.lang), str(e), parent=self)

    # --------------------------- Cleanup --------------------------
    def _cleanup_temp(self):
        if self._doc:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None
        if self._preview_pdf and os.path.isfile(self._preview_pdf):
            try:
                os.remove(self._preview_pdf)
            except OSError:
                pass

    def _cancel(self):
        self._unbind_wheel()
        self._cleanup_temp()
        if self._on_back_cb:
            self._on_back_cb()
