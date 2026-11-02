"""Быстрый проход: вкладки канала и плейлисты, без скачивания видео."""

import threading
from datetime import datetime

from core.catalog import merge_channel
from core.errors import Cancelled, explain
from core.links import classify
from core.models import Channel, Playlist, Video
from core.ytdlp_opts import extract


_LIVE_SKIP = {"is_live", "is_upcoming", "was_upcoming"}
# Дата из подписи «2 недели назад»: для сортировки и фильтра по году этого хватает.
_APPROX = {"extractor_args": {"youtubetab": {"approximate_date": [""]}}}


def _video_id(entry: dict) -> str:
    value = str((entry or {}).get("id") or "")
    if len(value) == 11:
        return value
    return ""


def _duration(entry: dict) -> float:
    try:
        return float(entry.get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def _keep(entry: dict) -> bool:
    if not entry:
        return False
    if (entry.get("live_status") or "") in _LIVE_SKIP:
        return False
    return bool(_video_id(entry))


def _add(channel: Channel, entry: dict, kind: str, playlist_id: str = "") -> str | None:
    video_id = _video_id(entry)
    if not video_id:
        return None
    own = channel.id
    entry_channel = entry.get("channel_id") or ""
    foreign = bool(entry_channel and own and entry_channel != own)
    video = channel.videos.get(video_id)
    if video is None:
        video = Video(
            id=video_id,
            title=(entry.get("title") or "").strip() or video_id,
            duration_sec=_duration(entry),
            kind=kind,
            foreign_channel=foreign,
        )
        channel.videos[video_id] = video
    else:
        if entry.get("title"):
            video.title = entry.get("title").strip() or video.title
        if _duration(entry):
            video.duration_sec = _duration(entry)
        if kind == "short":
            video.kind = "short"
        elif video.kind == "video" and kind == "stream":
            video.kind = "stream"
        if foreign:
            video.foreign_channel = True
    uploaded = str(entry.get("upload_date") or "")
    if uploaded and not video.details_loaded:
        video.upload_date = uploaded
    if playlist_id and playlist_id not in video.playlists:
        video.playlists.append(playlist_id)
    return video_id


def _entries(info: dict) -> list:
    return [entry for entry in (info.get("entries") or []) if entry]


def _channel_base(info: dict, link) -> tuple[str, str, str, str]:
    channel_id = info.get("channel_id") or info.get("uploader_id") or link.channel_id or info.get("id") or ""
    if channel_id and not str(channel_id).startswith("UC"):
        channel_id = info.get("channel_id") or channel_id
    title = info.get("channel") or info.get("uploader") or info.get("title") or link.handle or "Канал"
    # у вкладки title часто «Видео» / «Shorts» — имя канала важнее
    if title.lower() in {"videos", "video", "shorts", "streams", "playlists", "видео"}:
        title = info.get("channel") or info.get("uploader") or link.handle or title
    handle = link.handle or ""
    uploader = info.get("uploader_id") or ""
    if isinstance(uploader, str) and uploader.startswith("@"):
        handle = handle or uploader[1:]
    url = info.get("channel_url") or link.url
    if link.kind == "channel":
        url = link.url
    if str(channel_id).startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel_id}"
    return str(channel_id or link.url), handle, title, url


def scan(url_text: str, auth: dict, stop: threading.Event, status, previous: Channel | None = None) -> tuple[Channel, list]:
    link = classify(url_text)
    if link.kind == "bad":
        raise RuntimeError(link.message or "Это не похоже на ссылку YouTube.")
    if stop.is_set():
        raise Cancelled()

    if link.kind == "video":
        status("Открываю видео, чтобы узнать канал...")
        info = extract(link.url, auth, flat=False)
        channel_url = info.get("channel_url") or ""
        if not channel_url and info.get("channel_id"):
            channel_url = f"https://www.youtube.com/channel/{info['channel_id']}"
        if not channel_url:
            raise RuntimeError("У этого видео не видно канала.")
        link = classify(channel_url)
        if link.kind != "channel":
            link = classify(channel_url)
            if link.kind == "bad":
                raise RuntimeError("Не удалось перейти от видео к каналу.")

    if link.kind == "playlist":
        return _scan_playlist(link, auth, stop, status, previous)
    return _scan_channel(link, auth, stop, status, previous)


def _scan_playlist(link, auth, stop, status, previous) -> tuple[Channel, list]:
    status("Читаю плейлист...")
    info = extract(link.url, auth, flat=True)
    channel_id, handle, title, url = _channel_base(info, link)
    channel = Channel(
        id=channel_id or f"playlist:{link.playlist_id}",
        handle=handle,
        title=title,
        url=url,
        scanned_at=datetime.now().isoformat(timespec="minutes"),
    )
    playlist_id = info.get("id") or link.playlist_id
    playlist_title = info.get("title") or "Плейлист"
    ids = []
    for entry in _entries(info):
        if stop.is_set():
            break
        if not _keep(entry):
            continue
        video_id = _add(channel, entry, "video", playlist_id)
        if video_id:
            ids.append(video_id)
    channel.playlists = [Playlist(id=playlist_id, title=playlist_title, video_ids=ids)]
    channel.tabs = {"videos": [], "streams": [], "shorts": []}
    return _finish(channel, previous)


def _scan_channel(link, auth, stop, status, previous) -> tuple[Channel, list]:
    base = link.url.rstrip("/")
    status("Читаю видео канала...")
    videos_info = extract(base + "/videos", auth, flat=True, extra=_APPROX)
    channel_id, handle, title, url = _channel_base(videos_info, link)
    channel = Channel(
        id=channel_id or base,
        handle=handle or link.handle,
        title=title,
        url=url or base,
        scanned_at=datetime.now().isoformat(timespec="minutes"),
        tabs={"videos": [], "streams": [], "shorts": []},
    )
    for entry in _entries(videos_info):
        if stop.is_set():
            break
        if not _keep(entry):
            continue
        video_id = _add(channel, entry, "video")
        if video_id:
            channel.tabs["videos"].append(video_id)
    if stop.is_set():
        return _finish(channel, previous)

    for tab, kind, label in (("streams", "stream", "стримы"), ("shorts", "short", "Shorts")):
        status(f"Читаю {label}...")
        try:
            info = extract(base + "/" + tab, auth, flat=True, extra=_APPROX)
        except Exception as exc:
            status(explain(exc))
            continue
        if not channel.title or channel.title == base:
            _id, handle2, title2, url2 = _channel_base(info, link)
            channel.title = title2 or channel.title
            channel.handle = channel.handle or handle2
            channel.id = channel.id or _id
            channel.url = channel.url or url2
        for entry in _entries(info):
            if stop.is_set():
                break
            if not _keep(entry):
                continue
            video_id = _add(channel, entry, kind)
            if video_id and video_id not in channel.tabs[tab]:
                channel.tabs[tab].append(video_id)
        if stop.is_set():
            return _finish(channel, previous)

    status("Читаю список плейлистов...")
    playlists = []
    try:
        info = extract(base + "/playlists", auth, flat=True)
    except Exception as exc:
        status(explain(exc))
        info = {}
    raw_lists = []
    for entry in _entries(info or {}):
        playlist_id = str(entry.get("id") or "")
        if not playlist_id or len(playlist_id) == 11:
            continue
        raw_lists.append((playlist_id, (entry.get("title") or "Плейлист").strip()))
    total = len(raw_lists)
    for index, (playlist_id, playlist_title) in enumerate(raw_lists, 1):
        if stop.is_set():
            break
        status(f"Плейлист {index} из {total}: {playlist_title}")
        try:
            plist = extract(f"https://www.youtube.com/playlist?list={playlist_id}", auth, flat=True)
        except Exception as exc:
            status(explain(exc))
            continue
        ids = []
        for entry in _entries(plist):
            if stop.is_set():
                break
            if not _keep(entry):
                continue
            video_id = _add(channel, entry, "video", playlist_id)
            if video_id:
                ids.append(video_id)
        playlists.append(Playlist(id=playlist_id, title=plist.get("title") or playlist_title, video_ids=ids))
    channel.playlists = playlists
    channel.scanned_at = datetime.now().isoformat(timespec="minutes")
    return _finish(channel, previous)


def _finish(channel: Channel, previous: Channel | None):
    fresh = []
    if previous and previous.id == channel.id:
        fresh = merge_channel(previous, channel)
    return channel, fresh
