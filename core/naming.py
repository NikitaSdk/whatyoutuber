"""Имена файлов и папок, которые Windows согласится создать."""

import re

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_name(name: str, limit: int = 120) -> str:
    cleaned = _FORBIDDEN.sub(" ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip(". ")
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned = "_" + cleaned
    return cleaned or "видео"


def text_filename(number: int, title: str, upload_date: str, style: str) -> str:
    if style == "date" and upload_date and len(upload_date) >= 8 and upload_date[:8].isdigit():
        prefix = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
    else:
        prefix = f"{int(number):03d}"
    room = max(20, 120 - len(prefix) - 3)
    return f"{prefix} - {safe_name(title, room)}.txt"
