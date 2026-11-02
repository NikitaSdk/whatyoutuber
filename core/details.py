"""Дата, описание и возрастное ограничение одного видео. Само видео не скачивается."""

from core.ytdlp_opts import extract


def _availability(info: dict) -> str:
    age = info.get("age_limit") or 0
    avail = str(info.get("availability") or "public").lower()
    if avail in {"private", "needs_auth"}:
        return "unavailable"
    if avail in {"subscriber_only", "premium_only"} or "members" in avail:
        return "members"
    try:
        if int(age) >= 18:
            return "18+"
    except (TypeError, ValueError):
        pass
    return "public"


def _from_error(exc: Exception) -> dict | None:
    from core.errors import diagnose
    kind, _text = diagnose(exc)
    if kind == "members":
        return {"availability": "members", "details_loaded": True}
    if kind == "need_login":
        return {"availability": "18+", "details_loaded": True}
    if kind == "unavailable":
        return {"availability": "unavailable", "details_loaded": True}
    return None


def parse_details(info: dict) -> dict:
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    original = [key for key in auto if str(key).endswith("-orig")]
    langs = list(subs.keys()) or original
    return {
        "title": (info.get("title") or "").strip(),
        "description": info.get("description") or "",
        "tags": list(info.get("tags") or []),
        "upload_date": info.get("upload_date") or "",
        "duration_sec": float(info.get("duration") or 0),
        "availability": _availability(info),
        "has_subtitles": bool(subs or original),
        "subtitle_langs": langs[:12],
        "details_loaded": True,
    }


def load_one(video_id: str, auth: dict) -> dict:
    try:
        info = extract(f"https://www.youtube.com/watch?v={video_id}", auth, flat=False)
    except Exception as exc:
        failed = _from_error(exc)
        if failed:
            return failed
        raise
    if not info:
        return {"availability": "unavailable", "details_loaded": True}
    return parse_details(info)
