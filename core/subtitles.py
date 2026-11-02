"""Субтитры YouTube: кеш для поиска и быстрый текст, если автор их выложил."""

import json
import re
import threading
from pathlib import Path

from core.details import parse_details
from core.fmt import fmt_clock, fold
from core.ytdlp_opts import client


def parse_vtt(text: str) -> list:
    cues = []
    stamp = re.compile(
        r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s+-->\s+(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})"
    )
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = stamp.search(lines[index])
        if not match:
            index += 1
            continue
        start = _seconds(match.group(1), match.group(2), match.group(3), match.group(4))
        end = _seconds(match.group(5), match.group(6), match.group(7), match.group(8))
        index += 1
        parts = []
        while index < len(lines) and lines[index].strip() and not stamp.search(lines[index]):
            line = re.sub(r"<[^>]+>", "", lines[index]).strip()
            if line and not line.startswith("NOTE") and line != "WEBVTT":
                parts.append(line)
            index += 1
        phrase = " ".join(parts).strip()
        if phrase and (not cues or cues[-1]["text"] != phrase):
            cues.append({"start": start, "end": end, "text": phrase})
    return cues


def parse_json3(text: str) -> list:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    cues = []
    for event in payload.get("events") or []:
        segs = event.get("segs") or []
        phrase = "".join(seg.get("utf8") or "" for seg in segs).replace("\n", " ").strip()
        if not phrase or phrase == "\n":
            continue
        start = float(event.get("tStartMs") or 0) / 1000
        end = start + float(event.get("dDurationMs") or 0) / 1000
        if cues and cues[-1]["text"] == phrase:
            continue
        cues.append({"start": start, "end": end, "text": phrase})
    return cues


def _seconds(hours, minutes, secs, millis) -> float:
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + int(secs or 0) + int(millis or 0) / 1000


def cues_to_body(cues: list) -> str:
    lines = []
    buf = []
    start = None
    last_end = None

    def flush():
        nonlocal buf, start
        if not buf:
            return
        lines.append(f"[{fmt_clock(start or 0)}]")
        lines.append(" ".join(buf).strip())
        lines.append("")
        buf = []
        start = None

    for cue in cues:
        text = (cue.get("text") or "").strip()
        if not text:
            continue
        begin = float(cue.get("start") or 0)
        end = float(cue.get("end") or begin)
        gap = 0 if last_end is None else begin - last_end
        if buf and (gap > 1.5 or sum(len(part) for part in buf) > 400):
            flush()
        if not buf:
            start = begin
        buf.append(text)
        last_end = end
    flush()
    return "\n".join(lines).strip() + ("\n" if lines else "")


def find_snippet(cues: list, query: str, radius: int = 40) -> str:
    words = [fold(part) for part in (query or "").split(",") if part.strip()]
    if not words or not cues:
        return ""
    full = " ".join(cue.get("text") or "" for cue in cues)
    folded = fold(full)
    for word in words:
        pos = folded.find(word)
        if pos < 0:
            continue
        start = max(0, pos - radius)
        end = min(len(full), pos + len(word) + radius)
        snippet = full[start:end].replace("\n", " ")
        walked = 0
        stamp = 0
        for cue in cues:
            piece = (cue.get("text") or "") + " "
            if walked + len(piece) > pos:
                stamp = cue.get("start") or 0
                break
            walked += len(piece)
        return f"[{fmt_clock(stamp)}] {snippet}"
    return ""


def _pick_track(info: dict):
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    original = (info.get("language") or "").split("-")[0]
    for lang in (original, "ru", "uk", "en"):
        if lang and manual.get(lang):
            return lang, manual[lang], True
    if manual:
        lang = next(iter(manual))
        return lang, manual[lang], True
    for key, formats in auto.items():
        if str(key).endswith("-orig") and formats:
            return str(key).removesuffix("-orig"), formats, False
    if original and auto.get(original):
        return original, auto[original], False
    return None


def _pick_format(formats: list, manual: bool = True):
    order = ("vtt", "json3", "srv3") if manual else ("json3", "srv3", "vtt")
    for ext in order:
        for fmt in formats or []:
            if fmt.get("ext") == ext and fmt.get("url"):
                kind = "json3" if ext in {"json3", "srv3"} else "vtt"
                return fmt["url"], kind
    if formats and formats[0].get("url"):
        return formats[0]["url"], formats[0].get("ext") or "vtt"
    return None, None


def fetch(video_id: str, auth: dict, cache_path: Path) -> dict:
    cache_path = Path(cache_path)
    if cache_path.is_file():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    _key, (ydl, log) = client(auth, False)
    log.errors.clear()
    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False) or {}
    picked = _pick_track(info)
    if not picked:
        payload = {"lang": "", "manual": False, "cues": []}
    else:
        lang, formats, manual = picked
        url, kind = _pick_format(formats, manual)
        cues = []
        if url:
            raw = ydl.urlopen(url).read().decode("utf-8", errors="replace")
            cues = parse_json3(raw) if kind == "json3" else parse_vtt(raw)
        payload = {"lang": lang, "manual": manual, "cues": cues}
    details = parse_details(info) if info else None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(cache_path)
    if details:
        payload["details"] = details
    return payload


def body_from_cache(payload: dict) -> tuple[str, str]:
    cues = payload.get("cues") or []
    if not cues:
        return "", ""
    lang = payload.get("lang") or "?"
    kind = "авторские" if payload.get("manual") else "автоматические"
    return cues_to_body(cues), f"субтитры YouTube ({lang}, {kind})"


def search_current(video_ids, auth, cache_for, query, emit, stop: threading.Event, pause: threading.Event) -> None:
    for index, video_id in enumerate(video_ids, 1):
        if stop.is_set():
            return
        while pause.is_set():
            if stop.is_set():
                return
            pause.wait(0.2)
        try:
            payload = fetch(video_id, auth, cache_for(video_id))
        except Exception as exc:
            emit({"type": "sub_error", "id": video_id, "message": str(exc)})
            continue
        snippet = find_snippet(payload.get("cues") or [], query)
        emit({
            "type": "sub_hit",
            "id": video_id,
            "snippet": snippet,
            "empty": not (payload.get("cues") or []),
            "fields": payload.get("details"),
            "done": index,
            "total": len(video_ids),
        })
