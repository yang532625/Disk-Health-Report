import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import windows_imaging


class TestScripts(unittest.TestCase):
    def test_sysprep_script_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = windows_imaging.generate_sysprep_script(tmp)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("sysprep.exe", text.lower())

    def test_capture_script_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            wim = os.path.join(tmp, "out", "install.wim")
            path = windows_imaging.generate_capture_script(wim, source_drive="C:")
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("Capture-Image", text)
            self.assertIn("install.wim", text)

    def test_autounattend_xml(self):
        xml = windows_imaging._minimal_autounattend("es-ES")
        self.assertIn("unattend", xml)
        self.assertIn("es-ES", xml)


class TestEstimateWim(unittest.TestCase):
    def test_positive(self):
        self.assertGreater(windows_imaging.estimate_wim_size(100_000_000_000), 0)


if __name__ == "__main__":
    unittest.main()
