"""Короткие форматы дат и длительности для таблицы и файлов."""

import re
from datetime import datetime


def fold(text: str) -> str:
    return (text or "").replace("Ё", "Е").replace("ё", "е").lower()


def fmt_clock(seconds) -> str:
    seconds = int(max(0, seconds or 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def fmt_hm(seconds) -> str:
    minutes_total = int(max(0, seconds or 0)) // 60
    hours, minutes = divmod(minutes_total, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


def fmt_eta(seconds) -> str:
    seconds = int(max(0, seconds or 0))
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин"
    return "меньше минуты"


def fmt_date(yyyymmdd: str) -> str:
    if not yyyymmdd or len(yyyymmdd) < 8 or not yyyymmdd[:8].isdigit():
        return ""
    return f"{yyyymmdd[6:8]}.{yyyymmdd[4:6]}.{yyyymmdd[0:4]}"


def date_key(yyyymmdd: str) -> str:
    if yyyymmdd and len(yyyymmdd) >= 8 and yyyymmdd[:8].isdigit():
        return yyyymmdd[:8]
    return ""


def fmt_scanned(iso_text: str, now: datetime | None = None) -> str:
    if not iso_text:
        return ""
    try:
        moment = datetime.fromisoformat(iso_text)
    except ValueError:
        return iso_text
    now = now or datetime.now()
    clock = moment.strftime("%H:%M")
    if moment.date() == now.date():
        return f"сегодня в {clock}"
    return f"{moment.strftime('%d.%m.%Y')} в {clock}"


def plural(count: int, one: str, few: str, many: str) -> str:
    number = abs(int(count))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def counted(count: int, one: str, few: str, many: str) -> str:
    return f"{count} {plural(count, one, few, many)}"


def initials(title: str) -> str:
    parts = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", title or "")
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()
