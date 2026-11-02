"""Отбор видео. Источник правды — множество отмеченных id, без обращения к YouTube."""


def effective(manual) -> set:
    return set(manual)


def group_mark(manual, ids) -> str:
    ids = list(ids or [])
    if not ids:
        return "off"
    got = sum(1 for video_id in ids if video_id in manual)
    if got == 0:
        return "off"
    if got == len(ids):
        return "on"
    return "partial"


def set_group(manual, ids, turn_on: bool) -> set:
    manual = set(manual)
    for video_id in ids or []:
        if turn_on:
            manual.add(video_id)
        else:
            manual.discard(video_id)
    return manual


def toggle_one(manual, video_id: str, turn_on: bool) -> set:
    manual = set(manual)
    if turn_on:
        manual.add(video_id)
    else:
        manual.discard(video_id)
    return manual


def invert(manual, ids) -> set:
    manual = set(manual)
    for video_id in ids or []:
        if video_id in manual:
            manual.discard(video_id)
        else:
            manual.add(video_id)
    return manual


def check_only_visible(manual, group_ids, visible_ids) -> set:
    """В этом пункте оставляет отмеченными только видео, которые сейчас видны по фильтру."""
    manual = set(manual)
    visible = set(visible_ids or [])
    for video_id in group_ids or []:
        if video_id in visible:
            manual.add(video_id)
        else:
            manual.discard(video_id)
    return manual


def whole_playlist_ids(manual, groups) -> list:
    found = []
    for key, _title, ids in groups:
        if not str(key).startswith("pl:"):
            continue
        if ids and all(video_id in manual for video_id in ids):
            found.append(str(key).split(":", 1)[1])
    return found


_RANK = {"loose": 1, "tab:streams": 2, "tab:shorts": 2, "tab:videos": 3}


def export_order(groups, manual) -> list:
    """Сначала порядок плейлиста, потом видео вне плейлистов, и только затем «Все видео»."""
    chosen, seen, ordered = set(manual), set(), []
    ranked = sorted(groups, key=lambda group: 0 if str(group[0]).startswith("pl:") else _RANK.get(group[0], 3))
    for _key, title, ids in ranked:
        for video_id in ids or []:
            if video_id in chosen and video_id not in seen:
                seen.add(video_id)
                ordered.append((video_id, title))
    return ordered


def summary(groups, manual, videos, ready_ids) -> dict:
    chosen = [video_id for video_id, _title in export_order(groups, manual)]
    whole = whole_playlist_ids(manual, groups)
    covered = set()
    for key, _title, ids in groups:
        playlist_id = str(key).split(":", 1)[1] if str(key).startswith("pl:") else ""
        if playlist_id in whole:
            covered.update(ids or [])
    seconds = 0
    adult = 0
    ready = 0
    for video_id in chosen:
        video = videos.get(video_id)
        if video is None:
            continue
        seconds += int(video.duration_sec or 0)
        if video.availability == "18+":
            adult += 1
        if video_id in ready_ids:
            ready += 1
    individual = [video_id for video_id in chosen if video_id not in covered]
    return {
        "count": len(chosen),
        "seconds": seconds,
        "whole_playlists": len(whole),
        "individual": len(individual),
        "ready": ready,
        "adult": adult,
        "order": chosen,
    }
