"""Темы и общие стили интерфейса."""
from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#f5f5f7",
    "panel": "#ffffff",
    "panel_alt": "#efeff3",
    "text": "#1b1b1f",
    "muted": "#6a6a73",
    "accent": "#4b5cf0",
    "accent_text": "#ffffff",
    "border": "#d9d9e0",
    "danger": "#b3261e",
    "hover": "#e6e6ee",
    "selection": "#dde0ff",
}

DARK = {
    "bg": "#17171b",
    "panel": "#212126",
    "panel_alt": "#2a2a31",
    "text": "#f2f2f5",
    "muted": "#9a9aa5",
    "accent": "#8b96ff",
    "accent_text": "#101018",
    "border": "#34343d",
    "danger": "#ff8a80",
    "hover": "#303039",
    "selection": "#353a66",
}


def system_theme() -> str:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if value else "dark"
    except OSError:
        return "light"


def resolve_theme(name: str) -> str:
    return system_theme() if name == "system" else name


def palette_for(theme: str) -> dict:
    return LIGHT if theme == "light" else DARK


def apply_theme(app: QApplication, name: str) -> None:
    colors = palette_for(resolve_theme(name))
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(colors["bg"]))
    palette.setColor(QPalette.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.Base, QColor(colors["panel"]))
    palette.setColor(QPalette.AlternateBase, QColor(colors["panel_alt"]))
    palette.setColor(QPalette.Text, QColor(colors["text"]))
    palette.setColor(QPalette.Button, QColor(colors["panel"]))
    palette.setColor(QPalette.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.Highlight, QColor(colors["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor(colors["accent_text"]))
    palette.setColor(QPalette.ToolTipBase, QColor(colors["panel"]))
    palette.setColor(QPalette.ToolTipText, QColor(colors["text"]))
    app.setPalette(palette)
    app.setStyleSheet(_stylesheet(colors))


def _stylesheet(c: dict) -> str:
    return f"""
    * {{ font-family: "Segoe UI"; font-size: 10pt; }}
    QMainWindow, QDialog {{ background: {c['bg']}; }}
    QWidget {{ color: {c['text']}; }}
    QLineEdit {{
        background: {c['panel']}; border: 1px solid {c['border']};
        border-radius: 8px; padding: 7px 10px; selection-background-color: {c['accent']};
    }}
    QLineEdit:focus {{ border: 1px solid {c['accent']}; }}
    QPushButton {{
        background: {c['panel']}; border: 1px solid {c['border']};
        border-radius: 8px; padding: 6px 12px;
    }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton:focus {{ border: 1px solid {c['accent']}; }}
    QPushButton#accent {{ background: {c['accent']}; color: {c['accent_text']}; border: none; }}
    QPushButton#accent:hover {{ background: {c['accent']}; }}
    QPushButton:disabled {{ color: {c['muted']}; }}
    QToolButton {{
        background: transparent; border: 1px solid transparent;
        border-radius: 8px; padding: 4px;
    }}
    QToolButton:hover {{ background: {c['hover']}; }}
    QToolButton:focus {{ border: 1px solid {c['accent']}; }}
    QToolButton#transport {{
        background: {c['panel_alt']}; border: 1px solid {c['border']};
        border-radius: 17px; min-width: 34px; min-height: 34px;
    }}
    QToolButton#transport:hover {{ background: {c['hover']}; }}
    QToolButton#primary {{
        background: {c['accent']}; color: {c['accent_text']}; border: none;
        border-radius: 21px; min-width: 42px; min-height: 42px;
    }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 10px; background: {c['panel']}; }}
    QTabBar::tab {{
        background: transparent; padding: 8px 16px; margin-right: 4px;
        border-radius: 8px; color: {c['muted']};
    }}
    QTabBar::tab:selected {{ background: {c['panel']}; color: {c['text']}; }}
    QTabBar::tab:hover {{ background: {c['hover']}; }}
    QListWidget {{ background: {c['panel']}; border: none; outline: none; }}
    QListWidget::item {{ border-bottom: 1px solid {c['border']}; }}
    QListWidget::item:selected {{ background: {c['selection']}; }}
    QLabel#accentBadge {{
        color: {c['accent']}; font-weight: 600; font-size: 9pt;
        border: 1px solid {c['accent']}; border-radius: 8px; padding: 0 7px;
    }}
    QScrollArea {{ border: none; background: transparent; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {c['accent']}; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
    }}
    QLabel#title {{ font-size: 11pt; font-weight: 600; }}
    QLabel#muted {{ color: {c['muted']}; }}
    QLabel#danger {{ color: {c['danger']}; }}
    QFrame#playerBar {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 12px; }}
    QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; }}
    QMenu::item:selected {{ background: {c['selection']}; }}
    QCheckBox {{ spacing: 8px; }}
    QComboBox {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 5px; }}
    QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; }}
    """
