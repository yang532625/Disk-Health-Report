# -*- coding: utf-8 -*-
"""Localización de valores del reporte PDF según idioma de la aplicación."""

from __future__ import annotations

import re

from i18n import t

_UNKNOWN_MARKERS = frozenset(
    {
        "desconocido",
        "desconocida",
        "no especificado",
        "no especificada",
        "unknown",
        "not specified",
        "not available",
        "no disponible",
    }
)


def _is_unknown(text: str) -> bool:
    return not (text or "").strip() or text.strip().lower() in _UNKNOWN_MARKERS


def localize_generic(text: str, lang: str) -> str:
    if _is_unknown(text):
        return t("not_available", lang)
    return text.strip()


def localize_capacity(capacidad: str, lang: str) -> str:
    if _is_unknown(capacidad) or capacidad.strip().lower() == "desconocida":
        return t("unknown_capacity", lang)
    return capacidad.strip()


def localize_link_speed(speed: str, lang: str) -> str:
    low = (speed or "").strip().lower()
    if not low or low in ("no especificada", "not specified"):
        return t("link_speed_unknown", lang)
    return speed.strip()


def localize_interface(interfaz: str, lang: str) -> str:
    text = (interfaz or "").strip()
    low = text.lower()
    if _is_unknown(text) or low == "desconocida":
        return t("not_available", lang)
    if text == "ATA/SATA":
        return t("interface_ata_sata", lang)
    return text


def localize_sectors(sectores: str, lang: str) -> str:
    text = (sectores or "").strip()
    if _is_unknown(text) or low_eq(text, "no especificado"):
        return t("not_specified", lang)

    # Escapes Unicode: evita mojibake al empaquetar en consolas Windows legacy.
    match = re.search(
        r"(\d+)\s*B\s*(l[o\u00f3\ufffd]gico|logical)",
        text,
        re.I,
    )
    if match:
        label = "logical" if lang == "en" else "l\u00f3gico"
        return f"{match.group(1)}B {label}"

    if lang == "en":
        text = re.sub(
            r"\bl[o\u00f3\ufffd]gico\b", "logical", text, flags=re.I
        )
        text = re.sub(
            r"\bf[i\u00ed\ufffd]sico\b", "physical", text, flags=re.I
        )
        text = re.sub(r"\bbytes\b", "bytes", text, flags=re.I)
    else:
        text = re.sub(r"\blogical\b", "l\u00f3gico", text, flags=re.I)
        text = re.sub(r"\bphysical\b", "f\u00edsico", text, flags=re.I)
    return text


def localize_form_factor(factor: str, lang: str) -> str:
    text = (factor or "").strip()
    if _is_unknown(text) or low_eq(text, "no especificado"):
        return t("not_specified", lang)
    if text == "M.2 / NVMe":
        return t("form_factor_m2_nvme", lang)
    if text == "2.5\" / M.2":
        return t("form_factor_25_m2", lang)
    return text


def low_eq(text: str, marker: str) -> bool:
    return text.strip().lower() == marker.lower()


def localize_identification(report, lang: str) -> dict[str, str]:
    """Devuelve todos los valores de identificación traducidos para el PDF."""
    return {
        "modelo": localize_generic(report.modelo, lang),
        "capacidad": localize_capacity(report.capacidad, lang),
        "serial": localize_generic(report.serial, lang),
        "interfaz": localize_interface(report.interfaz, lang),
        "velocidad_interfaz": localize_link_speed(report.velocidad_interfaz, lang),
        "firmware": localize_generic(report.firmware, lang),
        "factor_forma": localize_form_factor(report.factor_forma, lang),
        "sectores": localize_sectors(report.sectores, lang),
    }
