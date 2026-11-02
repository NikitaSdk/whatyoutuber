"""WhatYouTuber — канал YouTube в папку с текстами.

Конвертер «Видео → текст» лежит отдельно и этим файлом не меняется.
Его окно по-прежнему открывается своим python main.py.
Отсюда вызывается только его функция расшифровки.
"""

import os
import subprocess
import sys
from pathlib import Path


def ensure_interpreter():
    if os.environ.get("WY_TEST") == "1" or os.environ.get("WY_REEXEC") == "1":
        return
    try:
        import yt_dlp  # noqa: F401
        return
    except ImportError:
        pass
    candidate = Path(__file__).resolve().parent.parent / "MP4-TXT" / ".venv" / "Scripts" / "python.exe"
    if not candidate.is_file():
        return
    if Path(sys.executable).resolve() == candidate.resolve():
        return
    env = os.environ.copy()
    env["WY_REEXEC"] = "1"
    raise SystemExit(subprocess.call([str(candidate), str(Path(__file__).resolve()), *sys.argv[1:]], env=env))


def main():
    ensure_interpreter()
    from core.storage import load_settings
    from ui.app import App

    settings = load_settings()
    App(settings).mainloop()


if __name__ == "__main__":
    main()
