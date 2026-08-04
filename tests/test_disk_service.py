import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para detecciÃ³n de marca y enriquecimiento WMI."""

import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from disk_service import (
    DiskInfo,
    _brand_from_pnp,
    _enrich_disk_from_windows,
    _format_capacity_bytes,
    _is_weak_model,
    _merge_scan_entries,
    _parse_scan_output,
    _prefer_disk_entry,
    _usb_serials_from_rows,
    _windows_scan_entries,
    classify_disk,
    deduplicate_disks,
    disk_identity,
    extract_brand,
    get_disk_info,
    get_smart_data,
    scan_disk_signature,
    scan_disks,
    scan_disks_with_info,
)


class TestExtractBrand(unittest.TestCase):
    def test_datatraveler_is_kingston(self):
        self.assertEqual(extract_brand("DataTraveler 3.0"), "Kingston")

    def test_strips_usb_device_suffix(self):
        self.assertEqual(
            extract_brand("Kingston DataTraveler 3.0 USB Device"),
            "Kingston",
        )


class TestBrandFromPnp(unittest.TestCase):
    def test_kingston_vendor_id(self):
        pnp = "USBSTOR\\Disk&Ven_Kingston&Prod_DataTraveler_3.0&Rev_0001"
        self.assertEqual(_brand_from_pnp(pnp), "Kingston")


class TestWeakModel(unittest.TestCase):
    def test_dev_sdc_is_weak(self):
        self.assertTrue(_is_weak_model("/dev/sdc, SCSI device"))

    def test_real_model_not_weak(self):
        self.assertFalse(_is_weak_model("MTFDKBA1T0QGN-1BN1AABGA"))


class TestEnrichFromWindows(unittest.TestCase):
    def test_enriches_weak_usb_disk(self):
        info = DiskInfo(
            path="/dev/sdc",
            description="/dev/sdc, SCSI device",
            model="/dev/sdc, SCSI device",
            capacity="Unknown",
            brand="Unknown",
        )
        wmi_rows = [
            {
                "index": 2,
                "serial": "",
                "model": "Kingston DataTraveler 3.0 USB Device",
                "pnp": "USBSTOR\\Disk&Ven_Kingston&Prod_DataTraveler_3.0",
                "size": 68719476736,
            },
        ]
        _enrich_disk_from_windows(info, wmi_rows)
        self.assertEqual(info.brand, "Kingston")
        self.assertIn("DataTraveler", info.model)
        self.assertEqual(info.capacity, "64 GB")

    def test_fills_serial_from_wmi(self):
        info = DiskInfo(
            path="/dev/pd0",
            description="ATA device",
            model="Samsung SSD 870 QVO 2TB",
            serial="",
        )
        wmi_rows = [
            {
                "index": 0,
                "serial": "S5VWNJ0R500521A",
                "model": "Samsung SSD 870 QVO 2TB",
                "pnp": "",
                "size": 2000398934016,
            },
        ]
        _enrich_disk_from_windows(info, wmi_rows)
        self.assertEqual(info.serial, "S5VWNJ0R500521A")


class TestFormatCapacityBytes(unittest.TestCase):
    def test_formats_gb(self):
        self.assertEqual(_format_capacity_bytes(619897119872), "577 GB")


class TestDeduplicateDisks(unittest.TestCase):
    def test_same_serial_different_path(self):
        a = DiskInfo(
            path="/dev/pd0",
            description="ATA device",
            model="Samsung SSD 870 QVO 2TB",
            serial="S5VWNJ0R500521A",
        )
        b = DiskInfo(
            path="/dev/pd1",
            description="SCSI device",
            model="Samsung SSD 870 QVO 2TB",
            serial="S5VWNJ0R500521A",
        )
        result = deduplicate_disks([a, b])
        self.assertEqual(len(result), 1)

    def test_same_pd_index_different_path_style(self):
        a = DiskInfo(path="/dev/pd0", description="ATA", model="Disk A")
        b = DiskInfo(path="\\\\.\\PhysicalDrive0", description="ATA", model="Disk B")
        result = deduplicate_disks([a, b])
        self.assertEqual(len(result), 1)

    def test_distinct_serials_kept(self):
        a = DiskInfo(
            path="/dev/pd0", description="", model="Disk A", serial="SERIAL001",
        )
        b = DiskInfo(
            path="/dev/pd1", description="", model="Disk B", serial="SERIAL002",
        )
        result = deduplicate_disks([a, b])
        self.assertEqual(len(result), 2)

    def test_prefer_smart_available(self):
        weak = DiskInfo(
            path="/dev/pd0",
            description="SCSI",
            model="/dev/pd0, SCSI device",
            serial="ABC123",
            smart_available=False,
        )
        good = DiskInfo(
            path="/dev/pd0 -d ata",
            description="ATA",
            model="Samsung SSD 870 QVO 2TB",
            serial="ABC123",
            smart_available=True,
        )
        self.assertIs(_prefer_disk_entry(weak, good), good)
        self.assertEqual(len(deduplicate_disks([weak, good])), 1)
        self.assertTrue(deduplicate_disks([weak, good])[0].smart_available)


class TestDiskIdentity(unittest.TestCase):
    def test_same_serial_different_paths(self):
        a = DiskInfo(path="/dev/pd0", description="", serial="S5VWNJ0R500521A")
        b = DiskInfo(path="/dev/pd1", description="", serial="S5VWNJ0R500521A")
        self.assertEqual(disk_identity(a), disk_identity(b))

    def test_pd_index_without_serial(self):
        disk = DiskInfo(path="/dev/pd2", description="")
        self.assertEqual(disk_identity(disk), "pd:2")


class TestRobustUsbDiscovery(unittest.TestCase):
    def test_scan_parses_stdout_even_when_smartctl_returns_nonzero(self):
        result = CompletedProcess(
            ["smartctl", "--scan"],
            2,
            stdout="/dev/pd2 -d sat # /dev/pd2, ATA device\n",
            stderr="one device was not ready",
        )
        with patch("disk_service._run_hidden", return_value=result):
            disks = scan_disks("smartctl")
        self.assertEqual(disks[0]["comando"], "/dev/pd2")
        self.assertEqual(disks[0]["device_type"], "sat")

    def test_windows_usb_is_candidate_when_smartctl_scan_is_empty(self):
        rows = [{
            "index": 3,
            "serial": " USB-ABC 123 ",
            "model": "Seagate Expansion USB Device",
            "pnp": r"USBSTOR\Disk&Ven_Seagate",
            "interface": "USB",
            "size": 500_107_862_016,
        }]
        unavailable = CompletedProcess(["smartctl"], 1, stdout="", stderr="not ready")
        with (
            patch("disk_service._wmi_physical_disks", return_value=rows),
            patch("disk_service.scan_disks", return_value=[]),
            patch("disk_service._run_hidden", return_value=unavailable),
        ):
            disks = scan_disks_with_info("smartctl")
        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0].path, "/dev/pd3")
        self.assertEqual(disks[0].model, "Seagate Expansion USB Device")
        self.assertEqual(disks[0].category, "external")
        self.assertEqual(disks[0].transport, "USB")
        self.assertFalse(disks[0].smart_available)

    def test_usb_bridge_retries_sat_auto(self):
        empty = CompletedProcess(["smartctl"], 1, stdout="", stderr="unsupported")
        identity = CompletedProcess(
            ["smartctl"],
            0,
            stdout=(
                "Device Model:     Samsung SSD 870 EVO\n"
                "Serial Number:    S6P7 TEST-01\n"
                "User Capacity:    500,107,862,016 bytes [500 GB]\n"
            ),
            stderr="",
        )
        with patch("disk_service._run_hidden", side_effect=[empty, identity]) as run:
            info = get_disk_info(
                "smartctl", "/dev/pd4", "USB to SATA bridge", set()
            )
        self.assertTrue(info.smart_available)
        self.assertEqual(info.model, "Samsung SSD 870 EVO")
        self.assertEqual(info.smartctl_type, "sat,auto")
        self.assertEqual(run.call_args_list[1].args[0][2:4], ["-d", "sat,auto"])

    def test_report_read_reuses_successful_bridge_type(self):
        result = CompletedProcess(["smartctl"], 0, stdout="SMART DATA", stderr="")
        with patch("disk_service._run_hidden", return_value=result) as run:
            raw = get_smart_data("smartctl", "/dev/pd4", "sat,auto")
        self.assertEqual(raw, "SMART DATA")
        self.assertEqual(
            run.call_args.args[0],
            ["smartctl", "-a", "-d", "sat,auto", "/dev/pd4"],
        )

    def test_usb_serial_matching_is_normalized(self):
        rows = [{
            "interface": "USB",
            "pnp": "USBSTOR",
            "model": "External",
            "serial": "AA BB-001",
        }]
        serials = _usb_serials_from_rows(rows)
        info = DiskInfo(path="/dev/pd2", description="", serial="aabb001")
        self.assertEqual(classify_disk(info, "", "", serials), "external")

    def test_smartctl_and_windows_candidates_merge_by_disk_index(self):
        smart = _parse_scan_output("/dev/sdc -d sat # ATA device")
        windows = _windows_scan_entries([{
            "index": 2,
            "serial": "",
            "model": "Seagate Portable USB Device",
            "pnp": "USBSTOR",
            "interface": "USB",
            "size": 1,
        }])
        merged = _merge_scan_entries(smart, windows)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["comando"], "/dev/sdc")
        self.assertEqual(merged[0]["device_type"], "sat")
        self.assertIn("Seagate", merged[0]["descripcion"])

    def test_signature_changes_when_smartctl_becomes_ready(self):
        rows = [{
            "index": 2,
            "serial": "USB1",
            "model": "External USB",
            "pnp": "USBSTOR",
            "interface": "USB",
            "size": 1,
        }]
        with (
            patch("disk_service._wmi_physical_disks", return_value=rows),
            patch("disk_service.scan_disks", return_value=[]),
        ):
            windows_only = scan_disk_signature("smartctl")
        with (
            patch("disk_service._wmi_physical_disks", return_value=rows),
            patch(
                "disk_service.scan_disks",
                return_value=[{
                    "comando": "/dev/pd2",
                    "descripcion": "USB",
                    "device_type": "sat,auto",
                    "source": "smartctl",
                }],
            ),
        ):
            smart_ready = scan_disk_signature("smartctl")
        self.assertEqual(windows_only, frozenset({"pd:2"}))
        self.assertEqual(smart_ready, frozenset({"pd:2", "smart:pd:2"}))


if __name__ == "__main__":
    unittest.main()
