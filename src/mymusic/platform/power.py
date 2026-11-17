"""Реакция на сон/пробуждение Windows через WM_POWERBROADCAST."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012


class PowerEventFilter(QAbstractNativeEventFilter):
    def __init__(self, on_suspend=None, on_resume=None):
        super().__init__()
        self.on_suspend = on_suspend
        self.on_resume = on_resume

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        try:
            event_name = bytes(eventType)
        except (TypeError, ValueError):
            return False, 0
        if event_name not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if msg.message == WM_POWERBROADCAST:
            if msg.wParam == PBT_APMSUSPEND and self.on_suspend:
                self.on_suspend()
            elif msg.wParam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND) and self.on_resume:
                self.on_resume()
        return False, 0


def install(app, on_suspend, on_resume) -> PowerEventFilter:
    event_filter = PowerEventFilter(on_suspend, on_resume)
    app.installNativeEventFilter(event_filter)
    return event_filter
