import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import os
import tempfile
import threading
import unittest
from unittest import mock

import windows_activation
import windows_defender_remover


class _FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self._rc = returncode

    def wait(self):
        return self._rc

    def terminate(self):
        pass

    def kill(self):
        pass


def _write_required_bundle(root: str, *, with_powerrun: bool = True) -> None:
    """Crea todos los archivos que exige _verify_defender_bundle."""
    reg_dir = os.path.join(root, "Remove_Defender")
    sec_dir = os.path.join(root, "Remove_SecurityComp")
    os.makedirs(reg_dir, exist_ok=True)
    os.makedirs(sec_dir, exist_ok=True)
    for path in (
        os.path.join(reg_dir, "DisableAntivirusProtection.reg"),
        os.path.join(sec_dir, "Remove_SecurityComp.reg"),
        os.path.join(root, "RemoveSecHealthApp.ps1"),
        os.path.join(root, "files_removal.bat"),
    ):
        with open(path, "w", encoding="utf-8") as f:
            f.write("Windows Registry Editor Version 5.00\n")
    if with_powerrun:
        with open(os.path.join(root, "PowerRun.exe"), "wb") as f:
            f.write(b"MZ")


class TestVerifyDefenderBundle(unittest.TestCase):
    def test_accepts_complete_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_required_bundle(tmp)
            self.assertTrue(windows_defender_remover._verify_defender_bundle(tmp))

    def test_rejects_missing_powerrun(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_required_bundle(tmp, with_powerrun=False)
            self.assertFalse(windows_defender_remover._verify_defender_bundle(tmp))


class TestEnsureDefenderRemover(unittest.TestCase):
    def test_copies_bundle_tree_to_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled = os.path.join(tmp, "bundle")
            os.makedirs(bundled)
            _write_required_bundle(bundled)
            cache_dir = os.path.join(tmp, "cache", "defender_remover")
            with mock.patch.object(
                windows_defender_remover.bundled_assets,
                "defender_remover_bundle_dir",
                return_value=bundled,
            ), mock.patch.object(
                windows_defender_remover,
                "_defender_cache_dir",
                return_value=cache_dir,
            ):
                path = windows_defender_remover.ensure_defender_remover()
            self.assertEqual(path, cache_dir)
            copied = os.path.join(
                cache_dir, "Remove_Defender", "DisableAntivirusProtection.reg",
            )
            self.assertTrue(os.path.isfile(copied))
            self.assertTrue(os.path.isfile(os.path.join(cache_dir, "PowerRun.exe")))

    def test_returns_none_without_bundle(self):
        with mock.patch.object(
            windows_defender_remover.bundled_assets,
            "defender_remover_bundle_dir",
            return_value=None,
        ):
            self.assertIsNone(windows_defender_remover.ensure_defender_remover())

    def test_returns_none_when_copy_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled = os.path.join(tmp, "bundle")
            os.makedirs(bundled)
            with open(os.path.join(bundled, "PowerRun.exe"), "wb") as f:
                f.write(b"MZ")
            cache_dir = os.path.join(tmp, "cache", "defender_remover")
            with mock.patch.object(
                windows_defender_remover.bundled_assets,
                "defender_remover_bundle_dir",
                return_value=bundled,
            ), mock.patch.object(
                windows_defender_remover,
                "_defender_cache_dir",
                return_value=cache_dir,
            ):
                path = windows_defender_remover.ensure_defender_remover()
            self.assertIsNone(path)


class TestBuildActionSteps(unittest.TestCase):
    def test_full_starts_with_ps1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "defender")
            os.makedirs(os.path.join(root, "Remove_Defender"))
            with open(os.path.join(root, "Remove_Defender", "a.reg"), "w") as f:
                f.write("Windows Registry Editor Version 5.00\n")
            steps = windows_defender_remover._build_action_steps(root)
            self.assertEqual(steps["full"][0], ("ps1", "RemoveSecHealthApp.ps1"))
            self.assertTrue(any(s[0] == "reg" for s in steps["full"]))


class TestRunAction(unittest.TestCase):
    def _make_root(self, tmp, with_powerrun=True):
        root = os.path.join(tmp, "defender")
        _write_required_bundle(root, with_powerrun=with_powerrun)
        with open(os.path.join(root, "Remove_Defender", "engine.reg"), "w", encoding="utf-8") as f:
            f.write("Windows Registry Editor Version 5.00\n")
        return root

    def test_engine_invokes_regedit_s(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            with mock.patch.object(
                windows_defender_remover, "is_admin", return_value=True,
            ), mock.patch.object(
                windows_defender_remover,
                "is_tamper_protection_enabled",
                return_value=False,
            ), mock.patch.object(
                windows_defender_remover,
                "ensure_defender_remover",
                return_value=root,
            ), mock.patch.object(
                windows_activation.subprocess,
                "Popen",
                return_value=_FakeProc([], returncode=0),
            ) as popen:
                ok, err = windows_defender_remover.run_action("engine", lambda s: None)
            self.assertTrue(ok)
            self.assertEqual(err, "")
            args, _ = popen.call_args
            cmd = args[0]
            self.assertNotEqual(cmd[0], "reg")
            flat = " ".join(cmd).lower()
            self.assertIn("regedit", flat)
            self.assertIn("/s", flat)
            self.assertTrue(cmd[-1].endswith("engine.reg"))

    def test_not_admin_fails(self):
        with mock.patch.object(
            windows_defender_remover, "is_admin", return_value=False,
        ):
            ok, err = windows_defender_remover.run_action("engine", lambda s: None)
        self.assertFalse(ok)
        self.assertEqual(err, "defender_not_admin")

    def test_tamper_enabled_fails(self):
        with mock.patch.object(
            windows_defender_remover, "is_admin", return_value=True,
        ), mock.patch.object(
            windows_defender_remover,
            "is_tamper_protection_enabled",
            return_value=True,
        ):
            ok, err = windows_defender_remover.run_action("engine", lambda s: None)
        self.assertFalse(ok)
        self.assertEqual(err, "defender_tamper_enabled")

    def test_bundle_missing_fails(self):
        with mock.patch.object(
            windows_defender_remover, "is_admin", return_value=True,
        ), mock.patch.object(
            windows_defender_remover,
            "is_tamper_protection_enabled",
            return_value=False,
        ), mock.patch.object(
            windows_defender_remover,
            "ensure_defender_remover",
            return_value=None,
        ):
            ok, err = windows_defender_remover.run_action("engine", lambda s: None)
        self.assertFalse(ok)
        self.assertEqual(err, "defender_bundle_missing")

    def test_no_powerrun_regedit_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp, with_powerrun=False)
            with mock.patch.object(
                windows_defender_remover, "is_admin", return_value=True,
            ), mock.patch.object(
                windows_defender_remover,
                "is_tamper_protection_enabled",
                return_value=False,
            ), mock.patch.object(
                windows_defender_remover,
                "ensure_defender_remover",
                return_value=root,
            ):
                ok, err = windows_defender_remover.run_action("engine", lambda s: None)
            self.assertFalse(ok)
            self.assertEqual(err, "defender_no_powerrun")

    def test_error_marker_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            lines = ["Error accessing the registry\n"]
            with mock.patch.object(
                windows_defender_remover, "is_admin", return_value=True,
            ), mock.patch.object(
                windows_defender_remover,
                "is_tamper_protection_enabled",
                return_value=False,
            ), mock.patch.object(
                windows_defender_remover,
                "ensure_defender_remover",
                return_value=root,
            ), mock.patch.object(
                windows_activation.subprocess,
                "Popen",
                return_value=_FakeProc(lines, returncode=0),
            ):
                ok, err = windows_defender_remover.run_action("engine", lambda s: None)
            self.assertFalse(ok)
            self.assertEqual(err, "defender_failed")

    def test_cancel_stops_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_root(tmp)
            cancel = threading.Event()
            cancel.set()
            with mock.patch.object(
                windows_defender_remover, "is_admin", return_value=True,
            ), mock.patch.object(
                windows_defender_remover,
                "is_tamper_protection_enabled",
                return_value=False,
            ), mock.patch.object(
                windows_defender_remover,
                "ensure_defender_remover",
                return_value=root,
            ):
                ok, err = windows_defender_remover.run_action(
                    "engine", lambda s: None, cancel)
            self.assertFalse(ok)
            self.assertEqual(err, "defender_cancelled")


class TestHiddenKwargs(unittest.TestCase):
    def test_no_stdin_devnull(self):
        kw = windows_activation._hidden_kwargs()
        self.assertNotIn("stdin", kw)


if __name__ == "__main__":
    unittest.main()
