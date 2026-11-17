"""settings.json: значения по умолчанию, восстановление после повреждения, атомарная запись."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mymusic.storage.settings import DEFAULTS, Settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="mymusic-settings-")
        self.path = Path(self._temp.name) / "settings.json"

    def tearDown(self):
        self._temp.cleanup()

    def test_defaults_when_file_missing(self):
        settings = Settings(self.path)
        self.assertFalse(self.path.exists())
        self.assertFalse(settings.repaired)
        for key, value in DEFAULTS.items():
            self.assertEqual(settings.get(key), value)
        self.assertFalse(settings.get("autostart"))
        self.assertFalse(settings.get("widget_topmost"))

    def test_save_and_reload(self):
        settings = Settings(self.path)
        settings.set("volume", 0.42)
        settings.set("theme", "dark")
        settings.set("widget_visible", True)
        settings.set("widget_position", [120, 340])
        settings.save()

        reloaded = Settings(self.path)
        self.assertFalse(reloaded.repaired)
        self.assertAlmostEqual(reloaded.get("volume"), 0.42)
        self.assertEqual(reloaded.get("theme"), "dark")
        self.assertTrue(reloaded.get("widget_visible"))
        self.assertEqual(reloaded.get("widget_position"), [120, 340])
        self.assertFalse(self.path.with_name("settings.json.tmp").exists())

    def test_corrupted_file_is_backed_up_and_defaults_used(self):
        self.path.write_text("{ broken json", encoding="utf-8")
        settings = Settings(self.path)
        self.assertTrue(settings.repaired)
        self.assertEqual(settings.get("volume"), DEFAULTS["volume"])
        backups = list(self.path.parent.glob("settings.corrupt-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{ broken json")

    def test_non_object_json_is_treated_as_corrupt(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        settings = Settings(self.path)
        self.assertTrue(settings.repaired)
        self.assertEqual(settings.get("theme"), "system")

    def test_invalid_values_are_sanitised(self):
        self.path.write_text(json.dumps({
            "volume": 7,
            "theme": "neon",
            "widget_position": "left",
            "widget_visible": 1,
            "autostart": 0,
            "unknown": "ignored",
        }), encoding="utf-8")
        settings = Settings(self.path)
        self.assertEqual(settings.get("volume"), 1.0)
        self.assertEqual(settings.get("theme"), "system")
        self.assertIsNone(settings.get("widget_position"))
        self.assertIs(settings.get("widget_visible"), True)
        self.assertIs(settings.get("autostart"), False)

    def test_negative_and_nan_volume(self):
        settings = Settings(self.path)
        settings.set("volume", -3)
        self.assertEqual(settings.get("volume"), 0.0)
        settings.set("volume", "not-a-number")
        self.assertEqual(settings.get("volume"), DEFAULTS["volume"])

    def test_unknown_key_rejected(self):
        settings = Settings(self.path)
        with self.assertRaises(KeyError):
            settings.set("secret_token", "x")

    def test_autostart_off_by_default(self):
        settings = Settings(self.path)
        self.assertFalse(settings.get("autostart"))


if __name__ == "__main__":
    unittest.main()
