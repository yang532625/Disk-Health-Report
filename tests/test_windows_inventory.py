import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import unittest
from unittest import mock

import windows_inventory


class TestParseUninstall(unittest.TestCase):
    def test_skips_system_component(self):
        self.assertIsNone(windows_inventory._parse_uninstall_entry({
            "DisplayName": "Hidden",
            "SystemComponent": 1,
        }))

    def test_accepts_normal(self):
        entry = windows_inventory._parse_uninstall_entry({
            "DisplayName": "7-Zip",
            "DisplayVersion": "24.08",
            "Publisher": "Igor Pavlov",
        })
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "7-Zip")
        self.assertEqual(entry["source"], "msi")


class TestMergePrograms(unittest.TestCase):
    def test_merge_sorts(self):
        reg = [{"name": "Zebra", "version": "1", "source": "msi"}]
        store = [{"name": "Alpha", "version": "2", "source": "store"}]
        merged = windows_inventory.merge_program_lists(reg, store)
        self.assertEqual(merged[0]["name"], "Alpha")


class TestRunInventory(unittest.TestCase):
    def test_writes_json(self):
        with mock.patch.object(
            windows_inventory, "scan_registry_programs", return_value=[{"name": "A", "version": "1", "source": "msi"}],
        ), mock.patch.object(
            windows_inventory, "scan_store_apps", return_value=[],
        ), mock.patch.object(
            windows_inventory, "scan_drivers", return_value=[],
        ), mock.patch.object(
            windows_inventory, "_system_metadata", return_value={"Caption": "Win"},
        ), mock.patch.object(
            windows_inventory, "export_winget", return_value=(False, ""),
        ), mock.patch.object(
            windows_inventory.win_image_job, "inventory_path",
            return_value="C:/tmp/test_job/inventory.json",
        ), mock.patch("windows_inventory.os.makedirs"), mock.patch(
            "builtins.open", mock.mock_open(),
        ):
            inv = windows_inventory.run_inventory("job1")
        self.assertEqual(inv["program_count"], 1)


if __name__ == "__main__":
    unittest.main()
