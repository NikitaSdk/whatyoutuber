"""Понятные формулировки ошибок YouTube и диска.

Вид ошибки определяется по целым фразам исходного текста, а не по обрывкам вроде «age» или «webpage».
"""

import errno
import re


class AppError(Exception):
    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


class Cancelled(AppError):
    def __init__(self, message: str = "Остановлено"):
        super().__init__(message, "cancel")


_RULES = [
    ("disk", r"no space left|not enough space|disk full|errno 28|winerror 112",
     "Кончилось место на диске. Очередь остановлена."),
    ("ratelimit", r"rate.?limit|too many requests|http error 429|content isn.t available, try again later",
     "YouTube ограничил число запросов. Очередь подождёт и продолжит."),
    ("bot", r"not a bot|confirm you.?re not a bot",
     "YouTube просит подтвердить, что запрос не от робота. Настройте вход."),
    ("need_login", r"confirm your age|age.restricted|inappropriate for some users",
     "нужен вход: видео 18+"),
    ("network", r"timed out|connection ?reset|connectionreset|connection (refused|aborted)|getaddrinfo|name resolution"
                r"|winerror 100(54|60)|10054|http error 50[0234]|remote end closed",
     "Нет связи с YouTube. Повторю позже."),
    ("members", r"members.only|join this channel",
     "недоступно: только для спонсоров"),
    ("unavailable", r"private video",
     "недоступно: закрытое видео"),
    ("outdated", r"requested format is not available|no video formats|unable to extract"
                 r"|javascript runtime|n challenge|signature",
     "Похоже, YouTube что-то поменял — нажмите «Обновить yt-dlp»."),
    ("unavailable", r"video unavailable|has been removed|no longer available|account .{0,40}terminated",
     "недоступно: видео удалили или оно не открывается"),
]
_COMPILED = [(kind, re.compile(pattern, re.I), text) for kind, pattern, text in _RULES]


def diagnose(error) -> tuple[str, str]:
    """(вид, понятный текст)."""
    known = getattr(error, "kind", None)
    if known and known not in {"error", "cancel"}:
        return known, str(error)
    if isinstance(error, OSError) and getattr(error, "errno", None) in {errno.ENOSPC, 28, 112}:
        return "disk", _COMPILED[0][2]
    raw = str(error or "").strip()
    for kind, pattern, text in _COMPILED:
        if pattern.search(raw):
            return kind, text
    if not raw:
        return "error", "Не удалось выполнить запрос к YouTube."
    return "error", raw.splitlines()[-1][:400]


def explain(error) -> str:
    return diagnose(error)[1]


def classify_failure(error) -> str:
    return diagnose(error)[0]
