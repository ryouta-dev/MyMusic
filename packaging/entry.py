"""Точка входа для PyInstaller: пакетный импорт вместо относительного."""
from mymusic.app import main

if __name__ == "__main__":
    raise SystemExit(main())
