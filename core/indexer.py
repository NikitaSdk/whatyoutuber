"""Фоновый индекс: один запрос к видео даёт детали, субтитры и главы."""

import random
import threading
import time
from pathlib import Path

from core.catalog import watch_url
from core.details import parse_details
from core.errors import diagnose
from core.index_db import IndexDB
from core.subtitles import _pick_format, _pick_track, parse_json3, parse_vtt
from core.ytdlp_opts import client, extract


def to_windows(cues, size=60):
    buckets = {}
    for cue in cues or []:
        start = int(float(cue.get("start") or 0)) // size * size
        text = (cue.get("text") or "").strip()
        if text:
            buckets.setdefault(start, []).append(text)
    return [(start, " ".join(parts), "speech") for start, parts in sorted(buckets.items())]


def _cues(ydl, info) -> tuple[list, str, bool]:
    picked = _pick_track(info or {})
    if not picked:
        return [], "", False
    lang, formats, manual = picked
    url, kind = _pick_format(formats, manual)
    if not url:
        return [], lang, manual
    raw = ydl.urlopen(url).read().decode("utf-8", errors="replace")
    cues = parse_json3(raw) if kind == "json3" else parse_vtt(raw)
    return cues, lang, manual


def index_one(video_id: str, channel_id: str, auth: dict, db: IndexDB, emit, cache_dir=None) -> str:
    info = extract(watch_url(video_id), auth, flat=False) or {}
    if cache_dir is not None:
        from core.storyboard import cache_board
        cache_board(cache_dir, video_id, info)
    fields = parse_details(info)
    emit({"type": "detail", "id": video_id, "fields": fields})
    _key, (ydl, log) = client(auth, False)
    log.errors.clear()
    cues, lang, manual = _cues(ydl, info)
    speech = to_windows(cues)
    chapters = [
        (int(float(chapter.get("start_time") or 0)), chapter.get("title") or "", "chapter")
        for chapter in (info.get("chapters") or [])
        if (chapter.get("title") or "").strip()
    ]
    meta = (info.get("title") or "", info.get("description") or "", " ".join(info.get("tags") or []))
    duration = float(info.get("duration") or fields.get("duration_sec") or 0)
    windows = speech + chapters
    if speech:
        source = "subs_manual" if manual else "subs_auto"
        db.replace_video(video_id, channel_id, duration, windows, meta, source, lang, "indexed")
        return "indexed"
    if chapters:
        db.replace_video(video_id, channel_id, duration, chapters, meta, "", lang, "no_text")
    else:
        db.mark(video_id, channel_id, "no_text", duration=duration, meta=meta)
    return "no_text"


def run_indexer(channel, auth, db_path, priority, emit, stop: threading.Event, pause: threading.Event) -> None:
    db = IndexDB(db_path)
    ids = [video.id for video in channel.videos.values() if video.id and not video.removed_from_channel]
    known = db.statuses(ids)
    skip = {"indexed", "no_text", "unavailable"}
    if (auth or {}).get("mode") in {None, "", "none"}:
        skip.add("need_login")
    pending = [video_id for video_id in ids if known.get(video_id) not in skip]
    queue = list(pending)
    waiting = set(queue)
    total = len(ids)
    done = total - len(queue)
    no_text = sum(1 for status in known.values() if status == "no_text")
    cache_dir = Path(db_path).with_name("storyboards")
    emit({"type": "index_progress", "done": done, "total": total, "no_text": no_text})
    while queue:
        if stop.is_set():
            return
        while pause.is_set():
            if stop.is_set():
                return
            pause.wait(0.3)
        preferred = [video_id for video_id in (priority() or []) if video_id in waiting]
        video_id = preferred[0] if preferred else queue[0]
        queue.remove(video_id)
        waiting.discard(video_id)
        paused = 0
        while True:
            try:
                status = index_one(video_id, channel.id, auth, db, emit, cache_dir)
                if status == "no_text":
                    no_text += 1
                break
            except Exception as exc:
                kind, text = diagnose(exc)
                if kind in {"ratelimit", "bot"} and paused < 1:
                    paused += 1
                    reason = "YouTube просит подтвердить, что запрос не от робота." if kind == "bot" else "YouTube ограничил запросы."
                    emit({"type": "index_status", "message": f"{reason} Индекс подождёт 30 минут."})
                    if not _sleep(30 * 60, stop, pause):
                        return
                    continue
                if kind == "bot":
                    emit({"type": "index_status", "message": "Индекс остановлен: YouTube по-прежнему просит проверку «не робот»."})
                    return
                if kind == "need_login":
                    db.mark(video_id, channel.id, "need_login", error=text)
                elif kind == "unavailable":
                    db.mark(video_id, channel.id, "unavailable", error=text)
                else:
                    db.mark(video_id, channel.id, "error", error=text)
                    emit({"type": "index_status", "message": text})
                break
        done += 1
        emit({"type": "index_progress", "done": done, "total": total, "no_text": no_text})
        if not _sleep(random.uniform(3, 6), stop, pause):
            return
    emit({"type": "index_done", "done": done, "total": total, "no_text": no_text})


def run_asr(video_ids, channel, db_path, settings, emit, stop: threading.Event, pause: threading.Event, convert) -> None:
    """Распознать видео без субтитров в индекс, не создавая txt подборки."""
    db = IndexDB(db_path)
    options = dict(settings.get("converter") or {})
    options.update({"model": "large-v3-turbo", "max_accuracy": False, "text_mode": "Оригинал", "index_audio": True})
    total = len(video_ids)
    for index, video_id in enumerate(video_ids, 1):
        if stop.is_set():
            return
        while pause.is_set():
            if stop.is_set():
                return
            pause.wait(0.3)
        video = channel.videos.get(video_id)
        emit({"type": "index_status", "message": f"Распознаю для поиска {index} из {total}: {video.title if video else video_id}"})
        try:
            result = convert(watch_url(video_id), options, lambda *_a: None, stop, lambda message: emit({"type": "log", "message": message}))
        except Exception as exc:
            db.mark(video_id, channel.id, "error", error=str(exc))
            continue
        windows = [(int(start), text, "speech") for start, text in (result.paragraphs or []) if (text or "").strip()]
        meta = (video.title if video else "", video.description if video else "", " ".join(video.tags if video else []))
        db.replace_video(
            video_id, channel.id, float(result.duration or (video.duration_sec if video else 0)),
            windows, meta, "asr_index", result.language or "", "indexed",
        )
        emit({"type": "index_status", "message": f"В индексе: {video.title if video else video_id}"})


def _sleep(seconds: float, stop: threading.Event, pause: threading.Event) -> bool:
    end = time.time() + max(0, seconds)
    while time.time() < end:
        if stop.is_set():
            return False
        while pause.is_set() and not stop.is_set():
            time.sleep(0.2)
        time.sleep(min(0.2, max(0, end - time.time())))
    return not stop.is_set()
