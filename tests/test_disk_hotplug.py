import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Pruebas de reintentos hot-plug y cola de refresco."""

import unittest
from unittest.mock import Mock, patch

from disk_watcher import DiskWatcher, HOTPLUG_RETRY_DELAYS_MS
from gui_app import DiskHealthApp


class FakeRoot:
    def __init__(self):
        self.jobs = []
        self.cancelled = []

    def after(self, delay, callback):
        job = f"job-{len(self.jobs)}"
        self.jobs.append((job, delay, callback))
        return job

    def after_cancel(self, job):
        self.cancelled.append(job)


class TestDiskWatcherRetries(unittest.TestCase):
    def _watcher(self):
        root = FakeRoot()
        with patch("disk_watcher.sys.platform", "linux"):
            watcher = DiskWatcher(root, on_change=Mock())
        root.jobs.clear()  # descarta el sondeo periódico inicial
        return root, watcher

    def test_native_event_schedules_staged_retries(self):
        root, watcher = self._watcher()
        watcher._schedule_hotplug_checks()
        self.assertEqual(
            [delay for _job, delay, _callback in root.jobs],
            list(HOTPLUG_RETRY_DELAYS_MS),
        )

    def test_poll_requested_while_busy_is_not_lost(self):
        _root, watcher = self._watcher()
        watcher._polling = True
        watcher._schedule_poll(force=True)
        self.assertTrue(watcher._poll_pending)

        watcher._schedule_poll = Mock()
        watcher._last_signature = frozenset({"pd:0"})
        watcher._on_poll_done(frozenset({"pd:0"}))
        watcher._schedule_poll.assert_called_once_with(force=True)

    def test_sync_normalizes_windows_and_smartctl_paths(self):
        _root, watcher = self._watcher()
        watcher.sync(frozenset({r"\\.\PhysicalDrive2", "/dev/pd0"}))
        self.assertEqual(watcher._last_signature, frozenset({"pd:0", "pd:2"}))


class FakeDiskApp:
    def __init__(self):
        self._scanning = True
        self._building = False
        self._formatting = False
        self._cleaning_cache = False
        self._rescan_pending = False
        self._rescan_job = None
        self.jobs = []
        self.scans = []

    def after(self, delay, callback):
        self.jobs.append((delay, callback))
        return f"rescan-{len(self.jobs)}"

    def _queue_pending_rescan(self):
        return DiskHealthApp._queue_pending_rescan(self)

    def _try_pending_rescan(self):
        return DiskHealthApp._try_pending_rescan(self)

    def _scan_disks(self, silent=False):
        self.scans.append(silent)


class TestPendingGuiRescan(unittest.TestCase):
    def test_event_during_scan_runs_after_scan_finishes(self):
        app = FakeDiskApp()
        DiskHealthApp._on_devices_changed(app)
        self.assertTrue(app._rescan_pending)
        self.assertEqual(len(app.jobs), 1)
        self.assertEqual(app.scans, [])

        app._scanning = False
        _delay, callback = app.jobs.pop()
        callback()
        self.assertFalse(app._rescan_pending)
        self.assertEqual(app.scans, [True])


if __name__ == "__main__":
    unittest.main()
