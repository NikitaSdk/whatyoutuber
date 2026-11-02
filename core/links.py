"""Распознавание ссылки: канал, видео, один плейлист или непонятный текст."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID = re.compile(r"^UC[\w-]{22}$")
HANDLE = re.compile(r"^[\w.\-]+$", re.UNICODE)

_DROP = {"si", "t", "pp", "feature", "ab_channel", "utm_source", "utm_medium", "utm_campaign", "embeds_referring_euri"}
_TAB_SUFFIXES = ("/videos", "/shorts", "/streams", "/playlists", "/featured", "/about", "/community")


@dataclass
class Link:
    kind: str
    url: str = ""
    video_id: str = ""
    playlist_id: str = ""
    channel_id: str = ""
    handle: str = ""
    message: str = ""


def clean_text(text: str) -> str:
    text = (text or "").strip().strip('"').strip()
    text = text.replace("\\", "/")
    if text.startswith("@"):
        handle = text[1:].split("/")[0].strip()
        return f"https://www.youtube.com/@{handle}" if handle else ""
    if VIDEO_ID.fullmatch(text):
        return f"https://www.youtube.com/watch?v={text}"
    if text.startswith("youtu.be/") or text.startswith("youtube.com/") or text.startswith("www.youtube.com/"):
        text = "https://" + text
    return text


def _canonical(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    if host.startswith("m."):
        host = host[2:]
    if host in {"youtube.com", "music.youtube.com", "youtu.be"}:
        host = "www.youtube.com" if host != "youtu.be" else "youtu.be"
    path = parsed.path or ""
    if host == "www.youtube.com":
        for suffix in _TAB_SUFFIXES:
            if path.rstrip("/").endswith(suffix):
                path = path.rstrip("/")[: -len(suffix)]
                break
    query = parse_qs(parsed.query, keep_blank_values=False)
    kept = []
    for key, values in query.items():
        if key.lower() in _DROP or not values:
            continue
        if key in {"v", "list"}:
            kept.append((key, values[0]))
    kept.sort(key=lambda item: item[0] != "v")
    return urlunparse((parsed.scheme or "https", host, path.rstrip("/"), "", urlencode(kept), ""))


def classify(text: str) -> Link:
    raw = clean_text(text)
    if not raw:
        return Link("bad", message="Вставьте ссылку на канал, видео или плейлист.")
    if not re.match(r"https?://", raw, re.I):
        return Link("bad", message="Это не похоже на ссылку YouTube.")
    url = _canonical(raw)
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in {"www.youtube.com", "youtu.be"}:
        return Link("bad", message="Это не похоже на ссылку YouTube.")

    path = parsed.path or ""
    query = parse_qs(parsed.query)
    video_id = ""
    if host == "youtu.be":
        candidate = path.strip("/").split("/")[0]
        if VIDEO_ID.fullmatch(candidate):
            video_id = candidate
    else:
        parts = [part for part in path.split("/") if part]
        if parts and parts[0] in {"shorts", "embed", "live", "v"} and len(parts) > 1 and VIDEO_ID.fullmatch(parts[1]):
            video_id = parts[1]
        elif "v" in query and VIDEO_ID.fullmatch(query["v"][0]):
            video_id = query["v"][0]
        watch = re.search(r"(?:watch\?v=|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})", url)
        if watch:
            video_id = watch.group(1)

    playlist_id = query.get("list", [""])[0]
    is_playlist_page = path.rstrip("/").endswith("/playlist") or path.rstrip("/") == "/playlist"

    if is_playlist_page and playlist_id:
        return Link("playlist", url=url, playlist_id=playlist_id)
    if video_id and not is_playlist_page:
        clean = f"https://www.youtube.com/watch?v={video_id}"
        return Link("video", url=clean, video_id=video_id, playlist_id=playlist_id)

    parts = [part for part in path.split("/") if part]
    if parts and parts[0] == "channel" and len(parts) > 1 and CHANNEL_ID.fullmatch(parts[1]):
        channel_id = parts[1]
        return Link("channel", url=f"https://www.youtube.com/channel/{channel_id}", channel_id=channel_id)
    if parts and parts[0].startswith("@") and HANDLE.fullmatch(parts[0][1:]):
        handle = parts[0][1:]
        return Link("channel", url=f"https://www.youtube.com/@{handle}", handle=handle)
    if parts and parts[0] in {"c", "user"} and len(parts) > 1:
        handle = parts[1]
        kind_path = parts[0]
        return Link("channel", url=f"https://www.youtube.com/{kind_path}/{handle}", handle=handle)
    if playlist_id and not video_id:
        return Link("playlist", url=f"https://www.youtube.com/playlist?list={playlist_id}", playlist_id=playlist_id)
    return Link("bad", message="Это не похоже на ссылку YouTube.")
