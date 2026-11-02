"""Проверка yt-dlp, Deno, ffmpeg и папки конвертера. Сам конвертер не изменяется."""

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from core.ytdlp_opts import find_deno, find_node


@dataclass
class Component:
    key: str
    title: str
    ok: bool
    detail: str


def check_components(converter_path: str) -> list:
    rows = []
    try:
        import yt_dlp
        version = getattr(getattr(yt_dlp, "version", None), "__version__", "") or ""
        rows.append(Component("yt_dlp", "yt-dlp", True, version or "установлен"))
    except Exception as exc:
        rows.append(Component("yt_dlp", "yt-dlp", False, f"нет ({exc.__class__.__name__}). Команда: pip install -U \"yt-dlp[default]\""))

    deno = find_deno()
    node = find_node()
    if deno:
        rows.append(Component("deno", "Deno", True, deno))
    elif node:
        rows.append(Component("deno", "Deno", False, f"нет. Найден Node, с ним yt-dlp обычно тоже работает: {node}. Надёжнее поставить Deno: winget install --id=DenoLand.Deno"))
    else:
        rows.append(Component("deno", "Deno", False, "нет. Команда: winget install --id=DenoLand.Deno"))

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        rows.append(Component("ffmpeg", "ffmpeg", True, ffmpeg))
    else:
        rows.append(Component("ffmpeg", "ffmpeg", False, "нет. Команда: winget install Gyan.FFmpeg"))

    try:
        import pymorphy3  # noqa: F401
        rows.append(Component("pymorphy", "поиск по словам", True, "pymorphy3"))
    except Exception:
        rows.append(Component("pymorphy", "поиск по словам", False, "нет pymorphy3. Команда: pip install pymorphy3 pymorphy3-dicts-ru"))

    tesseract = shutil.which("tesseract")
    if tesseract:
        rows.append(Component("tesseract", "текст со слайдов", True, tesseract))
    else:
        rows.append(Component("tesseract", "текст со слайдов", False, "нет программы Tesseract (языки rus и eng). Поиск и расшифровка без неё работают."))

    path = Path(converter_path) if converter_path else None
    if path and path.is_file():
        path = path.parent
    if path and (path / "main.py").is_file():
        rows.append(Component("converter", "конвертер", True, str(path)))
    else:
        rows.append(Component("converter", "конвертер", False, "не найден. Укажите папку проекта «Видео → текст» в настройках."))
    return rows


def missing_banner(rows: list) -> str:
    bad = [row for row in rows if not row.ok and row.key != "tesseract"]
    if not bad:
        return ""
    return " ".join(f"{row.title}: {row.detail}" for row in bad)


def update_ytdlp() -> tuple[int, str]:
    command = [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        return 1, str(exc)
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return proc.returncode, output


def converter_main_exists(path: str) -> bool:
    if not path:
        return False
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    return (folder / "main.py").is_file() and importlib.util.spec_from_file_location is not None
