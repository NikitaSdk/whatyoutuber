"""Один кадр из видео по прямой ссылке. Само видео на диск не пишется."""

import shutil
import subprocess
from pathlib import Path


def stream(auth, video_id: str):
    from core.catalog import watch_url
    from core.ytdlp_opts import client

    extra = {"format": "bv*[height<=720][ext=mp4]/bv*[height<=720]/b"}
    _key, (ydl, log) = client(auth, False, extra)
    log.errors.clear()
    info = ydl.extract_info(watch_url(video_id), download=False) or {}
    fmt = (info.get("requested_formats") or [info])[0]
    return fmt.get("url") or "", fmt.get("http_headers") or {}


def grab(url: str, headers: dict, second: float, out_path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Не найден ffmpeg, кадр слайда не вырезать.")
    header_lines = []
    for key, value in (headers or {}).items():
        if value:
            header_lines.append(f"{key}: {value}")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{float(second):.2f}",
    ]
    if header_lines:
        command.extend(["-headers", "\r\n".join(header_lines) + "\r\n"])
    command.extend(["-i", url, "-frames:v", "1", "-q:v", "2", str(out_path)])
    subprocess.run(
        command,
        check=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if not Path(out_path).is_file():
        raise RuntimeError("ffmpeg не записал кадр.")
