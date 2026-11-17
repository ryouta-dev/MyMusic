"""Общие небольшие виджеты интерфейса."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


def format_ms(ms: int | None) -> str:
    if ms is None or ms < 0:
        return "--:--"
    seconds = int(ms // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


class ElidedLabel(QLabel):
    """QLabel с обрезкой по ширине и полным текстом в подсказке."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elide()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        width = max(20, self.width() - 4)
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, width)
        super().setText(elided)
