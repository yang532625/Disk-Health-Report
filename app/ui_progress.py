# -*- coding: utf-8 -*-
"""Utilidades de porcentaje para barras de progreso."""


def clamp_pct(pct: float) -> float:
    """Limita un porcentaje al intervalo [0, 100]."""
    return max(0.0, min(100.0, float(pct)))
