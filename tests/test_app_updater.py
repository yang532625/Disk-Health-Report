import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Pruebas del helper de actualización silenciosa."""

import os
import tempfile
import unittest
from unittest.mock import patch

from app_updater import schedule_silent_update


class TestSilentUpdateHelper(unittest.TestCase):
    def test_helper_waits_only_for_setup_process(self):
        with tempfile.TemporaryDirectory() as temp:
            setup = os.path.join(temp, "Setup.exe")
            with open(setup, "wb") as fh:
                fh.write(b"MZ")

            with (
                patch("app_updater.tempfile.gettempdir", return_value=temp),
                patch(
                    "ctypes.windll.shell32.ShellExecuteW",
                    return_value=33,
                ) as shell_execute,
            ):
                schedule_silent_update(setup, install_dir=temp)

            scripts = [
                os.path.join(temp, name)
                for name in os.listdir(temp)
                if name.endswith(".ps1")
            ]
            self.assertEqual(len(scripts), 1)
            with open(scripts[0], encoding="utf-8") as fh:
                script = fh.read()
            self.assertIn("$p.WaitForExit()", script)
            self.assertNotIn("-PassThru -Wait", script)
            shell_execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
