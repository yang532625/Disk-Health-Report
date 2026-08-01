import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests de paginaciÃ³n del reporte PDF."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from report_builder import exportar_pdf, generar_html
from smart_parser import parsear_smartctl


def _load_sample(name: str) -> str:
    path = os.path.join(ROOT, "samples", name)
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestReportPagination(unittest.TestCase):
    def test_hdd_report_fits_two_pages(self):
        report = parsear_smartctl(_load_sample("smartctl_sample.txt"))
        html = generar_html(report, "en")
        pdf_path = os.path.join(ROOT, "_test_report_pages.pdf")
        try:
            ok = exportar_pdf(html, pdf_path)
            self.assertTrue(ok)
            import pymupdf as fitz

            doc = fitz.open(pdf_path)
            pages = len(doc)
            doc.close()
            self.assertLessEqual(pages, 2, f"Report should fit in 2 pages, got {pages}")
        finally:
            if os.path.isfile(pdf_path):
                os.remove(pdf_path)


if __name__ == "__main__":
    unittest.main()
