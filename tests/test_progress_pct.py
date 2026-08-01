import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import unittest

from ui_progress import clamp_pct


def _set_progress_pct(pct: float, status_key: str | None = None,
                      update_status: bool = True, **kwargs):
    """Misma firma que DiskHealthApp._set_progress_pct (sin self)."""
    pct = clamp_pct(pct)
    if update_status and status_key:
        _ = int(round(pct))
        _ = kwargs


class TestClampPct(unittest.TestCase):
    def test_clamps_low(self):
        self.assertEqual(clamp_pct(-5), 0.0)

    def test_clamps_high(self):
        self.assertEqual(clamp_pct(150), 100.0)

    def test_passthrough(self):
        self.assertEqual(clamp_pct(42.5), 42.5)


class TestProgressPctCallPattern(unittest.TestCase):
    def test_scan_progress_pattern_ok(self):
        """disk_progress: pct posicional + status_key, sin pct en kwargs."""
        _set_progress_pct(50.0, status_key="scanning")

    def test_scan_progress_pattern_duplicate_pct_fails(self):
        with self.assertRaises(TypeError):
            _set_progress_pct(50.0, status_key="scanning", pct=50)

    def test_pseudo_progress_pattern_ok(self):
        _set_progress_pct(33.0, status_key="progress_processing")


if __name__ == "__main__":
    unittest.main()
