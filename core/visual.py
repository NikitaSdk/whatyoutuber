"""Слайды и доска: раскадровка, несколько кадров, текст в расшифровку и индекс."""

import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.fmt import fmt_clock

_PRESENTATION = re.compile(
    r"https?://[^\s<>\"]*(?:docs\.google\.com/presentation|drive\.google\.com|\.pdf\b|\.pptx?\b|slideshare\.net)[^\s<>\"]*",
    re.I,
)
_KIND = {"talking": "голова", "slides": "слайды", "mixed": "доска", "unknown": "неизвестно"}


def presentation_links(description: str) -> list:
    return _PRESENTATION.findall(description or "")


def merge_timeline(paragraphs, slides) -> str:
    events = []
    for start, text in paragraphs or []:
        if (text or "").strip():
            events.append((float(start), "speech", text.strip()))
    for slide in slides or []:
        if (slide.get("text") or "").strip() or slide.get("latex"):
            events.append((float(slide.get("t") or 0), "slide", slide))
    events.sort(key=lambda item: (item[0], 0 if item[1] == "speech" else 1))
    lines = []
    for moment, kind, payload in events:
        clock = fmt_clock(moment)
        if kind == "speech":
            lines.append(f"[{clock}] {payload}")
        else:
            lines.append(f"[СЛАЙД {clock}] {payload.get('text') or ''}".rstrip())
            for latex in payload.get("latex") or []:
                lines.append(f"LaTeX: {latex}")
    return "\n\n".join(lines).strip() + ("\n" if lines else "")


def _hashes(frames):
    import imagehash

    hashed = []
    for moment, tile in frames:
        hashed.append((moment, imagehash.phash(tile)))
    return hashed


def collect(video_id: str, auth: dict, folder, mode: str = "auto", formulas: bool = False, log=None, cache_dir=None) -> tuple[str, list]:
    """Вернуть (тип видео, кадры с текстом). mode: off | auto | on."""
    if mode == "off":
        return "", []
    from core.frames import grab, stream
    from core.ocr import read_frame
    from core.storyboard import analyse, best_storyboard, cache_board, cached_info, limit_moments, tiles
    from core.ytdlp_opts import client, extract
    from core.catalog import watch_url
    from PIL import Image

    info = cached_info(cache_dir, video_id) if cache_dir else None
    if info is None:
        info = extract(watch_url(video_id), auth, flat=False) or {}
        if cache_dir:
            cache_board(cache_dir, video_id, info)
    board = best_storyboard(info)
    kind = "talking"
    moments = []
    if board:
        _key, (ydl, _log) = client(auth, False)
        try:
            frames = list(tiles(ydl, board))
        except Exception:
            info = extract(watch_url(video_id), auth, flat=False) or {}
            if cache_dir:
                cache_board(cache_dir, video_id, info)
            board = best_storyboard(info)
            frames = list(tiles(ydl, board)) if board else []
        kind, moments = analyse(_hashes(frames)) if frames else ("unknown", [])
        if log:
            log(f"Раскадровка: { _KIND.get(kind, kind) }, кадров к чтению {len(moments)}.")
    else:
        duration = float(info.get("duration") or 0)
        probes = [duration * part for part in (0.2, 0.5, 0.8) if duration > 30]
        moments = limit_moments(probes or [10])
        kind = "unknown"
        if log:
            log("Раскадровки нет, беру 2–3 пробных кадра.")
    if mode == "auto" and kind == "talking":
        return kind, []
    if not moments:
        return kind, []
    url, headers = stream(auth, video_id)
    slides = []
    target = Path(folder) / "кадры"
    target.mkdir(parents=True, exist_ok=True)

    def one(moment, attempt=0):
        nonlocal url, headers
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "frame.jpg"
                try:
                    grab(url, headers, moment, path)
                except Exception as exc:
                    if attempt == 0 and "403" in str(exc):
                        url, headers = stream(auth, video_id)
                        return one(moment, 1)
                    raise
                img = Image.open(path)
                img.load()
                payload = read_frame(img, formulas)
                payload["t"] = round(float(moment), 1)
                return payload
        except Exception as exc:
            if log:
                log(f"Кадр {moment:.0f} с: {exc}")
            return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        for payload in pool.map(one, moments):
            if payload and ((payload.get("text") or "").strip() or payload.get("latex")):
                slides.append(payload)
    record = {"kind": kind, "frames": slides}
    (target / f"{video_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return kind, slides
