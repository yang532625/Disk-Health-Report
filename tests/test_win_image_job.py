import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from unittest import mock

import win_image_job


class TestWinImageJob(unittest.TestCase):
    def test_create_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(win_image_job, "jobs_root", return_value=tmp):
                job = win_image_job.create_job()
                loaded = win_image_job.load_job(job["id"])
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["stage"], "inventory")

    def test_set_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(win_image_job, "jobs_root", return_value=tmp):
                job = win_image_job.create_job()
                win_image_job.set_stage(job, "iso_done")
                loaded = win_image_job.load_job(job["id"])
            self.assertEqual(loaded["stage"], "iso_done")


if __name__ == "__main__":
    unittest.main()
