"""Папки WhatYouTuber и запись json так, чтобы обрыв питания не портил файл."""

import json
import os
import tempfile
from pathlib import Path

from core.models import Channel, Collection, Settings, default_auth, default_converter
from core.naming import safe_name


def app_home() -> Path:
    override = os.environ.get("WY_HOME")
    if override:
        return Path(override)
    return Path(os.environ.get("APPDATA") or str(Path.home())) / "WhatYouTuber"


def bootstrap_path() -> Path:
    return app_home() / "bootstrap.json"


def desktop_dir() -> Path:
    return Path.home() / "Desktop" / "WhatYouTuber"


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def guess_converter() -> str:
    here = Path(__file__).resolve().parents[1]
    sibling = here.parent / "MP4-TXT"
    if (sibling / "main.py").is_file():
        return str(sibling)
    return ""


def load_settings() -> Settings:
    boot = read_json(bootstrap_path(), {}) or {}
    data_dir = boot.get("data_dir") or str(desktop_dir())
    raw = read_json(Path(data_dir) / "настройки.json", {}) or {}
    if not raw:
        raw = {"data_dir": data_dir}
    raw["data_dir"] = data_dir
    settings = Settings.from_dict(raw)
    auth = default_auth()
    auth.update(settings.auth or {})
    settings.auth = auth
    converter = default_converter(guess_converter())
    converter.update(settings.converter or {})
    if not converter.get("path"):
        converter["path"] = guess_converter()
    settings.converter = converter
    return settings


def save_settings(settings: Settings) -> None:
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "логи").mkdir(exist_ok=True)
    (data_dir / "Каналы").mkdir(exist_ok=True)
    write_json(bootstrap_path(), {"data_dir": str(data_dir)})
    write_json(data_dir / "настройки.json", settings.to_dict())


def bootstrap_exists() -> bool:
    return bootstrap_path().is_file()


def append_log(settings: Settings, line: str) -> None:
    from datetime import datetime
    folder = Path(settings.data_dir) / "логи"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now():%Y-%m-%d}.log"
    with path.open("a", encoding="utf-8") as file:
        file.write(f"{datetime.now():%H:%M:%S} {line}\n")


def _index_path(data_dir: Path) -> Path:
    return Path(data_dir) / "Каналы" / "index.json"


def channel_dir(settings: Settings, channel: Channel) -> Path:
    root = Path(settings.data_dir) / "Каналы"
    root.mkdir(parents=True, exist_ok=True)
    index = read_json(_index_path(Path(settings.data_dir)), {}) or {}
    known = index.get(channel.id) or {}
    folder_name = known.get("folder") or safe_name(channel.title or channel.handle or channel.id, 80)
    folder = root / folder_name
    if folder.exists() and known.get("folder") != folder_name:
        # другое имя занято чужим каналом
        marker = folder / "канал.json"
        if marker.is_file():
            existing = read_json(marker, {}) or {}
            if (existing.get("channel") or {}).get("id") not in {None, "", channel.id}:
                folder_name = safe_name(f"{folder_name} {channel.id[-6:]}", 80)
                folder = root / folder_name
    index[channel.id] = {
        "folder": folder.name,
        "title": channel.title,
        "handle": channel.handle,
    }
    write_json(_index_path(Path(settings.data_dir)), index)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_channel(settings: Settings, channel: Channel, ui: dict | None = None) -> Path:
    folder = channel_dir(settings, channel)
    write_json(folder / "канал.json", {"channel": channel.to_dict(), "ui": ui or {}})
    return folder


def load_channel(folder: Path):
    raw = read_json(Path(folder) / "канал.json", {}) or {}
    channel = Channel.from_dict(raw.get("channel") or {})
    ui = raw.get("ui") or {}
    return channel, ui


def list_channels(settings: Settings) -> list:
    root = Path(settings.data_dir) / "Каналы"
    index = read_json(_index_path(Path(settings.data_dir)), {}) or {}
    rows = []
    seen = set()
    for channel_id, meta in index.items():
        folder = root / (meta.get("folder") or "")
        if not (folder / "канал.json").is_file():
            continue
        rows.append({
            "id": channel_id,
            "title": meta.get("title") or folder.name,
            "handle": meta.get("handle") or "",
            "folder": str(folder),
        })
        seen.add(channel_id)
    if root.is_dir():
        for folder in root.iterdir():
            if not folder.is_dir() or not (folder / "канал.json").is_file():
                continue
            raw = read_json(folder / "канал.json", {}) or {}
            channel = raw.get("channel") or {}
            if channel.get("id") in seen:
                continue
            rows.append({
                "id": channel.get("id") or folder.name,
                "title": channel.get("title") or folder.name,
                "handle": channel.get("handle") or "",
                "folder": str(folder),
            })
    rows.sort(key=lambda item: (item.get("title") or "").lower())
    return rows


def collection_dir(channel_folder: Path, name: str) -> Path:
    folder = Path(channel_folder) / "Подборки" / safe_name(name, 80)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Тексты").mkdir(exist_ok=True)
    return folder


def save_collection(folder: Path, collection: Collection) -> None:
    write_json(Path(folder) / "подборка.json", collection.to_dict())


def load_collection(folder: Path) -> Collection | None:
    raw = read_json(Path(folder) / "подборка.json")
    if not raw:
        return None
    return Collection.from_dict(raw)


def topics_root(settings: Settings) -> Path:
    folder = Path(settings.data_dir) / "Подборки"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def list_topics(settings: Settings) -> list:
    root = Path(settings.data_dir) / "Подборки"
    if not root.is_dir():
        return []
    found = []
    for folder in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if (folder / "подборка.json").is_file():
            item = load_collection(folder)
            if item and item.kind == "topic":
                found.append((folder, item))
    return found


def list_collections(channel_folder: Path) -> list:
    root = Path(channel_folder) / "Подборки"
    if not root.is_dir():
        return []
    found = []
    for folder in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if (folder / "подборка.json").is_file():
            item = load_collection(folder)
            if item:
                found.append((folder, item))
    return found


def load_queue(folder: Path) -> dict:
    raw = read_json(Path(folder) / "очередь.json", {}) or {}
    return raw


def save_queue(folder: Path, payload: dict) -> None:
    write_json(Path(folder) / "очередь.json", payload)


def subtitle_cache(channel_folder: Path, video_id: str) -> Path:
    folder = Path(channel_folder) / "субтитры"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{video_id}.json"
