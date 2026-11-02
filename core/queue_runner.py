"""Очередь конвертации: пауза, стоп, пропуск готового, повтор после сбоя."""

import threading
import time
from pathlib import Path

from core.errors import Cancelled, classify_failure
from core.export import file_ready, text_header, text_path, write_toc, write_transcript
from core.models import QueueItem
from core.storage import load_queue, save_queue


def _status_word(status: str) -> str:
    return {
        "done": "готово",
        "error": "ошибка",
        "waiting": "ожидает",
        "running": "в работе",
        "skipped": "пропущено",
        "need_login": "нужен вход",
    }.get(status, status)


def build_items(channel, order, numbers, folder: Path, style: str) -> tuple[list, float]:
    folder = Path(folder)
    raw = load_queue(folder)
    previous = {item.get("video_id"): item for item in raw.get("items") or []}
    ratio = float(raw.get("ratio") or 0)
    items = []
    for video_id in order:
        video = channel.videos.get(video_id)
        if video is None:
            continue
        number = int(numbers.get(video_id) or 0)
        target = text_path(folder, number, video.title or video_id, video.upload_date, style, video_id=video_id)
        filename = target.name
        old = previous.get(video_id) or {}
        status = old.get("status") or "waiting"
        error = old.get("error") or ""
        if video.removed_from_channel:
            status, error = "skipped", "удалено с канала"
        elif video.availability == "unavailable":
            status, error = "skipped", "недоступно"
        elif file_ready(target):
            status, error = "done", ""
        elif status in {"running", "done"}:
            status = "waiting"
        items.append(QueueItem(
            video_id=video_id,
            number=number,
            status=status,
            attempts=int(old.get("attempts") or 0),
            error=error,
            source=old.get("source") or "",
            out_file=str(Path("Тексты") / filename),
            seconds_spent=float(old.get("seconds_spent") or 0),
        ))
    remember(folder, items, ratio)
    return items, ratio


def remember(folder: Path, items: list, ratio: float) -> None:
    save_queue(folder, {
        "items": [item.to_dict() for item in items],
        "ratio": ratio,
    })


def retry_failed(items: list) -> int:
    count = 0
    for item in items:
        if item.status in {"error", "need_login"}:
            item.status = "waiting"
            item.error = ""
            count += 1
    return count


def run(channel, items: list, folder: Path, settings, auth, emit, stop: threading.Event,
        pause: threading.Event, convert, subtitles_text=None, prefetch=None, visual: str = "off",
        formulas: bool = False) -> None:
    folder = Path(folder)
    style = settings.filename_style
    raw = load_queue(folder)
    # Старый замер «медленнее реального времени» — это был процессор. Он портит прогноз.
    stored = float(raw.get("ratio") or 0)
    samples = [stored] if 0 < stored < 1 else []
    ahead = {}
    fast = bool(settings.fast_subtitles)
    numbers = {item.video_id: item.number for item in items}

    def statuses():
        return {item.video_id: _status_word(item.status) for item in items}

    def kick(url: str):
        if not prefetch or not url or url in ahead:
            return

        box = {}

        def work():
            try:
                box["got"] = prefetch(url, lambda message: emit({
                    "type": "log",
                    "message": f"Следующий ролик: {message}",
                }))
            except Exception as exc:
                box["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        ahead[url] = (thread, box)
        thread.start()

    def take(url: str):
        job = ahead.pop(url, None)
        if not job:
            return None
        thread, box = job
        while thread.is_alive():
            if stop.is_set():
                return None
            thread.join(0.3)
        got = box.get("got")
        if not got and box.get("error"):
            emit({"type": "log", "message": f"Звук следующего ролика скачаю ещё раз: {box['error']}"})
        return got

    def publish(item, message=""):
        ratio = _average(samples)
        remember(folder, items, ratio)
        write_toc(folder, channel, [entry.video_id for entry in items], numbers, statuses(), style)
        emit({
            "type": "queue",
            "id": item.video_id,
            "status": item.status,
            "error": item.error,
            "message": message,
            "items": [entry.to_dict() for entry in items],
            "ratio": ratio,
            "eta": _remaining(channel, items, ratio),
        })

    total = len(items)
    cursor = 0
    while cursor < len(items):
        item = items[cursor]
        if item.status != "waiting":
            cursor += 1
            continue
        if stop.is_set():
            break
        if pause.is_set():
            emit({"type": "log", "message": "Пауза."})
            while pause.is_set():
                if stop.is_set():
                    break
                pause.wait(0.3)
            if stop.is_set():
                break
        video = channel.videos.get(item.video_id)
        if video is None:
            item.status = "skipped"
            item.error = "нет данных о видео"
            publish(item)
            cursor += 1
            continue
        filename = Path(item.out_file).name
        target = folder / "Тексты" / filename
        if file_ready(target):
            item.status = "done"
            item.error = ""
            publish(item, "уже есть текст, пропускаю")
            cursor += 1
            continue
        if video.availability == "unavailable" or video.removed_from_channel:
            item.status = "skipped"
            item.error = "удалено с канала" if video.removed_from_channel else "недоступно"
            publish(item, item.error)
            cursor += 1
            continue

        item.status = "running"
        item.attempts += 1
        publish(item, f"Видео {cursor + 1} из {total}: {video.title}")
        started = time.time()
        try:
            source = ""
            body = ""
            paragraphs = []
            if fast and video.has_subtitles is not False and subtitles_text:
                emit({"type": "log", "message": "Пробую субтитры YouTube..."})
                got = subtitles_text(video.id)
                body, source = got[0], got[1]
                if len(got) > 2:
                    paragraphs = [(float(start), text) for start, text in (got[2] or []) if (text or "").strip()]
            if not (body or "").strip():
                def progress(fraction, phase):
                    emit({
                        "type": "progress",
                        "id": video.id,
                        "fraction": max(0.0, min(1.0, float(fraction or 0))),
                        "phase": phase,
                        "index": cursor + 1,
                        "total": total,
                        "eta": _remaining(channel, items, _average(samples)),
                    })

                url = f"https://www.youtube.com/watch?v={video.id}"
                next_url = ""
                for nxt in items[cursor + 1:]:
                    if nxt.status == "waiting":
                        next_url = f"https://www.youtube.com/watch?v={nxt.video_id}"
                        break
                kick(next_url)
                ready = take(url)
                source_path = url
                cleanup = None
                if ready:
                    source_path, cleanup = ready
                try:
                    result = convert(
                        source_path,
                        settings.converter,
                        progress,
                        stop,
                        lambda message: emit({"type": "log", "message": message}),
                    )
                finally:
                    if cleanup:
                        cleanup()
                body = result.text
                source = result.source
                paragraphs = list(result.paragraphs or [])
                if result.duration and not video.duration_sec:
                    video.duration_sec = result.duration
            slides = []
            if visual and visual != "off":
                try:
                    from core.visual import collect, merge_timeline
                    cache_dir = Path(getattr(settings, "data_dir", "") or "") / "storyboards"
                    kind, slides = collect(
                        video.id, auth, folder, visual, formulas,
                        lambda message: emit({"type": "log", "message": message}),
                        cache_dir if cache_dir.parent else None,
                    )
                    if kind:
                        video.visual_kind = kind
                    if slides and paragraphs:
                        body = merge_timeline(paragraphs, slides)
                    elif slides:
                        body = (body or "").rstrip() + "\n\n" + merge_timeline([], slides)
                except Exception as exc:
                    emit({"type": "log", "message": f"Слайды пропущены: {exc}"})
                    slides = []
            if paragraphs or slides:
                emit({
                    "type": "transcript",
                    "id": video.id,
                    "channel_id": channel.id,
                    "duration": video.duration_sec,
                    "paragraphs": paragraphs,
                    "slides": slides,
                    "source": "transcript" if paragraphs else "subs_auto",
                    "title": video.title,
                    "description": video.description,
                })
            header = text_header(video, channel, source or "конвертер")
            write_transcript(folder, filename, header, body, settings.file_header)
            spent = time.time() - started
            item.status = "done"
            item.error = ""
            item.source = source
            item.seconds_spent = spent
            if video.duration_sec:
                samples.append(spent / max(float(video.duration_sec), 1))
                del samples[:-20]
            publish(item, f"Готово: {filename}")
            cursor += 1
        except Cancelled:
            item.status = "waiting"
            item.error = ""
            publish(item, "Остановлено. Это видео начнётся заново при продолжении.")
            break
        except Exception as exc:
            kind = classify_failure(exc)
            item.error = str(exc)
            if kind == "disk":
                item.status = "error"
                publish(item, str(exc))
                emit({"type": "log", "message": str(exc)})
                break
            if kind == "ratelimit" and item.attempts < 2:
                emit({"type": "log", "message": "YouTube просит подождать 15 минут."})
                item.status = "waiting"
                publish(item)
                if not _sleep(15 * 60, stop, pause):
                    break
                continue
            if kind == "network" and item.attempts < 3:
                delay = [30, 120, 300][min(item.attempts - 1, 2)]
                emit({"type": "log", "message": f"Нет связи. Повтор через {delay} сек."})
                item.status = "waiting"
                publish(item)
                if not _sleep(delay, stop, pause):
                    break
                continue
            if kind == "need_login":
                item.status = "need_login"
                emit({"type": "auth_failed", "message": str(exc)})
            elif kind in {"unavailable", "members"}:
                item.status = "skipped"
            else:
                item.status = "error"
            publish(item, item.error)
            cursor += 1
        else:
            gap = 0 if prefetch else int(settings.pause_between_sec or 0)
            if gap and any(other.status == "waiting" for other in items):
                emit({"type": "log", "message": f"Пауза {gap} сек перед следующим видео."})
                if not _sleep(gap, stop, pause):
                    break
    _drop_ahead(ahead)
    remember(folder, items, _average(samples))
    emit({"type": "queue_done", "items": [entry.to_dict() for entry in items], "stopped": stop.is_set()})


def _drop_ahead(ahead: dict) -> None:
    for thread, box in list(ahead.values()):
        thread.join(2)
        got = box.get("got")
        if got:
            try:
                got[1]()
            except Exception:
                pass
    ahead.clear()


def _average(samples: list) -> float:
    if not samples:
        return 0
    return sum(samples) / len(samples)


def _remaining(channel, items, ratio: float) -> float:
    if ratio <= 0:
        return 0
    seconds = 0
    for item in items:
        if item.status != "waiting":
            continue
        video = channel.videos.get(item.video_id)
        seconds += float(video.duration_sec or 0) if video else 0
    return ratio * seconds


def _sleep(seconds: float, stop: threading.Event, pause: threading.Event) -> bool:
    end = time.time() + max(0, seconds)
    while time.time() < end:
        if stop.is_set():
            return False
        while pause.is_set() and not stop.is_set():
            time.sleep(0.2)
        time.sleep(min(0.2, max(0, end - time.time())))
    return not stop.is_set()
