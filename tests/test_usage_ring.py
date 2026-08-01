import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para el gauge de uso (PIL)."""

import unittest
import tkinter as tk

from PIL import ImageColor

from gui_app import (
    COLOR_RING_TRACK,
    DiskHealthApp,
    RING_SIZE,
    RING_SCALE,
    usage_ring_arc_angles,
)


def _count_ring_colored_pixels(img) -> int:
    track = ImageColor.getrgb(COLOR_RING_TRACK)
    cx, cy = img.size[0] // 2, img.size[1] // 2
    inner_r = img.width // 2 - 36
    count = 0
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = img.getpixel((x, y))
            if a < 128:
                continue
            if (x - cx) ** 2 + (y - cy) ** 2 < inner_r ** 2:
                continue
            if (r, g, b) == track:
                continue
            count += 1
    return count


class TestUsageRingArcAngles(unittest.TestCase):
    def test_eighty_percent_sweep(self):
        start, end = usage_ring_arc_angles(80)
        self.assertAlmostEqual(start, -198.0)
        self.assertEqual(end, 90.0)

    def test_forty_percent_sweep(self):
        start, end = usage_ring_arc_angles(40)
        self.assertAlmostEqual(start, -54.0)
        self.assertEqual(end, 90.0)


class TestUsageRingImage(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = DiskHealthApp()
        self.app.withdraw()

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_zero_percent_ring(self):
        img = self.app._render_usage_ring_image(0)
        self.assertEqual(img.size, (RING_SIZE, RING_SIZE))

    def test_partial_percent_ring(self):
        img = self.app._render_usage_ring_image(40)
        self.assertEqual(img.size, (RING_SIZE, RING_SIZE))

    def test_high_percent_ring(self):
        img = self.app._render_usage_ring_image(80)
        self.assertEqual(img.size, (RING_SIZE, RING_SIZE))

    def test_none_percent_ring(self):
        img = self.app._render_usage_ring_image(None)
        self.assertEqual(img.size, (RING_SIZE, RING_SIZE))

    def test_eighty_percent_more_colored_than_forty(self):
        img80 = self.app._render_usage_ring_image(80, downscale=False)
        img40 = self.app._render_usage_ring_image(40, downscale=False)
        self.assertEqual(img80.size, (RING_SIZE * RING_SCALE, RING_SIZE * RING_SCALE))
        self.assertGreater(_count_ring_colored_pixels(img80), _count_ring_colored_pixels(img40))


if __name__ == "__main__":
    unittest.main()
