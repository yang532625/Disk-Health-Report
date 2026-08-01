import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para send_to_recycle_bin."""

import os
import tempfile
import unittest

import disk_ops


class TestRecycleBin(unittest.TestCase):
    def test_is_path_under_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "a.txt")
            with open(file_path, "w") as fh:
                fh.write("x")
            self.assertTrue(disk_ops.is_path_under_volume(file_path, tmp))
            self.assertFalse(disk_ops.is_path_under_volume(tmp, tmp))

    def test_send_rejects_outside_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = os.path.join(tempfile.gettempdir(), "dhr_outside_test.txt")
            try:
                with open(other, "w") as fh:
                    fh.write("x")
                ok = disk_ops.send_to_recycle_bin(other, volume_root=tmp)
                self.assertFalse(ok)
            finally:
                if os.path.isfile(other):
                    os.remove(other)


if __name__ == "__main__":
    unittest.main()
