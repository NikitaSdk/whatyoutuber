"""Данные канала, подборки и очереди. Окна хранят те же объекты, но не ходят в YouTube."""

from dataclasses import asdict, dataclass, field, fields


def _pick(cls, data: dict):
    if data is None:
        data = {}
    allowed = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class Video:
    id: str
    title: str = ""
    duration_sec: float = 0
    upload_date: str = ""
    description: str = ""
    tags: list = field(default_factory=list)
    kind: str = "video"
    availability: str = "public"
    playlists: list = field(default_factory=list)
    foreign_channel: bool = False
    has_subtitles: bool | None = None
    subtitle_langs: list = field(default_factory=list)
    details_loaded: bool = False
    first_seen: str = ""
    removed_from_channel: bool = False
    is_new: bool = False
    channel_title: str = ""
    visual_kind: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Video":
        return _pick(cls, data)


@dataclass
class Playlist:
    id: str
    title: str = ""
    video_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Playlist":
        return _pick(cls, data)


@dataclass
class Channel:
    id: str
    handle: str = ""
    title: str = ""
    url: str = ""
    videos: dict = field(default_factory=dict)
    playlists: list = field(default_factory=list)
    tabs: dict = field(default_factory=dict)
    scanned_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "handle": self.handle,
            "title": self.title,
            "url": self.url,
            "videos": {key: video.to_dict() for key, video in self.videos.items()},
            "playlists": [item.to_dict() for item in self.playlists],
            "tabs": {
                "videos": list(self.tabs.get("videos") or []),
                "streams": list(self.tabs.get("streams") or []),
                "shorts": list(self.tabs.get("shorts") or []),
            },
            "scanned_at": self.scanned_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Channel":
        videos = {
            key: Video.from_dict(value)
            for key, value in (data.get("videos") or {}).items()
        }
        playlists = [Playlist.from_dict(item) for item in data.get("playlists") or []]
        tabs = data.get("tabs") or {}
        return cls(
            id=data.get("id") or "",
            handle=data.get("handle") or "",
            title=data.get("title") or "",
            url=data.get("url") or "",
            videos=videos,
            playlists=playlists,
            tabs={
                "videos": list(tabs.get("videos") or []),
                "streams": list(tabs.get("streams") or []),
                "shorts": list(tabs.get("shorts") or []),
            },
            scanned_at=data.get("scanned_at") or "",
        )


@dataclass
class Collection:
    name: str
    channel_id: str
    whole_playlists: list = field(default_factory=list)
    single_videos: list = field(default_factory=list)
    order: list = field(default_factory=list)
    numbers: dict = field(default_factory=dict)
    created_at: str = ""
    kind: str = "channel"
    channels: list = field(default_factory=list)
    visual: str = "off"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Collection":
        item = _pick(cls, data)
        item.numbers = {str(key): int(value) for key, value in (item.numbers or {}).items()}
        return item


@dataclass
class QueueItem:
    video_id: str
    number: int = 0
    status: str = "waiting"
    attempts: int = 0
    error: str = ""
    source: str = ""
    out_file: str = ""
    seconds_spent: float = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "QueueItem":
        return _pick(cls, data)


@dataclass
class Settings:
    data_dir: str
    auth: dict = field(default_factory=dict)
    converter: dict = field(default_factory=dict)
    pause_between_sec: int = 5
    fast_subtitles: bool = False
    filename_style: str = "number"
    file_header: bool = True
    shutdown_after: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        item = _pick(cls, data or {})
        item.auth = dict(item.auth or {})
        item.converter = dict(item.converter or {})
        return item


def default_auth() -> dict:
    return {
        "mode": "none",
        "browser": "firefox",
        "cookie_file": "",
        "last_ok": None,
        "last_message": "",
    }


def default_converter(path: str = "") -> dict:
    return {
        "path": path,
        "language": "Авто",
        "model": "Авто",
        "text_mode": "Оригинал",
        "max_accuracy": False,
    }
