# -*- coding: utf-8 -*-
"""Compartir reportes (WhatsApp vía Explorador + portapapeles)."""

import os
import subprocess

from disk_service import _hidden_subprocess_kwargs
from i18n import t
from smart_parser import DiskReport


def whatsapp_share_summary(report: DiskReport, pdf_path: str, lang: str = "es") -> str:
    status = t("result_passed", lang) if report.smart_passed else t("result_failed", lang)
    return (
        f"Disk Health Report — {report.modelo}\n"
        f"{t('serial', lang)}: {report.serial} | {t('capacity', lang)}: {report.capacidad}\n"
        f"SMART: {status}\n"
        f"{pdf_path}"
    )


def open_file_in_explorer(pdf_path: str) -> None:
    path = os.path.normpath(os.path.abspath(pdf_path))
    subprocess.run(
        ["explorer.exe", f"/select,{path}"],
        **_hidden_subprocess_kwargs(),
        check=False,
    )


def copy_to_clipboard(widget, text: str) -> None:
    widget.clipboard_clear()
    widget.clipboard_append(text)
    widget.update()
