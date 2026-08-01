# -*- coding: utf-8 -*-
"""Tipografía y escala de fuentes de la UI."""

import customtkinter as ctk

FONT_BUMP = 2


def ui_font(size: int, **kwargs) -> ctk.CTkFont:
    return ctk.CTkFont(size=size + FONT_BUMP, **kwargs)
