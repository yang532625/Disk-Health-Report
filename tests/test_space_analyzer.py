import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para space_analyzer."""

import os
import tempfile
import threading
import unittest

import space_analyzer


class TestSpaceAnalyzer(unittest.TestCase):
    def test_invalid_root_returns_empty(self):
        entries, total = space_analyzer.scan_volume("/nonexistent/path/xyz")
        self.assertEqual(entries, [])
        self.assertEqual(total, 0)

    def test_sorts_largest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            big_dir = os.path.join(tmp, "big")
            medium_dir = os.path.join(tmp, "medium")
            os.makedirs(big_dir)
            os.makedirs(medium_dir)
            with open(os.path.join(big_dir, "data.bin"), "wb") as fh:
                fh.write(b"x" * 1024 * 1024)
            with open(os.path.join(medium_dir, "data.bin"), "wb") as fh:
                fh.write(b"x" * 100 * 1024)
            with open(os.path.join(tmp, "small.txt"), "wb") as fh:
                fh.write(b"x" * 1024)

            entries, total = space_analyzer.scan_volume(tmp)
            self.assertGreaterEqual(entries[0].size_bytes, 100 * 1024)
            self.assertGreater(entries[0].size_bytes, entries[-1].size_bytes)
            self.assertGreater(total, 1024 * 1024)

    def test_progress_callback_reaches_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "sample.txt"), "wb") as fh:
                fh.write(b"x" * 4096)
            seen: list[float] = []

            def progress(files, dirs, pct):
                seen.append(pct)

            space_analyzer.scan_volume(tmp, progress_cb=progress)
            self.assertTrue(seen)
            self.assertEqual(seen[-1], 100.0)

    def test_progress_increases_with_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(150):
                with open(os.path.join(tmp, f"f{i}.bin"), "wb") as fh:
                    fh.write(b"x" * 2048)
            seen: list[float] = []

            def progress(files, dirs, pct):
                seen.append(pct)

            space_analyzer.scan_volume(tmp, progress_cb=progress)
            self.assertTrue(any(0 < p < 100 for p in seen))
            self.assertEqual(seen[-1], 100.0)

    def test_cancel_clears_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(20):
                path = os.path.join(tmp, f"dir{i}")
                os.makedirs(path)
                with open(os.path.join(path, "f.bin"), "wb") as fh:
                    fh.write(b"x" * 512)

            cancel = threading.Event()
            cancel.set()
            entries, total = space_analyzer.scan_volume(
                tmp, cancel_event=cancel,
            )
            self.assertEqual(entries, [])
            self.assertEqual(total, 0)


if __name__ == "__main__":
    unittest.main()
