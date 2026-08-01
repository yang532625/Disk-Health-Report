import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para detecciÃ³n de marca y enriquecimiento WMI."""

import unittest

from disk_service import (
    DiskInfo,
    _brand_from_pnp,
    _enrich_disk_from_windows,
    _format_capacity_bytes,
    _is_weak_model,
    _prefer_disk_entry,
    deduplicate_disks,
    disk_identity,
    extract_brand,
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


if __name__ == "__main__":
    unittest.main()
