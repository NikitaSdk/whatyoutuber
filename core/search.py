"""Поиск по индексу: понятия, синонимы и уровень от 1 до 5 звёзд."""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from core.lemma import lemmatize, load_synonyms

P = dict(
    lvl2_mentions=2,
    lvl3_mentions=4,
    lvl3_focus=2,
    lvl4_focus=5,
    lvl4_together=2,
    lvl5_focus=15,
    lvl5_cover=0.30,
)

_SOURCE = {
    "subs_manual": "авторские субтитры",
    "subs_auto": "автосубтитры",
    "transcript": "расшифровка",
    "asr_index": "распознано для поиска",
}


@dataclass
class Metrics:
    mentions: int = 0
    density: float = 0
    segments: list = field(default_factory=list)
    focus: float = 0
    cover: float = 0
    together: int = 0
    in_title: bool = False
    in_chapters: bool = False


@dataclass
class Found:
    video_id: str
    channel_id: str
    level: int
    score: float
    start: int
    end: int
    moments: list
    snippet: str
    source: str
    where: str
    title_hit: bool = False


def concepts_of(query: str):
    return [part.strip() for part in (query or "").split(",") if part.strip()]


def _quote(term: str) -> str:
    clean = " ".join(term.replace('"', " ").split())
    return f'"{clean}"' if clean else ""


def _expand(concept: str, groups, index, weak_terms=None) -> tuple[list, set]:
    weak_terms = weak_terms or set()
    folded = lemmatize(concept)
    alts = [folded] if folded else []
    number = index.get(folded)
    if number is not None:
        for item in groups[number]:
            if item not in alts:
                alts.append(item)
    weak = {alt for alt in alts if alt in weak_terms}
    return alts, weak


def fts_query(query: str, groups, index, weak_terms=None, column: str = "") -> str:
    """Слабые синонимы в MATCH не входят: иначе «я» вытаскивает почти все окна."""
    parts = []
    prefix = f"{column} : " if column else ""
    for concept in concepts_of(query):
        alts, _weak = _expand(concept, groups, index, weak_terms)
        quoted = []
        for alt in alts:
            if alt in (_weak or set()):
                continue
            text = _quote(alt)
            if text:
                quoted.append(prefix + text)
        if quoted:
            parts.append("(" + " OR ".join(quoted) + ")")
    return " OR ".join(parts)


def level(metrics: Metrics, concept_count: int) -> int:
    if metrics.focus >= P["lvl5_focus"] or (metrics.cover >= P["lvl5_cover"] and metrics.mentions >= 10):
        return 5
    if metrics.focus >= P["lvl4_focus"] and (concept_count == 1 or metrics.together >= P["lvl4_together"]):
        return 4
    if metrics.mentions >= P["lvl3_mentions"] or metrics.focus >= P["lvl3_focus"]:
        return 3
    if metrics.mentions >= P["lvl2_mentions"]:
        return 2
    if metrics.mentions >= 1 or metrics.in_title or metrics.in_chapters:
        return 1
    return 0


def _count_term(lemmas: str, term: str) -> int:
    words = lemmas.split()
    term_words = term.split()
    if not term_words or not words:
        return 0
    if len(term_words) == 1:
        return words.count(term_words[0])
    count = 0
    width = len(term_words)
    for index in range(0, len(words) - width + 1):
        if words[index:index + width] == term_words:
            count += 1
    return count


def _metrics(minutes: dict, duration: float, concept_count: int, weak_minutes: dict) -> Metrics:
    """minutes[minute] = {concept: strong_count}. weak_minutes — короткие синонимы."""
    usable = {minute: dict(counts) for minute, counts in minutes.items()}
    for minute, weak in weak_minutes.items():
        near = False
        for shift in range(-1, 2):
            other = usable.get(minute + shift * 60) or {}
            if any(value for key, value in other.items()):
                near = True
                break
            foreign = weak_minutes.get(minute + shift * 60) or {}
            if any(key != list(weak)[0] and value for key, value in foreign.items() if weak):
                near = True
        concepts_here = set()
        for shift in range(-1, 2):
            concepts_here.update((usable.get(minute + shift * 60) or {}))
            concepts_here.update(key for key, value in (weak_minutes.get(minute + shift * 60) or {}).items() if value)
        if len(concepts_here) >= 2 or (concept_count == 1 and near):
            bucket = usable.setdefault(minute, {})
            for key, value in weak.items():
                bucket[key] = bucket.get(key, 0) + value
    if concept_count == 1:
        for minute, weak in weak_minutes.items():
            if any(value for value in weak.values()):
                # одно понятие из короткого слова само по себе не поднимает всю лекцию
                pass
    hits = sorted(minute for minute, counts in usable.items() if sum(counts.values()) > 0)
    mentions = sum(sum(counts.values()) for counts in usable.values())
    segments = []
    if hits:
        begin = prev = hits[0]
        for minute in hits[1:]:
            if minute - prev <= 120:
                prev = minute
                continue
            segments.append((begin, prev))
            begin = prev = minute
        segments.append((begin, prev))
    focus = 0
    best = (0, 0)
    for begin, end in segments:
        length = (end - begin) / 60 + 1
        if length > focus:
            focus = length
            best = (begin, end)
    duration_min = max(float(duration or 0) / 60, 1)
    together = 0
    if concept_count <= 1:
        together = len(hits)
    else:
        for minute in hits:
            present = set()
            for shift in range(3):
                present.update(key for key, value in (usable.get(minute + shift * 60) or {}).items() if value)
            if len(present) >= concept_count:
                together += 1
    return Metrics(
        mentions=mentions,
        density=mentions / (duration_min / 10),
        segments=segments,
        focus=focus,
        cover=len(hits) / duration_min,
        together=together,
        in_title=False,
        in_chapters=False,
    ), best


def search(path, query: str, synonyms_path, channel_ids=None, scope: str = "везде", min_level: int = 1) -> list:
    text = (query or "").strip()
    if not text or not path or not Path(path).is_file():
        return []
    groups, index, weak_terms = load_synonyms(synonyms_path)
    match = fts_query(text, groups, index, weak_terms)
    title_match = fts_query(text, groups, index, weak_terms, column="title")
    if not match and not title_match:
        return []
    concepts = []
    weaks = []
    for concept in concepts_of(text):
        alts, weak = _expand(concept, groups, index, weak_terms)
        concepts.append(alts)
        weaks.append(weak)
    con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        rows = []
        if match:
            rows = con.execute(
                """
                SELECT w.video_id, w.start, w.kind, w.text, w.lemmas, v.channel_id, v.duration, v.source
                FROM windows_fts JOIN windows w ON w.id = windows_fts.rowid
                JOIN videos v ON v.video_id = w.video_id
                WHERE windows_fts MATCH ?
                """,
                (match,),
            ).fetchall()
        meta_rows = []
        if scope != "речь" and title_match:
            meta_rows = con.execute(
                "SELECT video_id, title FROM meta_fts WHERE meta_fts MATCH ?",
                (title_match,),
            ).fetchall()
    finally:
        con.close()
    allowed = set(channel_ids) if channel_ids else None
    per_video = {}
    for row in rows:
        if allowed is not None and row["channel_id"] not in allowed:
            continue
        if scope == "названия":
            continue
        if scope == "мои тексты" and row["source"] not in {"transcript", "asr_index"}:
            continue
        if scope == "речь" and row["kind"] not in {"speech", "slide"}:
            continue
        bucket = per_video.setdefault(row["video_id"], {
            "channel_id": row["channel_id"],
            "duration": row["duration"] or 0,
            "source": row["source"] or "",
            "strong": {},
            "weak": {},
            "kinds": set(),
            "snippet": "",
            "snippet_at": 10 ** 9,
        })
        minute = int(row["start"])
        lemmas = row["lemmas"] or ""
        strong = bucket["strong"].setdefault(minute, {})
        weak = bucket["weak"].setdefault(minute, {})
        for number, alts in enumerate(concepts):
            for alt in alts:
                count = _count_term(lemmas, alt)
                if not count:
                    continue
                target = weak if alt in weaks[number] else strong
                target[number] = target.get(number, 0) + count
        if row["kind"] == "chapter":
            bucket["kinds"].add("главы")
        elif row["kind"] == "slide":
            bucket["kinds"].add("слайд")
        else:
            bucket["kinds"].add("речь")
        if minute < bucket["snippet_at"] and (row["text"] or "").strip():
            bucket["snippet_at"] = minute
            bucket["snippet"] = (row["text"] or "").strip().replace("\n", " ")[:180]
    titles = {}
    for row in meta_rows:
        titles[row["video_id"]] = True
    found = []
    seen = set(per_video)
    for video_id, bucket in per_video.items():
        metrics, best = _metrics(bucket["strong"], bucket["duration"], len(concepts), bucket["weak"])
        metrics.in_chapters = "главы" in bucket["kinds"]
        metrics.in_title = video_id in titles
        rank = level(metrics, len(concepts))
        if rank < min_level or rank == 0:
            continue
        where = list(bucket["kinds"])
        if metrics.in_title:
            where.append("название")
        score = metrics.focus * 3 + metrics.density + metrics.together * 2
        if metrics.in_title:
            score += 2
        if metrics.in_chapters:
            score += 2
        moments = []
        for minute in sorted(set(bucket["strong"]) | set(bucket["weak"])):
            if len(moments) >= 5:
                break
            moments.append(minute)
        found.append(Found(
            video_id=video_id,
            channel_id=bucket["channel_id"],
            level=rank,
            score=score,
            start=best[0],
            end=best[1] + 60,
            moments=moments,
            snippet=bucket["snippet"],
            source=_SOURCE.get(bucket["source"], bucket["source"] or "название"),
            where=", ".join(where) or "название",
            title_hit=metrics.in_title,
        ))
        seen.add(video_id)
    if scope in {"везде", "названия"}:
        con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            for video_id in titles:
                if video_id in seen:
                    continue
                row = con.execute(
                    "SELECT channel_id, duration, source FROM videos WHERE video_id = ?",
                    (video_id,),
                ).fetchone()
                if row is None or (allowed is not None and row["channel_id"] not in allowed):
                    continue
                metrics = Metrics(in_title=True)
                rank = level(metrics, len(concepts))
                if rank < min_level:
                    continue
                found.append(Found(
                    video_id=video_id,
                    channel_id=row["channel_id"],
                    level=rank,
                    score=2,
                    start=0,
                    end=0,
                    moments=[],
                    snippet="",
                    source=_SOURCE.get(row["source"] or "", "название"),
                    where="название",
                    title_hit=True,
                ))
        finally:
            con.close()
    found.sort(key=lambda item: (-item.level, -item.score, item.video_id))
    return found
