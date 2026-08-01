import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import json
import unittest
from unittest import mock

import partition_ops


MB = 1024 * 1024


class TestHelpers(unittest.TestCase):
    def test_normalize_letter(self):
        self.assertEqual(partition_ops.normalize_letter("g:"), "G")
        self.assertEqual(partition_ops.normalize_letter("C"), "C")
        self.assertEqual(partition_ops.normalize_letter("1"), "")
        self.assertEqual(partition_ops.normalize_letter(""), "")
        self.assertEqual(partition_ops.normalize_letter("AB"), "")

    def test_fs_ps(self):
        self.assertEqual(partition_ops._fs_ps("exfat"), "exFAT")
        self.assertEqual(partition_ops._fs_ps("fat32"), "FAT32")
        self.assertEqual(partition_ops._fs_ps("ntfs"), "NTFS")
        self.assertEqual(partition_ops._fs_ps("weird"), "NTFS")

    def test_safe_label(self):
        self.assertEqual(partition_ops._safe_label("my'disk`$x"), "mydiskx")
        self.assertEqual(len(partition_ops._safe_label("x" * 50)), 32)


class TestSegments(unittest.TestCase):
    def test_unallocated_gap_detected(self):
        parts = [
            {"offset": 1 * MB, "size": 100 * MB, "partition_number": 1},
            {"offset": 300 * MB, "size": 100 * MB, "partition_number": 2},
        ]
        segs = partition_ops._compute_segments(parts, 500 * MB)
        kinds = [s["kind"] for s in segs]
        # part, gap, part, tail-gap
        self.assertEqual(kinds, ["partition", "unallocated", "partition", "unallocated"])
        gap = segs[1]
        self.assertEqual(gap["offset"], 101 * MB)
        self.assertEqual(gap["size"], 199 * MB)

    def test_no_gap_when_contiguous(self):
        parts = [
            {"offset": 1 * MB, "size": 100 * MB, "partition_number": 1},
            {"offset": 101 * MB, "size": 399 * MB, "partition_number": 2},
        ]
        segs = partition_ops._compute_segments(parts, 500 * MB)
        self.assertEqual([s["kind"] for s in segs], ["partition", "partition"])

    def test_build_disk_computes_used(self):
        item = {
            "Number": 2, "Model": "Test", "BusType": "USB", "Size": 500 * MB,
            "PartitionStyle": "GPT", "IsSystem": False, "IsBoot": False,
            "Partitions": [
                {"PartitionNumber": 1, "DriveLetter": "G", "Offset": 1 * MB,
                 "Size": 200 * MB, "Size_": 0, "Label": "DATA",
                 "FileSystem": "NTFS", "SizeRemaining": 50 * MB,
                 "IsActive": False, "IsHidden": False},
            ],
        }
        disk = partition_ops._build_disk(item)
        self.assertEqual(disk["number"], 2)
        self.assertEqual(disk["partitions"][0]["used"], 150 * MB)
        self.assertEqual(disk["partitions"][0]["letter"], "G")
        self.assertTrue(partition_ops.disk_has_unallocated(disk))


class TestListParsing(unittest.TestCase):
    def test_list_disks_parses_json(self):
        payload = [{
            "Number": 1, "Model": "Disk", "BusType": "SATA", "Size": 1000 * MB,
            "PartitionStyle": "MBR", "IsSystem": False, "IsBoot": False,
            "Partitions": {
                "PartitionNumber": 1, "DriveLetter": "E", "Offset": 1 * MB,
                "Size": 999 * MB, "Label": "X", "FileSystem": "exFAT",
                "SizeRemaining": 0, "IsActive": True, "IsHidden": False,
            },
        }]
        with mock.patch.object(partition_ops, "_run_ps",
                               return_value=json.dumps(payload)):
            with mock.patch.object(partition_ops.sys, "platform", "win32"):
                disks = partition_ops.list_disks_with_partitions()
        self.assertEqual(len(disks), 1)
        self.assertEqual(len(disks[0]["partitions"]), 1)
        self.assertTrue(disks[0]["partitions"][0]["is_active"])

    def test_list_disks_empty_on_blank(self):
        with mock.patch.object(partition_ops, "_run_ps", return_value=""):
            with mock.patch.object(partition_ops.sys, "platform", "win32"):
                self.assertEqual(partition_ops.list_disks_with_partitions(), [])


class TestOps(unittest.TestCase):
    def test_delete_guard_in_script(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return json.dumps({"ok": True})

        with mock.patch.object(partition_ops, "_run_ps", side_effect=fake_run):
            with mock.patch.object(partition_ops.sys, "platform", "win32"):
                ok, info = partition_ops.delete_partition(3, 2)
        self.assertTrue(ok)
        self.assertIn("IsSystem", captured["script"])
        self.assertIn("Remove-Partition", captured["script"])

    def test_op_failure_returns_error(self):
        with mock.patch.object(partition_ops, "_run_ps",
                               return_value=json.dumps({"ok": False, "error": "boom"})):
            with mock.patch.object(partition_ops.sys, "platform", "win32"):
                ok, info = partition_ops.delete_partition(1, 1)
        self.assertFalse(ok)
        self.assertEqual(info, "boom")

    def test_invalid_letter_rejected(self):
        with mock.patch.object(partition_ops.sys, "platform", "win32"):
            ok, info = partition_ops.set_drive_letter(1, 1, "123")
        self.assertFalse(ok)
        self.assertEqual(info, "pm_invalid_letter")

    def test_create_uses_max_when_no_size(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return json.dumps({"ok": True, "letter": "H"})

        with mock.patch.object(partition_ops, "_run_ps", side_effect=fake_run):
            with mock.patch.object(partition_ops.sys, "platform", "win32"):
                ok, letter = partition_ops.create_partition(2, None, "NTFS", "L", "")
        self.assertTrue(ok)
        self.assertEqual(letter, "H")
        self.assertIn("-UseMaximumSize", captured["script"])
        self.assertIn("Format-Volume", captured["script"])


if __name__ == "__main__":
    unittest.main()
