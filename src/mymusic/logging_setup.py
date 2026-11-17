"""Логи с ротацией; URL, токены и поисковые запросы не записываются."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(log_dir: Path, console: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "mymusic.log", maxBytes=1_048_576, backupCount=5, encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    def log_exception(exc_type, exc_value, exc_tb):
        logging.getLogger("mymusic").error(
            "unhandled exception: %s", exc_type.__name__,
            exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = log_exception
