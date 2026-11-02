"""Общие настройки yt-dlp: тихий режим, вход и среда JavaScript.

Конвертер «Видео → текст» здесь не вызывается и не меняется.
"""

import json
import os
import shutil
import threading


def find_node():
    found = shutil.which("node")
    if found and os.path.isfile(found):
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    for path in (
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        os.path.join(local, "Programs", "nodejs", "node.exe"),
    ):
        if path and os.path.isfile(path):
            return path
    return None


def find_deno():
    found = shutil.which("deno")
    if found and os.path.isfile(found):
        return found
    return None


def js_runtimes():
    deno = find_deno()
    if deno:
        return {"deno": {"path": deno}}
    node = find_node()
    if node:
        return {"node": {"path": node}}
    return None


def auth_opts(auth: dict | None) -> dict:
    auth = auth or {}
    mode = auth.get("mode") or "none"
    if mode == "browser" and auth.get("browser"):
        return {"cookiesfrombrowser": (auth.get("browser"),)}
    if mode == "file" and auth.get("cookie_file") and os.path.isfile(auth.get("cookie_file")):
        return {"cookiefile": auth.get("cookie_file")}
    return {}


class ErrorLog:
    """Собирает сообщения yt-dlp и не печатает их в консоль."""

    def __init__(self):
        self.errors = []
        self.warnings = []

    def debug(self, msg):
        return None

    def info(self, msg):
        return None

    def warning(self, msg):
        self.warnings.append(str(msg))

    def error(self, msg):
        self.errors.append(str(msg))


def build_opts(auth: dict | None = None, flat: bool = False, logger=None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": flat,
        "logger": logger or ErrorLog(),
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "sleep_interval_requests": 0.75,
        "sleep_interval_subtitles": 5,
        "remote_components": ["ejs:github"],
        "extract_flat": "in_playlist" if flat else False,
        "skip_download": True,
        "lazy_playlist": False,
        "noplaylist": not flat,
    }
    runtimes = js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    opts.update(auth_opts(auth))
    return opts


_LOCAL = threading.local()


def _merge(base: dict, extra: dict | None) -> dict:
    if not extra:
        return base
    out = dict(base)
    for key, value in extra.items():
        if key == "extractor_args" and isinstance(value, dict):
            merged = dict(out.get("extractor_args") or {})
            for name, args in value.items():
                current = dict(merged.get(name) or {})
                current.update(args or {})
                merged[name] = current
            out["extractor_args"] = merged
        else:
            out[key] = value
    return out


def client(auth: dict | None, flat: bool, extra: dict | None = None):
    """Один YoutubeDL на поток и на набор настроек. Cookies читаются один раз."""
    import yt_dlp

    cache = getattr(_LOCAL, "cache", None)
    if cache is None:
        cache = _LOCAL.cache = {}
    key = (json.dumps(auth_opts(auth), sort_keys=True, default=str), bool(flat), json.dumps(extra or {}, sort_keys=True))
    entry = cache.get(key)
    if entry is None:
        log = ErrorLog()
        entry = cache[key] = (yt_dlp.YoutubeDL(_merge(build_opts(auth, flat, log), extra)), log)
    return key, entry


def extract(url: str, auth: dict | None = None, flat: bool = False, extra: dict | None = None):
    from core.errors import classify_failure

    last = None
    # Другой клиент плеера — только если у одиночного видео сломались форматы.
    attempts = [extra or {}]
    if not flat:
        attempts.append(_merge(extra or {}, {"extractor_args": {"youtube": {"player_client": ["tv_embedded"]}}}))
        attempts.append(_merge(extra or {}, {"extractor_args": {"youtube": {"player_client": ["web_safari"]}}}))
    for attempt in attempts:
        key, (ydl, log) = client(auth, flat, attempt)
        log.errors.clear()
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as exc:
            last = exc
            cache = getattr(_LOCAL, "cache", None) or {}
            cache.pop(key, None)
            if flat or classify_failure(exc) != "outdated":
                raise RuntimeError(str(exc)) from exc
            continue
        if info:
            return info
        if log.errors:
            last = RuntimeError(log.errors[-1])
            if flat or classify_failure(last) != "outdated":
                raise last
    if last:
        raise RuntimeError(str(last))
    raise RuntimeError("Не удалось прочитать ссылку YouTube.")
