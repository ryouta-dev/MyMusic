"""Жизненный цикл приложения: скрытие в трей, виджет, восстановление, полный выход."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mymusic.application.app_controller import ApplicationController
from mymusic.domain.models import PlaybackState
from mymusic.domain.queue import QueueEntry

from .support import make_track


class ApplicationLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="mymusic-lifecycle-")
        self.data_dir = Path(self._temp.name)
        self.controller = ApplicationController(self.app, self.data_dir)

    def tearDown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._shutdown()
            if controller._power_filter is not None:
                self.app.removeNativeEventFilter(controller._power_filter)
        self._temp.cleanup()

    def test_tray_widget_restore_and_full_exit(self):
        controller = self.controller
        self.assertTrue(controller.main_window.isVisible())
        self.assertFalse(controller.widget.isVisible())
        self.assertFalse(controller.settings.get("autostart"))
        self.assertFalse(controller.settings.get("widget_topmost"))

        controller.main_window.close()
        self.assertFalse(controller.main_window.isVisible())
        self.assertEqual(controller.player.state, PlaybackState.IDLE)
        self.assertTrue(controller.settings.get("tray_notice_shown"))
        self.assertTrue((self.data_dir / "settings.json").is_file())
        self.assertFalse(controller._shutdown_done)

        controller.show_main()
        self.assertTrue(controller.main_window.isVisible())

        controller.set_widget_visible(True)
        self.assertTrue(controller.widget.isVisible())
        self.assertTrue(controller.settings.get("widget_visible"))
        controller.widget.close()
        self.assertFalse(controller.widget.isVisible())
        self.assertFalse(controller.settings.get("widget_visible"))
        self.assertTrue(controller.main_window.isVisible())

        controller.save_widget_position(controller.widget.pos())
        self.assertIsInstance(controller.settings.get("widget_position"), list)

    def test_queue_is_restored_paused_after_restart(self):
        controller = self.controller
        entries = [QueueEntry.create(make_track(i)) for i in range(2)]
        controller.player.queue._entries = list(entries)
        controller.player.queue.current_entry_id = entries[1].entry_id
        controller.player._position_ms = 3_300
        controller._shutdown()

        self.assertEqual(controller.player.state, PlaybackState.SHUTTING_DOWN)
        self.assertFalse(controller.main_window.isVisible())
        self.assertFalse(controller.widget.isVisible())
        self.assertFalse(controller.backend.has_source())
        self.assertIsNone(controller.backend.player.audioOutput())
        self.assertFalse(controller.player._ui_timer.isActive())
        self.assertFalse(controller.player._save_timer.isActive())

        restored = ApplicationController(self.app, self.data_dir)
        try:
            self.assertEqual(restored.player.state, PlaybackState.PAUSED)
            self.assertEqual(restored.player.snapshot().position_ms, 3_300)
            self.assertEqual(restored.player.snapshot().track.title, "Трек 1")
            self.assertFalse(restored.backend.has_source())
            restored._shutdown()
        finally:
            if restored._power_filter is not None:
                self.app.removeNativeEventFilter(restored._power_filter)

    def test_twenty_open_hide_cycles(self):
        controller = self.controller
        for _ in range(20):
            controller.main_window.close()
            self.assertFalse(controller.main_window.isVisible())
            controller.show_main()
            self.assertTrue(controller.main_window.isVisible())

            controller.set_widget_visible(True)
            self.assertTrue(controller.widget.isVisible())
            controller.widget.close()
            self.assertFalse(controller.widget.isVisible())
            self.assertTrue(controller.main_window.isVisible())
        self.assertEqual(controller.player.state, PlaybackState.IDLE)
        self.assertFalse(controller._shutdown_done)
        self.assertTrue(controller.settings.get("tray_notice_shown"))

    def test_shutdown_is_idempotent(self):
        controller = self.controller
        controller._shutdown()
        controller._shutdown()
        self.assertEqual(controller.player.state, PlaybackState.SHUTTING_DOWN)


if __name__ == "__main__":
    unittest.main()
