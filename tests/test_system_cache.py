import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para limpieza de cachÃ© del sistema."""

import os
import tempfile
import unittest

from system_cache import _clean_directory_contents, _remove_entry


class TestSystemCache(unittest.TestCase):
    def test_clean_directory_contents_keeps_root(self):
        with tempfile.TemporaryDirectory() as root:
            file_path = os.path.join(root, "temp.txt")
            subdir = os.path.join(root, "nested")
            os.makedirs(subdir)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("hello")
            with open(os.path.join(subdir, "inner.txt"), "w", encoding="utf-8") as f:
                f.write("world")

            deleted, skipped, bytes_freed = _clean_directory_contents(root)

            self.assertTrue(os.path.isdir(root))
            self.assertEqual(os.listdir(root), [])
            self.assertEqual(deleted, 2)
            self.assertEqual(skipped, 0)
            self.assertGreater(bytes_freed, 0)

    def test_remove_entry_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "one.bin")
            with open(path, "wb") as f:
                f.write(b"data")
            self.assertTrue(_remove_entry(path))
            self.assertFalse(os.path.exists(path))

    def test_remove_entry_missing_is_safe(self):
        self.assertFalse(_remove_entry(os.path.join(tempfile.gettempdir(), "nonexistent_xyz_12345")))


if __name__ == "__main__":
    unittest.main()
