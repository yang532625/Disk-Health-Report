import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para medicion de uso de disco."""

import unittest
from unittest.mock import patch

import disk_ops


class TestUsageFromDriveLetters(unittest.TestCase):
    def test_aggregates_multiple_letters(self):
        class Du:
            def __init__(self, total, used):
                self.total = total
                self.used = used

        with patch("disk_ops.shutil.disk_usage") as mock_du:
            mock_du.side_effect = [
                Du(100, 10),
                Du(200, 50),
            ]
            result = disk_ops._usage_from_drive_letters(["E:", "F:"])

        self.assertEqual(result, (60, 300, 20.0))
        mock_du.assert_any_call("E:\\")
        mock_du.assert_any_call("F:\\")

    def test_returns_none_when_no_mounts(self):
        with patch("disk_ops.shutil.disk_usage", side_effect=OSError("no mount")):
            self.assertIsNone(disk_ops._usage_from_drive_letters(["Z:"]))


if __name__ == "__main__":
    unittest.main()
