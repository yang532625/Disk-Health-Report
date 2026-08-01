import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para sondeo de uso y helpers del anillo."""

import unittest

from gui_app import (
    format_bytes,
    format_usage_size_text,
    usage_ring_needs_redraw,
    usage_ring_rounded_pct,
    usage_size_needs_update,
)
from ui_progress import clamp_pct


class TestClampPct(unittest.TestCase):
    def test_clamps_high(self):
        self.assertEqual(clamp_pct(150.0), 100.0)

    def test_clamps_low(self):
        self.assertEqual(clamp_pct(-5.0), 0.0)

    def test_passes_through(self):
        self.assertEqual(clamp_pct(42.5), 42.5)


class TestUsageRingRedraw(unittest.TestCase):
    def test_rounds_to_int(self):
        self.assertEqual(usage_ring_rounded_pct(3.4), 3)
        self.assertEqual(usage_ring_rounded_pct(3.6), 4)

    def test_none_stays_none(self):
        self.assertIsNone(usage_ring_rounded_pct(None))

    def test_skips_when_rounded_unchanged(self):
        self.assertFalse(usage_ring_needs_redraw(3, 3.2))
        self.assertFalse(usage_ring_needs_redraw(3, 3.4))

    def test_redraws_when_rounded_changes(self):
        self.assertTrue(usage_ring_needs_redraw(3, 3.6))
        self.assertTrue(usage_ring_needs_redraw(3, 4.0))

    def test_redraws_from_none(self):
        self.assertTrue(usage_ring_needs_redraw(None, 3.0))

    def test_redraws_to_none(self):
        self.assertTrue(usage_ring_needs_redraw(3, None))


class TestFormatUsageSize(unittest.TestCase):
    def test_mb_sizes(self):
        used = 500 * 1024 ** 2
        total = 900 * 1024 ** 2
        self.assertEqual(format_usage_size_text(used, total), "500.0 MB / 900.0 MB")

    def test_gb_sizes(self):
        used = int(450.12 * 1024 ** 3)
        total = int(931.51 * 1024 ** 3)
        text = format_usage_size_text(used, total)
        self.assertIn("GB", text)
        self.assertIn("/", text)

    def test_tb_sizes(self):
        used = int(1.5 * 1024 ** 4)
        total = int(2.0 * 1024 ** 4)
        text = format_usage_size_text(used, total)
        self.assertEqual(text, "1.50 TB / 2.00 TB")

    def test_format_bytes_tb(self):
        self.assertEqual(format_bytes(2 * 1024 ** 4), "2.00 TB")


class TestUsageSizeUpdate(unittest.TestCase):
    def test_updates_when_bytes_change(self):
        self.assertTrue(usage_size_needs_update((100, 200), 101, 200))

    def test_skips_when_unchanged(self):
        self.assertFalse(usage_size_needs_update((100, 200), 100, 200))

    def test_updates_from_none(self):
        self.assertTrue(usage_size_needs_update(None, 100, 200))

    def test_updates_when_pct_same_but_bytes_differ(self):
        """Bytes can shift without changing rounded ring percent."""
        total = 1_000_000_000
        last_used = 399_999_999
        new_used = 400_000_001
        last_pct = usage_ring_rounded_pct(last_used / total * 100)
        new_pct = usage_ring_rounded_pct(new_used / total * 100)
        self.assertEqual(last_pct, new_pct)
        self.assertTrue(usage_size_needs_update((last_used, total), new_used, total))


if __name__ == "__main__":
    unittest.main()
