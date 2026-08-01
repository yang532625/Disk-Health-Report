# -*- coding: utf-8 -*-
"""Lista virtualizada (virtual scrolling) para Tkinter/CustomTkinter.

Renderiza solo las filas visibles reutilizando un pool fijo de widgets, de modo
que el numero de widgets en pantalla es constante (~ filas visibles + buffer)
sin importar cuantos elementos contenga la lista.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable

import customtkinter as ctk


class VirtualList(ctk.CTkFrame):
    """Canvas + scrollbar con pooling de filas de altura fija.

    build_row(parent) -> widget: crea una fila vacia reutilizable.
    bind_row(widget, index, item): rellena una fila con los datos del item.
    """

    def __init__(
        self,
        parent,
        row_height: int,
        build_row: Callable,
        bind_row: Callable,
        buffer_rows: int = 4,
        bg_color: str = "#eef2f7",
        scrollbar_color: str = "#0056b3",
        scrollbar_hover: str = "#004494",
        **kwargs,
    ):
        super().__init__(parent, fg_color=bg_color, **kwargs)
        self._row_height = max(int(row_height), 1)
        self._build_row = build_row
        self._bind_row = bind_row
        self._buffer = max(int(buffer_rows), 0)
        self._items: list = []
        self._pool: list[tuple[tk.Widget, int]] = []

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(
            self, bg=bg_color, highlightthickness=0, bd=0, yscrollincrement=1,
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")

        self._sb = ctk.CTkScrollbar(
            self,
            orientation="vertical",
            command=self._canvas.yview,
            button_color=scrollbar_color,
            button_hover_color=scrollbar_hover,
        )
        self._sb.grid(row=0, column=1, sticky="ns")
        self._canvas.configure(yscrollcommand=self._on_yscroll)

        self._canvas.bind("<Configure>", self._on_configure)
        self._canvas.bind("<Enter>", lambda _e: self._wheel_bind(True))
        self._canvas.bind("<Leave>", lambda _e: self._wheel_bind(False))

    # ------------------------------------------------------------------ API
    def set_items(self, items: list) -> None:
        self._items = list(items)
        total_h = max(len(self._items) * self._row_height, 1)
        self._canvas.configure(scrollregion=(0, 0, 0, total_h))
        self._canvas.yview_moveto(0.0)
        self._render()

    def refresh(self) -> None:
        self._render()

    # -------------------------------------------------------------- internos
    def _wheel_bind(self, active: bool) -> None:
        try:
            if active:
                self._canvas.bind_all("<MouseWheel>", self._on_wheel)
            else:
                self._canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _on_wheel(self, event) -> None:
        if not self._items:
            return
        lines = -1 if event.delta > 0 else 1
        self._canvas.yview_scroll(lines * self._row_height, "units")

    def _on_yscroll(self, lo, hi) -> None:
        self._sb.set(lo, hi)
        self._render()

    def _on_configure(self, event) -> None:
        for _widget, win_id in self._pool:
            self._canvas.itemconfigure(win_id, width=event.width)
        self._render()

    def _ensure_pool(self, needed: int) -> None:
        width = max(self._canvas.winfo_width(), 1)
        while len(self._pool) < needed:
            widget = self._build_row(self._canvas)
            win_id = self._canvas.create_window(
                0, 0, window=widget, anchor="nw", width=width,
            )
            self._pool.append((widget, win_id))

    def _render(self) -> None:
        if not self._items:
            for _widget, win_id in self._pool:
                self._canvas.itemconfigure(win_id, state="hidden")
            return

        top = self._canvas.canvasy(0)
        view_h = max(self._canvas.winfo_height(), 1)
        first = max(int(top // self._row_height) - self._buffer, 0)
        visible = math.ceil(view_h / self._row_height) + self._buffer * 2
        last = min(first + visible, len(self._items))

        self._ensure_pool(last - first)
        width = max(self._canvas.winfo_width(), 1)

        for pool_idx, (widget, win_id) in enumerate(self._pool):
            data_idx = first + pool_idx
            if data_idx < last:
                self._canvas.coords(win_id, 0, data_idx * self._row_height)
                self._canvas.itemconfigure(win_id, state="normal", width=width)
                try:
                    self._bind_row(widget, data_idx, self._items[data_idx])
                except Exception:
                    pass
            else:
                self._canvas.itemconfigure(win_id, state="hidden")
