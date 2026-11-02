"""Порядок пунктов слева и слияние повторного сканирования с уже сохранённым каналом."""

from datetime import date

from core.models import Channel


def _known(channel: Channel, video_id: str):
    return video_id in channel.videos


def order_by_date(channel: Channel, ids, reverse_if_undated: bool = True) -> list:
    ids = [video_id for video_id in ids if _known(channel, video_id)]
    if any(channel.videos[video_id].upload_date for video_id in ids):
        return sorted(ids, key=lambda video_id: channel.videos[video_id].upload_date or "99999999")
    if reverse_if_undated:
        return list(reversed(ids))
    return ids


def loose_ids(channel: Channel) -> list:
    covered = set()
    for playlist in channel.playlists:
        covered.update(playlist.video_ids)
    raw = [video_id for video_id in (channel.tabs.get("videos") or []) if video_id not in covered]
    return order_by_date(channel, raw)


def all_video_ids(channel: Channel) -> list:
    ordered = order_by_date(channel, channel.tabs.get("videos") or [])
    seen = set(ordered)
    removed = [
        video.id for video in channel.videos.values()
        if video.removed_from_channel and video.id not in seen and video.kind == "video"
    ]
    return ordered + removed


def build_groups(channel: Channel) -> list:
    groups = [
        ("tab:videos", "Все видео", all_video_ids(channel)),
        ("tab:streams", "Стримы", [video_id for video_id in (channel.tabs.get("streams") or []) if _known(channel, video_id)]),
        ("tab:shorts", "Shorts", [video_id for video_id in (channel.tabs.get("shorts") or []) if _known(channel, video_id)]),
    ]
    for playlist in channel.playlists:
        ids = [video_id for video_id in playlist.video_ids if _known(channel, video_id)]
        groups.append((f"pl:{playlist.id}", playlist.title or "Плейлист", ids))
    groups.append(("loose", "Видео вне плейлистов", loose_ids(channel)))
    return groups


def group_by_key(channel: Channel) -> dict:
    return {key: (title, ids) for key, title, ids in build_groups(channel)}


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def merge_channel(old: Channel, new: Channel) -> list:
    """Переносит даты и описания. Возвращает id видео, которых раньше не было."""
    today = date.today().isoformat()
    fresh = []
    for video_id, video in new.videos.items():
        prev = old.videos.get(video_id)
        if prev is None:
            video.is_new = True
            video.first_seen = video.first_seen or today
            fresh.append(video_id)
            continue
        video.first_seen = prev.first_seen or today
        video.is_new = prev.is_new
        video.removed_from_channel = False
        if prev.details_loaded:
            video.upload_date = prev.upload_date or video.upload_date
            video.description = prev.description
            video.tags = list(prev.tags or [])
            video.availability = prev.availability or video.availability
            video.has_subtitles = prev.has_subtitles
            video.subtitle_langs = list(prev.subtitle_langs or [])
            video.details_loaded = True
    for video_id, prev in old.videos.items():
        if video_id not in new.videos:
            prev.removed_from_channel = True
            prev.is_new = False
            new.videos[video_id] = prev
    return fresh
