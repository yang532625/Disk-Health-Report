import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import os
import tempfile
import threading
import unittest
from unittest import mock

import windows_activation


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


class TestEnsureMasScript(unittest.TestCase):
    def test_copies_bundled_to_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled = os.path.join(tmp, "bundle.cmd")
            with open(bundled, "w", encoding="utf-8") as f:
                f.write("@echo off\n")
            cache_dir = os.path.join(tmp, "cache", "mas")
            dest = os.path.join(cache_dir, "MAS_AIO.cmd")
            with mock.patch.object(windows_activation.bundled_assets, "mas_script_path",
                                   return_value=bundled), \
                 mock.patch.object(windows_activation, "_mas_cache_dir",
                                   return_value=cache_dir):
                path = windows_activation.ensure_mas_script()
            self.assertEqual(path, dest)
            self.assertTrue(os.path.isfile(dest))

    def test_returns_none_without_bundle(self):
        with mock.patch.object(windows_activation.bundled_assets, "mas_script_path",
                               return_value=None):
            self.assertIsNone(windows_activation.ensure_mas_script())


class TestHiddenKwargs(unittest.TestCase):
    def test_no_stdin_devnull(self):
        kw = windows_activation._hidden_kwargs()
        self.assertNotIn("stdin", kw)


class TestOutputErrorDetection(unittest.TestCase):
    def test_error_marker_fails_despite_rc_zero(self):
        lines = ["==== ERROR ====\n", "launched from the temp folder\n"]
        with mock.patch.object(windows_activation, "ensure_mas_script",
                               return_value=r"C:\\mas\\MAS_AIO.cmd"), \
             mock.patch.object(windows_activation.subprocess, "Popen",
                               return_value=_FakeProc(lines, returncode=0)):
            ok, err = windows_activation.run_mas_action(["/HWID"], lambda s: None)
        self.assertFalse(ok)
        self.assertEqual(err, "activation_failed")

    def test_input_redirection_marker_fails(self):
        lines = ["ERROR: Input redirection is not supported, exiting the process immediately.\n"]
        with mock.patch.object(windows_activation, "ensure_mas_script",
                               return_value=r"C:\\mas\\MAS_AIO.cmd"), \
             mock.patch.object(windows_activation.subprocess, "Popen",
                               return_value=_FakeProc(lines, returncode=0)):
            ok, err = windows_activation.run_mas_action(["/HWID"], lambda s: None)
        self.assertFalse(ok)


class TestLaunchMas(unittest.TestCase):
    def test_online_when_internet(self):
        with mock.patch.object(windows_activation, "_has_internet", return_value=True), \
             mock.patch.object(windows_activation.subprocess, "Popen") as popen:
            ok, mode = windows_activation.launch_mas()
        self.assertTrue(ok)
        self.assertEqual(mode, "online")
        args, kwargs = popen.call_args
        self.assertEqual(args[0][0], "powershell")
        self.assertIn("irm https://get.activated.win | iex", args[0][-1])
        self.assertEqual(kwargs.get("creationflags"),
                         windows_activation._new_console_flag())

    def test_offline_fallback_no_internet(self):
        with mock.patch.object(windows_activation, "_has_internet", return_value=False), \
             mock.patch.object(windows_activation, "ensure_mas_script",
                               return_value=r"C:\\mas\\MAS_AIO.cmd"), \
             mock.patch.object(windows_activation.subprocess, "Popen") as popen:
            ok, mode = windows_activation.launch_mas()
        self.assertTrue(ok)
        self.assertEqual(mode, "offline")
        args, _ = popen.call_args
        self.assertEqual(args[0][0], "cmd")
        self.assertEqual(args[0][-1], r"C:\\mas\\MAS_AIO.cmd")

    def test_no_internet_no_bundle(self):
        with mock.patch.object(windows_activation, "_has_internet", return_value=False), \
             mock.patch.object(windows_activation, "ensure_mas_script", return_value=None):
            ok, info = windows_activation.launch_mas()
        self.assertFalse(ok)
        self.assertEqual(info, "activation_no_internet")

    def test_online_failure_falls_back_to_offline(self):
        def popen_side_effect(args, **kwargs):
            if args and args[0] == "powershell":
                raise OSError("boom")
            return mock.MagicMock()

        with mock.patch.object(windows_activation, "_has_internet", return_value=True), \
             mock.patch.object(windows_activation, "ensure_mas_script",
                               return_value=r"C:\\mas\\MAS_AIO.cmd"), \
             mock.patch.object(windows_activation.subprocess, "Popen",
                               side_effect=popen_side_effect):
            ok, mode = windows_activation.launch_mas()
        self.assertTrue(ok)
        self.assertEqual(mode, "offline")

    def test_offline_failure_returns_error(self):
        with mock.patch.object(windows_activation, "_has_internet", return_value=False), \
             mock.patch.object(windows_activation, "ensure_mas_script",
                               return_value=r"C:\\mas\\MAS_AIO.cmd"), \
             mock.patch.object(windows_activation.subprocess, "Popen",
                               side_effect=OSError("nope")):
            ok, info = windows_activation.launch_mas()
        self.assertFalse(ok)
        self.assertEqual(info, "activation_failed")


class TestClean(unittest.TestCase):
    def test_strips_ansi_and_cr(self):
        raw = "\x1b[32mHello\x1b[0m world\r\n"
        self.assertEqual(windows_activation._clean(raw), "Hello world")

    def test_plain_passthrough(self):
        self.assertEqual(windows_activation._clean("plain text\n"), "plain text")


class TestRunMasAction(unittest.TestCase):
    def test_uses_bundled_and_streams(self):
        lines = ["line one\n", "\x1b[31mline two\x1b[0m\n"]
        collected = []
        with mock.patch.object(windows_activation, "ensure_mas_script",
                               return_value=r"C:\\mas\\MAS_AIO.cmd"), \
             mock.patch.object(windows_activation.subprocess, "Popen",
                               return_value=_FakeProc(lines, returncode=0)) as popen:
            ok, err = windows_activation.run_mas_action(
                ["/HWID"], collected.append)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(collected, ["line one", "line two"])
        args, kwargs = popen.call_args
        self.assertEqual(args[0][:2], ["cmd", "/c"])
        self.assertEqual(args[0][-1], "/HWID")
        self.assertEqual(kwargs.get("cwd"), r"C:\\mas")

    def test_nonzero_returncode_fails(self):
        with mock.patch.object(windows_activation, "ensure_mas_script",
                               return_value=r"C:\\mas\\MAS_AIO.cmd"), \
             mock.patch.object(windows_activation.subprocess, "Popen",
                               return_value=_FakeProc(["x\n"], returncode=1)):
            ok, err = windows_activation.run_mas_action(["/HWID"], lambda s: None)
        self.assertFalse(ok)
        self.assertEqual(err, "activation_failed")

    def test_online_fallback_when_no_bundle(self):
        with mock.patch.object(windows_activation, "ensure_mas_script", return_value=None), \
             mock.patch.object(windows_activation, "_has_internet", return_value=True), \
             mock.patch.object(windows_activation.subprocess, "Popen",
                               return_value=_FakeProc(["ok\n"], returncode=0)) as popen:
            ok, err = windows_activation.run_mas_action(["/Ohook"], lambda s: None)
        self.assertTrue(ok)
        args, _ = popen.call_args
        self.assertEqual(args[0][0], "powershell")
        self.assertIn("/Ohook", args[0][-1])
        self.assertIn("irm https://get.activated.win", args[0][-1])

    def test_no_bundle_no_internet(self):
        with mock.patch.object(windows_activation, "ensure_mas_script", return_value=None), \
             mock.patch.object(windows_activation, "_has_internet", return_value=False):
            ok, err = windows_activation.run_mas_action(["/HWID"], lambda s: None)
        self.assertFalse(ok)
        self.assertEqual(err, "activation_no_internet")

    def test_cancel_stops_stream(self):
        cancel = threading.Event()
        cancel.set()
        collected = []
        with mock.patch.object(windows_activation, "ensure_mas_script",
                               return_value=r"C:\\mas\\MAS_AIO.cmd"), \
             mock.patch.object(windows_activation.subprocess, "Popen",
                               return_value=_FakeProc(["a\n", "b\n"], returncode=0)):
            ok, err = windows_activation.run_mas_action(
                ["/HWID"], collected.append, cancel)
        self.assertFalse(ok)
        self.assertEqual(err, "activation_cancelled")
        self.assertEqual(collected, [])


class TestRunStatus(unittest.TestCase):
    def test_runs_slmgr(self):
        with mock.patch.object(windows_activation.subprocess, "Popen",
                               return_value=_FakeProc(["status\n"], returncode=0)) as popen:
            ok, err = windows_activation.run_status(lambda s: None)
        self.assertTrue(ok)
        args, _ = popen.call_args
        self.assertEqual(args[0][0], "cscript")
        self.assertIn("slmgr.vbs", args[0][-2])
        self.assertEqual(args[0][-1], "/xpr")


class TestHasInternet(unittest.TestCase):
    def test_true_when_connect_ok(self):
        with mock.patch.object(windows_activation.socket, "create_connection") as cc:
            cc.return_value.__enter__.return_value = mock.MagicMock()
            self.assertTrue(windows_activation._has_internet())

    def test_false_when_all_fail(self):
        with mock.patch.object(windows_activation.socket, "create_connection",
                               side_effect=OSError("no net")):
            self.assertFalse(windows_activation._has_internet())


if __name__ == "__main__":
    unittest.main()
