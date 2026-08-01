import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests de localizaciÃ³n del reporte PDF."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from report_i18n import localize_identification, localize_link_speed, localize_sectors
from smart_parser import DiskReport, parsear_smartctl


def _load_sample(name: str) -> str:
    path = os.path.join(ROOT, "samples", name)
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestReportI18n(unittest.TestCase):
    def test_link_speed_english(self):
        self.assertEqual(localize_link_speed("No especificada", "en"), "Not specified")

    def test_sectors_english(self):
        self.assertEqual(localize_sectors("512B lÃ³gico", "en"), "512B logical")

    def test_nvme_identification_english(self):
        report = parsear_smartctl(_load_sample("xraydisk_dump.txt"))
        ident = localize_identification(report, "en")
        self.assertEqual(ident["velocidad_interfaz"], "Not specified")
        self.assertEqual(ident["sectores"], "512B logical")

    def test_hdd_sample_spanish(self):
        from smart_parser import format_rotation_rate

        report = parsear_smartctl(_load_sample("smartctl_sample.txt"))
        ident = localize_identification(report, "es")
        self.assertEqual(format_rotation_rate(report, "es"), "5400 RPM")
        self.assertIn("lÃ³gico", localize_sectors(report.sectores, "es"))


if __name__ == "__main__":
    unittest.main()
