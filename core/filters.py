"""Фильтры таблицы. Смотрят только на уже скачанные сведения о видео."""

from datetime import datetime

from core.fmt import date_key, fold


DURATIONS = [
    ("Любая длительность", None),
    ("до 4 мин", (0, 4 * 60)),
    ("4–20 мин", (4 * 60, 20 * 60)),
    ("20–60 мин", (20 * 60, 60 * 60)),
    ("длиннее часа", (60 * 60, 10 ** 9)),
]

PERIODS = [
    ("Любой период", None),
    ("7 дней", 7),
    ("30 дней", 30),
    ("год", 365),
    ("старше года", "older"),
]


def split_words(text: str) -> list:
    return [fold(part) for part in (text or "").split(",") if part.strip()]


def _haystack(video, subtitle_text: str = "") -> str:
    tags = " ".join(video.tags or [])
    return fold(f"{video.title}\n{video.description}\n{tags}\n{subtitle_text}")


def matches(video, search: str, exclude: str, duration, period, subtitle_text: str = "", now: datetime | None = None) -> bool:
    haystack = _haystack(video, subtitle_text)
    words = split_words(search)
    if words and not any(word in haystack for word in words):
        return False
    banned = split_words(exclude)
    if banned and any(word in haystack for word in banned):
        return False
    if duration:
        low, high = duration
        length = float(video.duration_sec or 0)
        if length > 0 and not (low <= length < high):
            return False
    if period and date_key(video.upload_date):
        now = now or datetime.now()
        uploaded = datetime.strptime(date_key(video.upload_date), "%Y%m%d")
        age_days = (now.date() - uploaded.date()).days
        if period == "older":
            if age_days < 365:
                return False
        elif age_days > int(period) or age_days < 0:
            return False
    return True


def period_label(ids, videos) -> str:
    total = len(ids)
    if not total:
        return ""
    loaded = sum(1 for video_id in ids if videos.get(video_id) and videos[video_id].details_loaded)
    if loaded < total:
        return f"даты загружаются: {loaded} из {total}"
    return ""


def visible_ids(ids, videos, search, exclude, duration, period, subtitles=None, now=None) -> list:
    subtitles = subtitles or {}
    result = []
    for video_id in ids:
        video = videos.get(video_id)
        if video is None:
            continue
        extra = ""
        if search.strip():
            extra = subtitles.get(video_id) or ""
        if matches(video, search, exclude, duration, period, extra, now):
            result.append(video_id)
    return result
