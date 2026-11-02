"""links.txt, titles.txt, список.csv, оглавление и общий файл."""

import csv
import os
from pathlib import Path

from core.catalog import watch_url
from core.fmt import fmt_clock, fmt_date
from core.naming import text_filename


def _mentions(path: Path, video_id: str) -> bool:
    if not video_id:
        return False
    try:
        with path.open(encoding="utf-8") as file:
            return video_id in file.read(2500)
    except OSError:
        return False


def text_path(folder, number, title, upload_date, style, stored: str = "", video_id: str = "") -> Path:
    """Готовый файл важнее нового имени: и по номеру, и по дате в стиле «дата - название»."""
    texts = Path(folder) / "Тексты"
    if stored and (texts / stored).is_file():
        return texts / stored
    if texts.is_dir() and number:
        found = sorted(texts.glob(f"{int(number):03d} - *.txt"))
        if found:
            return found[0]
    date = str(upload_date or "")
    if texts.is_dir() and len(date) >= 8 and date[:8].isdigit():
        prefix = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        dated = sorted(texts.glob(f"{prefix} - *.txt"))
        if video_id:
            for path in dated:
                if _mentions(path, video_id):
                    return path
        if len(dated) == 1:
            return dated[0]
    return texts / text_filename(number, title or "видео", upload_date, style)


def assign_numbers(existing: dict, order: list) -> dict:
    numbers = {str(key): int(value) for key, value in (existing or {}).items()}
    used = set(numbers.values())
    nxt = max(used or {0}) + 1
    for video_id in order:
        if video_id in numbers:
            continue
        while nxt in used:
            nxt += 1
        numbers[video_id] = nxt
        used.add(nxt)
        nxt += 1
    return numbers


def _playlist_cell(source_title: str) -> str:
    if source_title in {"Все видео", "Стримы", "Shorts", "Видео вне плейлистов"}:
        return source_title
    return source_title


def write_lists(folder: Path, channel, rows: list, numbers: dict, style: str) -> None:
    """rows: [(video, source_title)] в порядке подборки, уже без повторов."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    links = []
    titles = []
    csv_rows = []
    for video, source in rows:
        number = numbers[video.id]
        title = (video.title or video.id).replace("\r", " ").replace("\n", " ")
        links.append(watch_url(video.id))
        titles.append(title)
        filename = text_path(folder, number, video.title or video.id, video.upload_date, style, video_id=video.id).name
        csv_rows.append([
            f"{number:03d}",
            title,
            fmt_date(video.upload_date),
            fmt_clock(video.duration_sec),
            _playlist_cell(source),
            watch_url(video.id),
            str(Path("Тексты") / filename),
        ])
    (folder / "links.txt").write_text("\n".join(links) + ("\n" if links else ""), encoding="utf-8")
    (folder / "titles.txt").write_text("\n".join(titles) + ("\n" if titles else ""), encoding="utf-8")
    with (folder / "список.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["№", "Название", "Дата", "Длительность", "Плейлист", "Ссылка", "Файл текста"])
        writer.writerows(csv_rows)


def toc_line(number: int, video, filename: str, status: str) -> str:
    return (
        f"{number:03d} · {video.title} · {fmt_date(video.upload_date) or '—'} · {fmt_clock(video.duration_sec)}"
        f"      {watch_url(video.id)}      Тексты\\{filename} · {status}"
    )


def write_toc(folder: Path, channel, order: list, numbers: dict, statuses: dict, style: str) -> Path:
    lines = []
    for video_id in order:
        video = channel.videos.get(video_id)
        if video is None:
            continue
        number = int(numbers.get(video_id) or 0)
        filename = text_path(folder, number, video.title or video.id, video.upload_date, style, video_id=video.id).name
        lines.append(toc_line(number, video, filename, statuses.get(video_id) or "ожидает"))
    path = Path(folder) / "Оглавление.txt"
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def text_header(video, channel, source: str) -> str:
    return "\n".join([
        f"Название: {video.title}",
        f"Канал: {getattr(video, 'channel_title', '') or channel.title} · Дата: {fmt_date(video.upload_date) or '—'} · Длительность: {fmt_clock(video.duration_sec)}",
        f"Ссылка: {watch_url(video.id)}",
        f"Источник текста: {source}",
        "-" * 40,
        "",
    ])


def write_transcript(folder: Path, filename: str, header: str, body: str, with_header: bool) -> Path:
    texts = Path(folder) / "Тексты"
    texts.mkdir(parents=True, exist_ok=True)
    target = texts / filename
    temporary = texts / (filename + ".tmp")
    parts = []
    if with_header and header:
        parts.append(header)
    parts.append((body or "").strip() + "\n")
    temporary.write_text("".join(parts), encoding="utf-8")
    os.replace(temporary, target)
    return target


def file_ready(path: Path) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    try:
        return path.stat().st_size > 20
    except OSError:
        return False


def combine_texts(folder: Path, channel, order: list, numbers: dict, style: str) -> Path:
    chunks = []
    texts = Path(folder) / "Тексты"
    for video_id in order:
        video = channel.videos.get(video_id)
        if video is None:
            continue
        number = int(numbers.get(video_id) or 0)
        path = text_path(folder, number, video.title or video.id, video.upload_date, style, video_id=video.id)
        title = f"{number:03d} · {video.title}"
        chunks.append("=" * 40)
        chunks.append(title)
        chunks.append("=" * 40)
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8").strip())
        else:
            chunks.append("[текста пока нет]")
        chunks.append("")
    target = Path(folder) / "Все тексты в одном файле.txt"
    target.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")
    return target


def search_texts(folder: Path, channel, order: list, numbers: dict, style: str, query: str, radius: int = 40) -> list:
    from core.fmt import fold
    needle = fold(query).strip()
    if not needle:
        return []
    found = []
    texts = Path(folder) / "Тексты"
    for video_id in order:
        video = channel.videos.get(video_id)
        if video is None:
            continue
        number = int(numbers.get(video_id) or 0)
        path = text_path(folder, number, video.title or video.id, video.upload_date, style, video_id=video.id)
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        folded = fold(original)
        pos = folded.find(needle)
        if pos < 0:
            continue
        start = max(0, pos - radius)
        end = min(len(original), pos + len(needle) + radius)
        snippet = original[start:end].replace("\n", " ")
        if start > 0:
            snippet = "…" + snippet
        if end < len(original):
            snippet = snippet + "…"
        found.append({"video_id": video_id, "number": number, "title": video.title, "file": str(path), "snippet": snippet})
    return found
