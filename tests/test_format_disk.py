import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para formateo de discos (disk_ops)."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import disk_ops
from i18n import t


class TestNormalizeStorageError(unittest.TestCase):
    def test_strips_trailing_colon(self):
        self.assertEqual(
            disk_ops._normalize_storage_error("Virtual Disk Service error:"),
            "Virtual Disk Service error",
        )

    def test_empty_after_strip_returns_format_failed(self):
        self.assertEqual(disk_ops._normalize_storage_error(":"), "format_failed")

    def test_preserves_detail_after_colon(self):
        msg = "Virtual Disk Service error: The object is not found."
        self.assertEqual(disk_ops._normalize_storage_error(msg), msg)


class TestExtractDiskpartError(unittest.TestCase):
    DISKPART_NO_VOLUME = (
        "DiskPart successfully converted the selected disk to MBR format.\n"
        "DiskPart succeeded in creating the specified partition.\n"
        "There is no volume selected.\n"
        "Please select a volume and try again.\n"
    )

    def test_extracts_no_volume_line(self):
        msg = disk_ops._extract_diskpart_error(self.DISKPART_NO_VOLUME)
        self.assertIn("no volume", msg.lower())

    def test_empty_output_returns_format_failed(self):
        self.assertEqual(disk_ops._extract_diskpart_error(""), "format_failed")

    def test_output_failed_detects_no_volume(self):
        self.assertTrue(disk_ops._diskpart_output_failed(self.DISKPART_NO_VOLUME))


class TestFormatViaDiskpartScript(unittest.TestCase):
    @patch("disk_ops.os.unlink")
    @patch("disk_ops._diskpart_assigned_letter", return_value="G")
    @patch("disk_ops.subprocess.run")
    def test_script_includes_partition_select_and_online_after_clean(
        self, mock_run, mock_letter, mock_unlink,
    ):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        paths = []
        real_mkstemp = tempfile.mkstemp

        def tracking_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            paths.append(path)
            return fd, path

        with patch("tempfile.mkstemp", tracking_mkstemp):
            ok, letter = disk_ops._format_via_diskpart(2, "MBR", "ntfs", "ISOS", True)

        self.assertTrue(ok)
        self.assertEqual(letter, "G")
        with open(paths[0], encoding="ascii", errors="ignore") as fh:
            script = fh.read()
        self.assertIn("select partition 1", script)
        self.assertIn("format fs=ntfs label=\"ISOS\" quick", script)
        self.assertIn("attributes volume clear readonly noerr", script)
        clean_idx = script.index("clean")
        online_idx = script.index("online disk noerr", clean_idx)
        self.assertGreater(online_idx, clean_idx)

    @patch("disk_ops.os.unlink")
    @patch("disk_ops._diskpart_assigned_letter", return_value="G")
    @patch("disk_ops.subprocess.run")
    def test_gpt_script_includes_convert_gpt(
        self, mock_run, mock_letter, mock_unlink,
    ):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        paths = []
        real_mkstemp = tempfile.mkstemp

        def tracking_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            paths.append(path)
            return fd, path

        with patch("tempfile.mkstemp", tracking_mkstemp):
            ok, letter = disk_ops._format_via_diskpart(2, "GPT", "ntfs", "Y", True)

        self.assertTrue(ok)
        with open(paths[0], encoding="ascii", errors="ignore") as fh:
            script = fh.read()
        self.assertIn("convert gpt", script)

    @patch("disk_ops.os.unlink")
    @patch("disk_ops._diskpart_assigned_letter", return_value="G")
    @patch("disk_ops.subprocess.run")
    def test_clean_all_uses_deeper_wipe(self, mock_run, mock_letter, mock_unlink):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        paths = []
        real_mkstemp = tempfile.mkstemp

        def tracking_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            paths.append(path)
            return fd, path

        with patch("tempfile.mkstemp", tracking_mkstemp):
            ok, letter = disk_ops._format_via_diskpart(
                2, "GPT", "ntfs", "Y", True, clean_all=True,
            )

        self.assertTrue(ok)
        with open(paths[0], encoding="ascii", errors="ignore") as fh:
            script = fh.read()
        self.assertIn("clean all", script)


class TestFormatViaStorageScript(unittest.TestCase):
    @patch("disk_ops._run_ps")
    def test_script_a_refetches_disk_and_uses_basic_partition(self, mock_run):
        mock_run.return_value = '{"ok":true,"letter":"Y"}'
        ok, letter = disk_ops._format_via_storage(2, "GPT", "NTFS", "Y", True)
        self.assertTrue(ok)
        self.assertEqual(letter, "Y")
        script = mock_run.call_args_list[0][0][0]
        self.assertIn("ContainsKey('PartitionType')", script)
        self.assertIn("New-Partition @npArgs", script)
        self.assertIn("PartitionStyle GPT", script)
        self.assertGreaterEqual(script.count("$d=Get-Disk -Number $n"), 2)
        self.assertNotIn("Dismount-Volume", script)


class TestFormatDiskFallback(unittest.TestCase):
    @patch("disk_service.is_admin", return_value=True)
    @patch("disk_ops._invalidate_cache")
    @patch("disk_ops._format_via_diskpart", return_value=(True, "F"))
    @patch("disk_ops._format_via_storage", return_value=(False, "Clear-Disk failed"))
    @patch("disk_ops.prepare_disk_for_format", return_value=(True, ""))
    @patch("disk_ops._get_disk_fresh")
    def test_storage_failure_uses_diskpart(
        self, mock_fresh, mock_prep, mock_storage, mock_diskpart, mock_invalidate, _admin,
    ):
        mock_fresh.return_value = {
            "number": 2, "is_system": False, "is_boot": False, "bus_type": "SATA",
        }
        ok, info = disk_ops.format_disk(2, "MBR", "NTFS", "TEST", True)
        self.assertTrue(ok)
        self.assertEqual(info, "F")
        mock_diskpart.assert_called_once()
        mock_prep.assert_called_once_with(2)


class TestFormatDiskAdmin(unittest.TestCase):
    @patch("disk_service.is_admin", return_value=False)
    def test_format_not_admin(self, _admin):
        ok, info = disk_ops.format_disk(2, "MBR", "NTFS", "TEST", True)
        self.assertFalse(ok)
        self.assertEqual(info, "format_not_admin")


class TestFormatDiskUsbFirst(unittest.TestCase):
    @patch("disk_service.is_admin", return_value=True)
    @patch("disk_ops._invalidate_cache")
    @patch("disk_ops._format_via_storage")
    @patch("disk_ops._format_via_diskpart", return_value=(True, "G"))
    @patch("disk_ops.prepare_disk_for_format", return_value=(True, ""))
    @patch("disk_ops._get_disk_fresh")
    def test_usb_tries_diskpart_before_storage(
        self, mock_fresh, mock_prep, mock_diskpart, mock_storage, _invalidate, _admin,
    ):
        mock_fresh.return_value = {
            "number": 2, "is_system": False, "is_boot": False,
            "bus_type": "USB", "size": 58 * (1024 ** 3),
        }
        ok, info = disk_ops.format_disk(2, "GPT", "NTFS", "Yang", True)
        self.assertTrue(ok)
        self.assertEqual(info, "G")
        mock_diskpart.assert_called_once()
        mock_storage.assert_not_called()


class TestFormatDiskVdsRetry(unittest.TestCase):
    @patch("disk_service.is_admin", return_value=True)
    @patch("disk_ops._invalidate_cache")
    @patch("disk_ops._format_via_storage")
    @patch("disk_ops._format_via_diskpart")
    @patch("disk_ops.prepare_disk_for_format", return_value=(True, ""))
    @patch("disk_ops._get_disk_fresh")
    def test_vds_error_retries_with_clean_all(
        self, mock_fresh, mock_prep, mock_diskpart, mock_storage, _invalidate, _admin,
    ):
        vds_err = "Virtual Disk Service error:"
        mock_fresh.return_value = {
            "number": 2, "is_system": False, "is_boot": False,
            "bus_type": "USB", "size": 58 * (1024 ** 3),
        }
        mock_diskpart.side_effect = [(False, vds_err), (True, "G")]
        mock_storage.return_value = (False, vds_err)
        ok, info = disk_ops.format_disk(2, "GPT", "NTFS", "Yang", True)
        self.assertTrue(ok)
        self.assertEqual(info, "G")
        self.assertEqual(mock_diskpart.call_count, 2)
        self.assertTrue(mock_diskpart.call_args_list[1].kwargs.get("clean_all"))

    @patch("disk_service.is_admin", return_value=True)
    @patch("disk_ops._invalidate_cache")
    @patch("disk_ops._format_via_storage")
    @patch("disk_ops._format_via_diskpart")
    @patch("disk_ops.prepare_disk_for_format", return_value=(True, ""))
    @patch("disk_ops._get_disk_fresh")
    def test_vds_error_retries_mbr_after_clean_all_fails(
        self, mock_fresh, mock_prep, mock_diskpart, mock_storage, _invalidate, _admin,
    ):
        vds_err = "Virtual Disk Service error:"
        mock_fresh.return_value = {
            "number": 2, "is_system": False, "is_boot": False,
            "bus_type": "USB", "size": 58 * (1024 ** 3),
        }
        mock_diskpart.side_effect = [
            (False, vds_err),
            (False, vds_err),
            (True, "G"),
        ]
        mock_storage.return_value = (False, vds_err)
        ok, info = disk_ops.format_disk(2, "GPT", "NTFS", "Yang", True)
        self.assertTrue(ok)
        self.assertEqual(info, "G")
        mbr_calls = [c for c in mock_diskpart.call_args_list if c.args[1] == "MBR"]
        self.assertEqual(len(mbr_calls), 1)
        self.assertTrue(mbr_calls[0].kwargs.get("clean_all"))


class TestFormatDiskCombinedErrors(unittest.TestCase):
    @patch("disk_service.is_admin", return_value=True)
    @patch("disk_ops._invalidate_cache")
    @patch("disk_ops._format_via_storage")
    @patch("disk_ops._format_via_diskpart")
    @patch("disk_ops.prepare_disk_for_format", return_value=(True, ""))
    @patch("disk_ops._get_disk_fresh")
    def test_usb_returns_diskpart_and_storage_errors(
        self, mock_fresh, mock_prep, mock_diskpart, mock_storage, _invalidate, _admin,
    ):
        dp_err = "Virtual Disk Service error: The device is in use"
        st_err = "A parameter cannot be found that matches parameter name 'PartitionType'."
        mock_fresh.return_value = {
            "number": 2, "is_system": False, "is_boot": False,
            "bus_type": "USB", "size": 58 * (1024 ** 3),
        }
        mock_diskpart.return_value = (False, dp_err)
        mock_storage.return_value = (False, st_err)
        ok, info = disk_ops.format_disk(2, "MBR", "NTFS", "Yang USB", True)
        self.assertFalse(ok)
        self.assertIn("diskpart:", info)
        self.assertIn("storage:", info)
        self.assertIn("Virtual Disk Service", info)
        self.assertIn("PartitionType", info)


class TestCombineFormatErrors(unittest.TestCase):
    def test_combine_empty_returns_format_failed(self):
        self.assertEqual(disk_ops._combine_format_errors([]), "format_failed")

    def test_note_and_combine(self):
        errors: list[str] = []
        disk_ops._note_format_error(errors, "diskpart", "VDS error")
        disk_ops._note_format_error(errors, "storage", "PartitionType missing")
        self.assertEqual(
            disk_ops._combine_format_errors(errors),
            "diskpart: VDS error\nstorage: PartitionType missing",
        )


class TestPrepareDiskForFormat(unittest.TestCase):
    @patch("disk_ops._diskpart_offline_online")
    @patch("disk_ops._diskpart_remove_letters")
    @patch("disk_ops._parse_json", return_value={"ok": True})
    @patch("disk_ops._run_ps")
    def test_prepare_returns_ok_without_dismount_cmdlet(
        self, mock_run, _parse, mock_dp, _offline,
    ):
        mock_run.side_effect = ['{"ok":true}', "", ""]
        ok, err = disk_ops.prepare_disk_for_format(2)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        script = mock_run.call_args_list[0][0][0]
        self.assertIn("Get-Command Dismount-Volume", script)
        self.assertNotIn("$ErrorActionPreference='Stop'", script.split("catch")[0])
        mock_dp.assert_not_called()

    @patch("disk_ops._diskpart_offline_online")
    @patch("disk_ops._diskpart_remove_letters")
    @patch("disk_ops._parse_json", return_value={"ok": True})
    @patch("disk_ops._run_ps")
    def test_prepare_diskpart_fallback_when_letters_remain(
        self, mock_run, _parse, mock_dp, _offline,
    ):
        mock_run.side_effect = ['{"ok":true}', "G", ""]
        ok, err = disk_ops.prepare_disk_for_format(2)
        self.assertTrue(ok)
        mock_dp.assert_called_once_with(2)
        _offline.assert_called_once_with(2)

    @patch("disk_ops._parse_json", return_value={"ok": False, "error": "SYSTEM"})
    @patch("disk_ops._run_ps", return_value="")
    def test_prepare_system_disk(self, _run, _parse):
        ok, err = disk_ops.prepare_disk_for_format(0)
        self.assertFalse(ok)
        self.assertEqual(err, "system")


class TestDiskpartRemoveLetters(unittest.TestCase):
    @patch("disk_ops.os.unlink")
    @patch("disk_ops.subprocess.run")
    def test_parses_list_partition_and_removes_letters(self, mock_run, mock_unlink):
        list_out = (
            "  Volume ###  Ltr  Label        Fs     Type        Size     Status     Info\n"
            "  Volume 4     G   Yang         NTFS   Removable   57 GB    Healthy\n"
        )
        mock_run.side_effect = [
            subprocess.CompletedProcess([], 0, list_out, ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        paths = []
        real_mkstemp = tempfile.mkstemp

        def tracking_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            paths.append(path)
            return fd, path

        with patch("tempfile.mkstemp", tracking_mkstemp):
            disk_ops._diskpart_remove_letters(2)

        self.assertEqual(mock_run.call_count, 2)
        with open(paths[1], encoding="ascii", errors="ignore") as fh:
            remove_script = fh.read()
        self.assertIn("select volume 4", remove_script)
        self.assertIn("remove letter=G", remove_script)


class TestFormatErrorI18n(unittest.TestCase):
    def test_format_error_keys_english(self):
        self.assertIn("denied", t("format_error_access_denied", "en").lower())
        self.assertIn("volume", t("format_error_no_volume", "en").lower())
        self.assertEqual(t("format_error_title", "en"), "Format error")
        self.assertEqual(t("boot_error_title", "en"), "Bootable USB error")

    def test_format_error_keys_spanish(self):
        self.assertIn("denegado", t("format_error_access_denied", "es").lower())
        self.assertEqual(t("format_error_title", "es"), "Error al formatear")

    def test_format_error_vds_keys(self):
        self.assertIn("virtual disk", t("format_error_vds", "en").lower())
        self.assertIn("mbr", t("format_error_vds", "en").lower())
        self.assertIn("discos virtuales", t("format_error_vds", "es").lower())


if __name__ == "__main__":
    unittest.main()
