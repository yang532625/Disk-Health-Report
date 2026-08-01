import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import unittest
from unittest import mock

import win_time


class TestGeocode(unittest.TestCase):
    def test_geocode_success(self):
        payload = {
            "results": [
                {
                    "name": "Miami",
                    "admin1": "Florida",
                    "country": "United States",
                    "timezone": "America/New_York",
                }
            ]
        }
        with mock.patch.object(win_time, "_http_get_json", return_value=payload):
            res = win_time.geocode_location("Miami")
        self.assertIsNotNone(res)
        display, tz = res
        self.assertEqual(tz, "America/New_York")
        self.assertIn("Miami", display)
        self.assertIn("Florida", display)
        self.assertIn("United States", display)

    def test_geocode_no_results(self):
        with mock.patch.object(win_time, "_http_get_json", return_value={"results": []}):
            self.assertIsNone(win_time.geocode_location("zzzzzz"))

    def test_geocode_empty_name(self):
        self.assertIsNone(win_time.geocode_location("  "))

    def test_geocode_missing_timezone(self):
        payload = {"results": [{"name": "X"}]}
        with mock.patch.object(win_time, "_http_get_json", return_value=payload):
            self.assertIsNone(win_time.geocode_location("X"))


class TestFetchZone(unittest.TestCase):
    def test_timeapi_primary(self):
        payload = {
            "year": 2026,
            "month": 6,
            "day": 25,
            "hour": 14,
            "minute": 16,
            "seconds": 30,
        }
        with mock.patch.object(win_time, "_http_get_json", return_value=payload):
            comps = win_time.fetch_zone_now("America/New_York")
        self.assertEqual(comps, (2026, 6, 25, 14, 16, 30))

    def test_fallback_worldtimeapi(self):
        def side_effect(url):
            if "timeapi.io" in url:
                raise OSError("boom")
            return {"datetime": "2026-06-25T14:16:30.123456-04:00"}

        with mock.patch.object(win_time, "_http_get_json", side_effect=side_effect):
            comps = win_time.fetch_zone_now("America/New_York")
        self.assertEqual(comps, (2026, 6, 25, 14, 16, 30))

    def test_both_fail(self):
        with mock.patch.object(win_time, "_http_get_json", side_effect=OSError("no net")):
            self.assertIsNone(win_time.fetch_zone_now("America/New_York"))


class TestParseIso(unittest.TestCase):
    def test_parse_with_offset(self):
        self.assertEqual(
            win_time._parse_iso_components("2026-06-25T14:16:30+02:00"),
            (2026, 6, 25, 14, 16, 30),
        )

    def test_parse_with_z(self):
        self.assertEqual(
            win_time._parse_iso_components("2026-01-02T03:04:05Z"),
            (2026, 1, 2, 3, 4, 5),
        )

    def test_parse_invalid(self):
        self.assertIsNone(win_time._parse_iso_components("not-a-date"))


class TestSetTimeForLocation(unittest.TestCase):
    def test_invalid_empty(self):
        ok, info = win_time.set_time_for_location("")
        self.assertFalse(ok)
        self.assertEqual(info, "set_time_invalid")

    def test_not_found(self):
        with mock.patch.object(win_time, "geocode_location", return_value=None):
            ok, info = win_time.set_time_for_location("nowhere")
        self.assertFalse(ok)
        self.assertEqual(info, "set_time_not_found")

    def test_no_internet_on_geocode(self):
        with mock.patch.object(win_time, "geocode_location", side_effect=OSError("x")):
            ok, info = win_time.set_time_for_location("Miami")
        self.assertFalse(ok)
        self.assertEqual(info, "set_time_no_internet")

    def test_no_time(self):
        with mock.patch.object(
            win_time, "geocode_location", return_value=("Miami", "America/New_York")
        ), mock.patch.object(win_time, "fetch_zone_now", return_value=None):
            ok, info = win_time.set_time_for_location("Miami")
        self.assertFalse(ok)
        self.assertEqual(info, "set_time_no_internet")

    def test_set_failed(self):
        with mock.patch.object(
            win_time, "geocode_location", return_value=("Miami", "America/New_York")
        ), mock.patch.object(
            win_time, "fetch_zone_now", return_value=(2026, 6, 25, 14, 16, 30)
        ), mock.patch.object(win_time, "set_system_local_time", return_value=False):
            ok, info = win_time.set_time_for_location("Miami")
        self.assertFalse(ok)
        self.assertEqual(info, "set_time_failed")

    def test_success(self):
        with mock.patch.object(
            win_time, "geocode_location", return_value=("Miami, Florida, United States", "America/New_York")
        ), mock.patch.object(
            win_time, "fetch_zone_now", return_value=(2026, 6, 25, 14, 16, 30)
        ), mock.patch.object(win_time, "set_system_local_time", return_value=True):
            ok, info = win_time.set_time_for_location("Miami")
        self.assertTrue(ok)
        self.assertIn("Miami", info)
        self.assertIn("2:16 PM", info)


if __name__ == "__main__":
    unittest.main()
