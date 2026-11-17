"""Иконки рисуются кодом — без внешних ассетов и лишних файлов в сборке."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def icon(name: str, color: str = "#e8e8ee", size: int = 20) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), max(1.4, size / 12))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    s = size
    if name == "play":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPolygonF([
            QPointF(s * 0.32, s * 0.22), QPointF(s * 0.32, s * 0.78),
            QPointF(s * 0.78, s * 0.5)]))
    elif name == "pause":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(s * 0.3, s * 0.24, s * 0.14, s * 0.52), 2, 2)
        painter.drawRoundedRect(QRectF(s * 0.56, s * 0.24, s * 0.14, s * 0.52), 2, 2)
    elif name in ("next", "previous"):
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        direction = 1 if name == "next" else -1
        base = 0.5 - direction * 0.16
        painter.drawPolygon(QPolygonF([
            QPointF(s * base, s * 0.24), QPointF(s * base, s * 0.76),
            QPointF(s * (base + direction * 0.26), s * 0.5)]))
        x = s * (0.7 if direction > 0 else 0.3)
        painter.drawRoundedRect(QRectF(x - s * 0.035, s * 0.24, s * 0.07, s * 0.52), 1.5, 1.5)
    elif name == "close":
        painter.drawLine(QPointF(s * 0.32, s * 0.32), QPointF(s * 0.68, s * 0.68))
        painter.drawLine(QPointF(s * 0.68, s * 0.32), QPointF(s * 0.32, s * 0.68))
    elif name == "add":
        painter.drawLine(QPointF(s * 0.5, s * 0.26), QPointF(s * 0.5, s * 0.74))
        painter.drawLine(QPointF(s * 0.26, s * 0.5), QPointF(s * 0.74, s * 0.5))
    elif name == "remove":
        painter.drawLine(QPointF(s * 0.26, s * 0.5), QPointF(s * 0.74, s * 0.5))
    elif name == "trash":
        painter.drawLine(QPointF(s * 0.3, s * 0.34), QPointF(s * 0.7, s * 0.34))
        painter.drawLine(QPointF(s * 0.4, s * 0.28), QPointF(s * 0.6, s * 0.28))
        painter.drawLine(QPointF(s * 0.36, s * 0.34), QPointF(s * 0.39, s * 0.74))
        painter.drawLine(QPointF(s * 0.64, s * 0.34), QPointF(s * 0.61, s * 0.74))
        painter.drawLine(QPointF(s * 0.39, s * 0.74), QPointF(s * 0.61, s * 0.74))
    elif name == "up":
        painter.drawLine(QPointF(s * 0.3, s * 0.62), QPointF(s * 0.5, s * 0.38))
        painter.drawLine(QPointF(s * 0.5, s * 0.38), QPointF(s * 0.7, s * 0.62))
    elif name == "down":
        painter.drawLine(QPointF(s * 0.3, s * 0.38), QPointF(s * 0.5, s * 0.62))
        painter.drawLine(QPointF(s * 0.5, s * 0.62), QPointF(s * 0.7, s * 0.38))
    elif name == "star":
        path = QPainterPath()
        center = s / 2
        outer = s * 0.28
        inner = outer * 0.46
        points = []
        for i in range(10):
            import math
            angle = -math.pi / 2 + i * math.pi / 5
            radius = outer if i % 2 == 0 else inner
            points.append(QPointF(center + radius * math.cos(angle),
                                  center + radius * math.sin(angle)))
        path.addPolygon(QPolygonF(points))
        path.closeSubpath()
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawPath(path)
    elif name == "star_outline":
        import math
        points = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            radius = s * 0.28 if i % 2 == 0 else s * 0.13
            points.append(QPointF(s / 2 + radius * math.cos(angle),
                                  s / 2 + radius * math.sin(angle)))
        points.append(points[0])
        painter.drawPolyline(QPolygonF(points))
    elif name == "settings":
        painter.drawEllipse(QRectF(s * 0.28, s * 0.28, s * 0.44, s * 0.44))
        painter.drawEllipse(QRectF(s * 0.44, s * 0.44, s * 0.12, s * 0.12))
    elif name == "open":
        painter.drawRect(QRectF(s * 0.28, s * 0.36, s * 0.36, s * 0.36))
        painter.drawLine(QPointF(s * 0.5, s * 0.5), QPointF(s * 0.74, s * 0.26))
        painter.drawLine(QPointF(s * 0.56, s * 0.26), QPointF(s * 0.74, s * 0.26))
        painter.drawLine(QPointF(s * 0.74, s * 0.26), QPointF(s * 0.74, s * 0.44))
    elif name == "music":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(s * 0.18, s * 0.24, s * 0.64, s * 0.64))
        painter.setPen(QPen(QColor("#1b1b1f"), max(1.2, s / 14)))
        painter.drawLine(QPointF(s * 0.42, s * 0.64), QPointF(s * 0.42, s * 0.36))
        painter.drawLine(QPointF(s * 0.42, s * 0.36), QPointF(s * 0.62, s * 0.31))
        painter.drawLine(QPointF(s * 0.62, s * 0.31), QPointF(s * 0.62, s * 0.6))
        painter.setBrush(QColor("#1b1b1f"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(s * 0.34, s * 0.6, s * 0.16, s * 0.12))
        painter.drawEllipse(QRectF(s * 0.54, s * 0.56, s * 0.16, s * 0.12))
    elif name == "volume":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawRect(QRectF(s * 0.2, s * 0.4, s * 0.16, s * 0.2))
        painter.drawPolygon(QPolygonF([
            QPointF(s * 0.36, s * 0.4), QPointF(s * 0.52, s * 0.26),
            QPointF(s * 0.52, s * 0.74), QPointF(s * 0.36, s * 0.6)]))
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(QRectF(s * 0.44, s * 0.32, s * 0.26, s * 0.36), -60 * 16, 120 * 16)
    painter.end()
    return QIcon(pixmap)
