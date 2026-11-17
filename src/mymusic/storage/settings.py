"""Настройки в settings.json с атомарной записью и терпимостью к повреждению."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

SCHEMA_VERSION = 1

DEFAULTS: dict = {
    "schema_version": SCHEMA_VERSION,
    "volume": 0.8,
    "widget_visible": False,
    "widget_position": None,
    "widget_topmost": False,
    "theme": "system",
    "selected_provider": "audius",
    "autostart": False,
    "tray_notice_shown": False,
}

VALID_THEMES = {"system", "light", "dark"}


class Settings:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.values = dict(DEFAULTS)
        self.repaired = False
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings must be an object")
        except (ValueError, OSError):
            backup = self.path.with_suffix(f".corrupt-{int(time.time())}.json")
            try:
                shutil.copy2(self.path, backup)
            except OSError:
                pass
            self.repaired = True
            return
        for key, default in DEFAULTS.items():
            if key in data:
                self.values[key] = data[key]
        self._validate()

    def _validate(self) -> None:
        try:
            self.values["volume"] = min(1.0, max(0.0, float(self.values["volume"])))
        except (TypeError, ValueError):
            self.values["volume"] = DEFAULTS["volume"]
        self.values["widget_visible"] = bool(self.values["widget_visible"])
        self.values["widget_topmost"] = bool(self.values["widget_topmost"])
        self.values["autostart"] = bool(self.values["autostart"])
        if self.values["theme"] not in VALID_THEMES:
            self.values["theme"] = DEFAULTS["theme"]
        pos = self.values.get("widget_position")
        if not (isinstance(pos, list) and len(pos) == 2
                and all(isinstance(v, (int, float)) for v in pos)):
            self.values["widget_position"] = None
        self.values["schema_version"] = SCHEMA_VERSION

    def get(self, key: str):
        return self.values.get(key, DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self.values[key] = value
        self._validate()

    def save(self) -> None:
        self.values["schema_version"] = SCHEMA_VERSION
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        data = json.dumps(self.values, ensure_ascii=False, indent=2)
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, self.path)
