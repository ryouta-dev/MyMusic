"""Вспомогательные функции ожидания событий Qt для тестов и замеров."""
from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication, QEvent


def _process_app_events(app) -> None:
    app.processEvents()
    # Без этого удалённые через deleteLater объекты копятся, пока не вернёмся
    # в основной цикл: в обычной работе приложения их удаляет цикл событий.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def pump_events(app, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _process_app_events(app)
        time.sleep(0.01)


def wait_until(app, predicate, timeout_s: float, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _process_app_events(app)
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(interval)
    _process_app_events(app)
    try:
        return bool(predicate())
    except Exception:
        return False
