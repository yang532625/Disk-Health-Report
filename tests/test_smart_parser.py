import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Regression tests for smartctl parsing."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from i18n import get_attr_name
from smart_parser import (
    HEALTH_ATTR_IDS,
    NVME_ATTR_CRITICAL_WARNING,
    _evaluar_estado,
    format_rotation_rate,
    parsear_smartctl,
)


def _load_sample(name: str) -> str:
    path = os.path.join(ROOT, "samples", name)
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestSmartctlSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = parsear_smartctl(_load_sample("smartctl_sample.txt"))

    def test_basic_identification(self):
        self.assertEqual(self.report.modelo, "ST2000VX007-2AY102")
        self.assertTrue(self.report.smart_passed)
        self.assertFalse(self.report.es_nvme)

    def test_rotation_rate_hdd(self):
        self.assertEqual(self.report.rotation_rate_raw, "5400 rpm")
        self.assertFalse(self.report.es_ssd)
        self.assertEqual(format_rotation_rate(self.report, "en"), "5400 RPM")
        self.assertEqual(format_rotation_rate(self.report, "es"), "5400 RPM")

    def test_usage_counters(self):
        self.assertEqual(self.report.horas, 31509)
        self.assertEqual(self.report.ciclos_encendido, 145)
        self.assertFalse(self.report.ciclos_es_start_stop)

    def test_temperature_min_max(self):
        self.assertEqual(self.report.temperatura_actual, 27)
        self.assertEqual(self.report.temperatura_promedio, 35)
        self.assertEqual(self.report.temperatura_maxima, 48)

    def test_sector_size_and_data_quality(self):
        self.assertEqual(self.report.sector_size_bytes, 4096)
        self.assertEqual(self.report.data_quality, "full")

    def test_health_attrs_only(self):
        attr_ids = [a.attr_id for a in self.report.atributos_criticos]
        self.assertGreaterEqual(len(attr_ids), 7)
        for aid in attr_ids:
            self.assertIn(aid, HEALTH_ATTR_IDS)
        self.assertNotIn(9, attr_ids)
        self.assertNotIn(241, attr_ids)
        self.assertNotIn(242, attr_ids)

    def test_attr_187_199_names_and_evaluation(self):
        self.assertEqual(get_attr_name(187, "es"), "Reported Uncorrectable")
        self.assertEqual(get_attr_name(199, "en"), "UDMA CRC Error Count")
        self.assertEqual(_evaluar_estado(187, "0", False, 0), "OK")
        self.assertEqual(_evaluar_estado(199, "3", False, 0), "Alerta")


class TestXraydiskNvmeSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = parsear_smartctl(_load_sample("xraydisk_dump.txt"))

    def test_nvme_identification(self):
        self.assertTrue(self.report.es_nvme)
        self.assertIn("XrayDisk", self.report.modelo)

    def test_rotation_rate_nvme(self):
        self.assertTrue(self.report.es_ssd)
        self.assertEqual(format_rotation_rate(self.report, "en"), "N/A (SSD)")

    def test_nvme_usage(self):
        self.assertEqual(self.report.horas, 1514)
        self.assertAlmostEqual(self.report.datos_escritos_tb, 1.43, places=1)
        self.assertAlmostEqual(self.report.datos_leidos_tb, 2.28, places=1)

    def test_nvme_temperature_honest(self):
        self.assertEqual(self.report.temperatura_actual, 40)
        self.assertIsNone(self.report.temperatura_promedio)
        self.assertIsNone(self.report.temperatura_maxima)

    def test_nvme_attrs(self):
        self.assertEqual(len(self.report.atributos_criticos), 7)
        self.assertEqual(self.report.atributos_criticos[0].attr_id, NVME_ATTR_CRITICAL_WARNING)

    def test_nvme_data_quality(self):
        self.assertEqual(self.report.data_quality, "partial")


if __name__ == "__main__":
    unittest.main()
