import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from unittest import mock

import disk_ops
import ventoy_runner


class TestVentoyCliArgs(unittest.TestCase):
    def test_install_gpt_defaults(self):
        args = ventoy_runner.build_cli_args(2)
        self.assertEqual(args[0], "VTOYCLI")
        self.assertIn("/I", args)
        self.assertIn("/PhyDrive:2", args)
        self.assertIn("/GPT", args)
        self.assertNotIn("/NoSB", args)
        self.assertNotIn("/FS:", "".join(args))

    def test_update_mbr_ntfs(self):
        args = ventoy_runner.build_cli_args(
            0, update=True, gpt=False, secure_boot=False,
            filesystem="NTFS", reserve_mb=512, no_usb_check=True,
        )
        self.assertIn("/U", args)
        self.assertNotIn("/GPT", args)
        self.assertIn("/NoSB", args)
        self.assertIn("/R:512", args)
        self.assertIn("/FS:NTFS", args)
        self.assertIn("/NoUSBCheck", args)


class TestVentoyCliFiles(unittest.TestCase):
    def test_read_percent_and_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            pct_path = os.path.join(tmp, ventoy_runner.CLI_PERCENT_FILE)
            done_path = os.path.join(tmp, ventoy_runner.CLI_DONE_FILE)
            with open(pct_path, "w", encoding="utf-8") as fh:
                fh.write("42\n")
            with open(done_path, "w", encoding="utf-8") as fh:
                fh.write("0\n")
            self.assertEqual(ventoy_runner.read_cli_percent(pct_path), 42.0)
            self.assertTrue(ventoy_runner.read_cli_done(done_path))

    def test_read_percent_missing(self):
        self.assertIsNone(ventoy_runner.read_cli_percent("/nonexistent/cli_percent.txt"))


class TestVentoyLogParse(unittest.TestCase):
    def test_parse_last_error_strips_timestamp(self):
        log = (
            "[2026/06/25 20:15:00.123] Ventoy_CLI_Update start ...\n"
            "[2026/06/25 20:15:01.456] [ERROR] No Ventoy information detected in PhyDrive 2\n"
        )
        err = ventoy_runner.parse_cli_log_last_error(log)
        self.assertIn("No Ventoy information detected", err)
        self.assertNotIn("2026/06/25", err)

    def test_classify_update_not_ventoy(self):
        log = "[ERROR] No Ventoy information detected in PhyDrive 2"
        self.assertEqual(
            ventoy_runner.classify_ventoy_error(log),
            "ventoy_update_not_ventoy",
        )

    def test_classify_disk_locked(self):
        self.assertEqual(
            ventoy_runner.classify_ventoy_error("Failed to open physical disk"),
            "ventoy_disk_locked",
        )
        self.assertEqual(
            ventoy_runner.classify_ventoy_error("Volume is in use"),
            "ventoy_disk_locked",
        )

    def test_read_cli_log_from_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ventoy_runner.CLI_LOG_FILE)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("test line\n")
            self.assertIn("test line", ventoy_runner.read_cli_log(tmp))


class TestEnsureVentoy(unittest.TestCase):
    def test_ensure_copies_bundle(self):
        with tempfile.TemporaryDirectory() as bundled:
            exe = os.path.join(bundled, "Ventoy2Disk_X64.exe")
            with open(exe, "wb") as fh:
                fh.write(b"MZ")
            ventoy_sub = os.path.join(bundled, "ventoy")
            os.makedirs(ventoy_sub)
            with open(os.path.join(ventoy_sub, "version"), "w", encoding="utf-8") as fh:
                fh.write("1.1.16")
            cache = os.path.join(tempfile.gettempdir(), "dhr_ventoy_test_cache")
            with mock.patch.object(ventoy_runner, "_ventoy_cache_dir", return_value=cache):
                with mock.patch.object(
                    ventoy_runner.bundled_assets,
                    "ventoy_bundle_dir",
                    return_value=bundled,
                ):
                    try:
                        if os.path.isdir(cache):
                            import shutil
                            shutil.rmtree(cache)
                        root = ventoy_runner.ensure_ventoy()
                        self.assertIsNotNone(root)
                        assert root is not None
                        self.assertTrue(os.path.isfile(os.path.join(root, "Ventoy2Disk_X64.exe")))
                    finally:
                        if os.path.isdir(cache):
                            import shutil
                            shutil.rmtree(cache, ignore_errors=True)


class TestDiskHasVentoy(unittest.TestCase):
    @mock.patch.object(disk_ops, "_run_ps", return_value="true")
    def test_detects_true(self, _mock_ps):
        self.assertTrue(disk_ops.disk_has_ventoy(2))

    @mock.patch.object(disk_ops, "_run_ps", return_value="false")
    def test_detects_false(self, _mock_ps):
        self.assertFalse(disk_ops.disk_has_ventoy(2))


class TestPrepareMultibootUsb(unittest.TestCase):
    @mock.patch.object(ventoy_runner, "install_ventoy", return_value=(True, "ventoy_done", ""))
    @mock.patch.object(disk_ops, "disk_has_ventoy", return_value=False)
    @mock.patch.object(ventoy_runner, "ensure_ventoy", return_value="/tmp/ventoy")
    def test_install_when_not_ventoy(self, _ensure, _has, mock_install):
        ok, key, _detail = ventoy_runner.prepare_multiboot_usb(2)
        self.assertTrue(ok)
        self.assertEqual(key, "boot_multiboot_done")
        mock_install.assert_called_once()
        self.assertFalse(mock_install.call_args.kwargs["update"])

    @mock.patch.object(ventoy_runner, "install_ventoy", return_value=(True, "ventoy_done", ""))
    @mock.patch.object(disk_ops, "disk_has_ventoy", return_value=True)
    @mock.patch.object(ventoy_runner, "ensure_ventoy", return_value="/tmp/ventoy")
    def test_update_when_ventoy(self, _ensure, _has, mock_install):
        ok, key, _detail = ventoy_runner.prepare_multiboot_usb(2)
        self.assertTrue(ok)
        self.assertEqual(key, "boot_multiboot_done")
        mock_install.assert_called_once()
        self.assertTrue(mock_install.call_args.kwargs["update"])

    @mock.patch.object(ventoy_runner, "install_ventoy")
    @mock.patch.object(disk_ops, "disk_has_ventoy", return_value=True)
    @mock.patch.object(ventoy_runner, "ensure_ventoy", return_value="/tmp/ventoy")
    def test_retry_install_on_false_positive(self, _ensure, _has, mock_install):
        mock_install.side_effect = [
            (False, "ventoy_update_not_ventoy", "No Ventoy information detected"),
            (True, "ventoy_done", ""),
        ]
        ok, key, _detail = ventoy_runner.prepare_multiboot_usb(2)
        self.assertTrue(ok)
        self.assertEqual(key, "boot_multiboot_done")
        self.assertEqual(mock_install.call_count, 2)
        self.assertTrue(mock_install.call_args_list[0].kwargs["update"])
        self.assertFalse(mock_install.call_args_list[1].kwargs["update"])

    @mock.patch.object(ventoy_runner, "install_ventoy")
    @mock.patch.object(ventoy_runner, "read_cli_log", return_value="Ventoy information detected")
    @mock.patch.object(disk_ops, "disk_has_ventoy", return_value=False)
    @mock.patch.object(ventoy_runner, "ensure_ventoy", return_value="/tmp/ventoy")
    def test_retry_update_after_install_hint(self, _ensure, _has, _log, mock_install):
        mock_install.side_effect = [
            (False, "ventoy_failed", "already installed"),
            (True, "ventoy_done", ""),
        ]
        ok, key, _detail = ventoy_runner.prepare_multiboot_usb(2)
        self.assertTrue(ok)
        self.assertEqual(key, "boot_multiboot_done")
        self.assertEqual(mock_install.call_count, 2)
        self.assertFalse(mock_install.call_args_list[0].kwargs["update"])
        self.assertTrue(mock_install.call_args_list[1].kwargs["update"])


class TestLogSuggestsExistingVentoy(unittest.TestCase):
    def test_negative(self):
        self.assertFalse(
            ventoy_runner._log_suggests_existing_ventoy(
                "[ERROR] No Ventoy information detected",
            ),
        )

    def test_positive(self):
        self.assertTrue(
            ventoy_runner._log_suggests_existing_ventoy("Ventoy information detected"),
        )


if __name__ == "__main__":
    unittest.main()
