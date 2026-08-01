# -*- coding: utf-8 -*-
"""Layout squarified treemap (coordenadas normalizadas 0–1)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class TreemapRect:
    x: float
    y: float
    w: float
    h: float
    index: int


def _worst(row: list[float], length: float) -> float:
    total = sum(row)
    if total <= 0 or length <= 0:
        return float("inf")
    rmax = max(row)
    rmin = min(row)
    return max((length ** 2 * rmax) / (total ** 2), (total ** 2) / (length ** 2 * rmin))


def _layout_row(
    row: list[tuple[float, int]],
    x: float,
    y: float,
    w: float,
    h: float,
    horizontal: bool,
) -> list[TreemapRect]:
    total = sum(v for v, _ in row)
    if total <= 0:
        return []
    rects: list[TreemapRect] = []
    if horizontal:
        row_h = total / w if w > 0 else 0
        cx = x
        for value, idx in row:
            rw = value / row_h if row_h > 0 else 0
            rects.append(TreemapRect(cx, y, rw, row_h, idx))
            cx += rw
    else:
        row_w = total / h if h > 0 else 0
        cy = y
        for value, idx in row:
            rh = value / row_w if row_w > 0 else 0
            rects.append(TreemapRect(x, cy, row_w, rh, idx))
            cy += rh
    return rects


def _squarify(
    items: list[tuple[float, int]],
    x: float,
    y: float,
    w: float,
    h: float,
) -> list[TreemapRect]:
    if not items:
        return []
    if len(items) == 1:
        value, idx = items[0]
        return [TreemapRect(x, y, w, h, idx)]
    if w >= h:
        horizontal = True
        length = w
    else:
        horizontal = False
        length = h

    row: list[tuple[float, int]] = []
    remaining = list(items)
    rects: list[TreemapRect] = []

    while remaining:
        candidate = remaining[0]
        test_row = row + [candidate]
        if not row or _worst([v for v, _ in test_row], length) <= _worst([v for v, _ in row], length):
            row = test_row
            remaining = remaining[1:]
        else:
            break

    if not row:
        row = [remaining[0]]
        remaining = remaining[1:]

    row_total = sum(v for v, _ in row)
    if horizontal:
        row_h = row_total / w if w > 0 else 0
        rects.extend(_layout_row(row, x, y, w, row_h, True))
        rects.extend(_squarify(remaining, x, y + row_h, w, h - row_h))
    else:
        row_w = row_total / h if h > 0 else 0
        rects.extend(_layout_row(row, x, y, row_w, h, False))
        rects.extend(_squarify(remaining, x + row_w, y, w - row_w, h))
    return rects


def layout_treemap(sizes: list[int], max_items: int = 48) -> tuple[list[TreemapRect], list[int]]:
    """Devuelve rects normalizados e índices (-1 = bloque Other)."""
    if not sizes:
        return [], []

    indices: list[int] = []
    weights: list[float] = []
    limit = min(len(sizes), max_items)
    for i in range(limit):
        indices.append(i)
        weights.append(float(max(sizes[i], 1)))

    if len(sizes) > limit:
        other = float(sum(max(s, 1) for s in sizes[limit:]))
        if other > 0:
            indices.append(-1)
            weights.append(other)

    total = sum(weights)
    if total <= 0:
        return [], indices

    norm = [w / total for w in weights]
    items = [(norm[i], indices[i]) for i in range(len(indices))]
    rects = _squarify(items, 0.0, 0.0, 1.0, 1.0)
    return rects, indices
