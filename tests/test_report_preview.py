import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
import tkinter as tk
import unittest
from unittest import mock

from report_preview import ReportPreviewFrame


class TestReportPreviewWheel(unittest.TestCase):
    def _make_frame_stub(self):
        frame = ReportPreviewFrame.__new__(ReportPreviewFrame)
        frame._canvas = mock.MagicMock()
        frame._pages_host = mock.MagicMock()
        frame._wheel_handlers = {
            "<MouseWheel>": frame._on_wheel if hasattr(frame, "_on_wheel") else mock.Mock(),
        }
        return frame

    def test_install_uses_bind_class_not_bind_all(self):
        frame = ReportPreviewFrame.__new__(ReportPreviewFrame)
        frame._canvas = mock.MagicMock()
        frame._pages_host = mock.MagicMock()
        frame._tag_wheel_widgets = mock.MagicMock()
        frame._on_wheel = mock.Mock()
        frame._on_shift_wheel = mock.Mock()
        frame._on_ctrl_wheel = mock.Mock()
        frame._install_wheel_bindings()
        frame._canvas.bind_all.assert_not_called()
        self.assertEqual(frame._canvas.bind_class.call_count, 3)
        self.assertEqual(frame._tag_wheel_widgets.call_count, 2)

    def test_tag_wheel_widgets_adds_custom_tag(self):
        root = tk.Tk()
        root.withdraw()
        try:
            canvas = tk.Canvas(root)
            host = tk.Frame(canvas)
            frame = ReportPreviewFrame.__new__(ReportPreviewFrame)
            frame._WHEEL_TAG = ReportPreviewFrame._WHEEL_TAG
            frame._tag_wheel_widgets(host)
            self.assertIn(ReportPreviewFrame._WHEEL_TAG, host.bindtags())
        finally:
            root.destroy()

    def test_unbind_wheel_clears_bind_class(self):
        frame = self._make_frame_stub()
        frame._WHEEL_SEQS = ReportPreviewFrame._WHEEL_SEQS
        frame._unbind_wheel()
        self.assertEqual(frame._canvas.bind_class.call_count, 3)


if __name__ == "__main__":
    unittest.main()
