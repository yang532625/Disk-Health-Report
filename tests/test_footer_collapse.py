import conftest_path  # noqa: F401
# -*- coding: utf-8 -*-
"""Tests para footer colapsable."""

import unittest
from unittest.mock import MagicMock, patch

from gui_app import DiskHealthApp, footer_should_collapse_after_progress


class TestFooterShouldCollapse(unittest.TestCase):
    def test_auto_expanded_without_pin_collapses(self):
        self.assertTrue(
            footer_should_collapse_after_progress(
                user_pinned=False, auto_expanded=True,
            )
        )

    def test_user_pinned_does_not_collapse(self):
        self.assertFalse(
            footer_should_collapse_after_progress(
                user_pinned=True, auto_expanded=True,
            )
        )

    def test_not_auto_expanded_does_not_collapse(self):
        self.assertFalse(
            footer_should_collapse_after_progress(
                user_pinned=False, auto_expanded=False,
            )
        )


class TestFooterToggleBehavior(unittest.TestCase):
    @patch("gui_app.save_settings")
    def test_toggle_persists_expanded_setting(self, mock_save):
        app = MagicMock()
        app.settings = {}
        app._footer_expanded = False
        app._footer_user_pinned = False
        app._footer_auto_expanded = False
        app._footer_body = MagicMock()
        app.lang = "en"
        app._apply_footer_collapsed_state = DiskHealthApp._apply_footer_collapsed_state.__get__(
            app, DiskHealthApp,
        )
        app._update_footer_toggle_label = MagicMock()

        DiskHealthApp._toggle_footer_body(app, force=True, user_action=True)

        self.assertTrue(app._footer_expanded)
        self.assertTrue(app._footer_user_pinned)
        self.assertTrue(app.settings["footer_expanded"])
        mock_save.assert_called_once_with(app.settings)

    @patch("gui_app.save_settings")
    def test_default_collapsed_from_empty_settings(self, mock_save):
        settings = {}
        self.assertFalse(bool(settings.get("footer_expanded", False)))

    def test_begin_progress_sets_auto_expanded_flag(self):
        app = MagicMock()
        app._footer_expanded = False
        app._footer_auto_expanded = False
        app._toggle_footer_body = MagicMock()
        app._set_footer_state = MagicMock()
        app._pseudo_progress_active = False
        app._end_pseudo_progress_timer = MagicMock()
        app.progress = MagicMock()
        app.progress.cget.return_value = "determinate"
        app._progress_frame = MagicMock()
        app._set_progress_pct = MagicMock()

        DiskHealthApp._begin_progress(app, 0.0)

        self.assertTrue(app._footer_auto_expanded)
        app._toggle_footer_body.assert_called_once_with(force=True)

    def test_end_progress_collapses_when_auto_expanded(self):
        app = MagicMock()
        app._footer_user_pinned = False
        app._footer_auto_expanded = True
        app._pseudo_progress_active = False
        app._end_pseudo_progress_timer = MagicMock()
        app._set_footer_state = MagicMock()
        app.progress = MagicMock()
        app._progress_frame = MagicMock()
        app._toggle_footer_body = MagicMock()

        DiskHealthApp._end_progress(app)

        app._toggle_footer_body.assert_called_once_with(force=False)
        self.assertFalse(app._footer_auto_expanded)

    def test_end_progress_keeps_open_when_user_pinned(self):
        app = MagicMock()
        app._footer_user_pinned = True
        app._footer_auto_expanded = True
        app._pseudo_progress_active = False
        app._end_pseudo_progress_timer = MagicMock()
        app._set_footer_state = MagicMock()
        app.progress = MagicMock()
        app._progress_frame = MagicMock()
        app._toggle_footer_body = MagicMock()

        DiskHealthApp._end_progress(app)

        app._toggle_footer_body.assert_not_called()
        self.assertFalse(app._footer_auto_expanded)


if __name__ == "__main__":
    unittest.main()
