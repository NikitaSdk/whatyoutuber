"""Раскадровка YouTube: понять, слайды это или говорящая голова, не скачивая видео."""

from io import BytesIO


def cache_board(directory, video_id: str, info: dict) -> None:
    board = best_storyboard(info)
    if not board or not video_id:
        return
    from pathlib import Path
    import json
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"duration": info.get("duration") or 0, "storyboard": board}
    (folder / f"{video_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def cached_info(directory, video_id: str):
    from pathlib import Path
    import json
    path = Path(directory) / f"{video_id}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    board = payload.get("storyboard")
    if not board:
        return None
    return {"duration": payload.get("duration") or 0, "formats": [board]}


def best_storyboard(info: dict):
    boards = [item for item in (info or {}).get("formats") or [] if str(item.get("format_id") or "").startswith("sb")]
    return max(boards, key=lambda item: item.get("width") or 0) if boards else None


def tiles(ydl, board):
    from PIL import Image

    width, height = int(board["width"]), int(board["height"])
    rows, cols = int(board.get("rows") or 1), int(board.get("columns") or 1)
    try:
        fps = float(board.get("fps") or 0)
    except (TypeError, ValueError):
        fps = 0
    step = (1 / fps) if fps else 0
    moment = 0.0
    for fragment in board.get("fragments") or []:
        sheet = Image.open(BytesIO(ydl.urlopen(fragment["url"]).read())).convert("L")
        per_tile = step or ((fragment.get("duration") or 0) / (rows * cols)) or 0.5
        for row in range(rows):
            for col in range(cols):
                tile = sheet.crop((col * width, row * height, (col + 1) * width, (row + 1) * height))
                if tile.getbbox() is None:
                    moment += per_tile
                    continue
                yield moment, tile
                moment += per_tile


def _distance(left, right) -> int:
    if hasattr(left, "__sub__") and not isinstance(left, int):
        return int(left - right)
    return (int(left) ^ int(right)).bit_count()


def analyse(frames, change=12, calm=4, plateau_sec=20):
    """frames: [(секунда, отпечаток)]. Возвращает тип и моменты для чётких кадров."""
    plateaus, start, prev = [], None, None
    for moment, digest in frames:
        if prev is not None and _distance(digest, prev[1]) <= calm:
            start = start if start is not None else prev[0]
        else:
            if start is not None and prev[0] - start >= plateau_sec:
                plateaus.append((start, prev[0], prev[1]))
            start = None
        prev = (moment, digest)
    if start is not None and prev and prev[0] - start >= plateau_sec:
        plateaus.append((start, prev[0], prev[1]))

    total = frames[-1][0] if frames else 1
    total = total or 1
    covered = sum(end - begin for begin, end, _digest in plateaus) / total
    unique = []
    for begin, end, digest in plateaus:
        if all(_distance(digest, item[2]) > 6 for item in unique):
            unique.append((begin, end, digest))

    gradual = []
    last_taken = None
    calm_since = None
    prev = None
    for moment, digest in frames:
        if last_taken is None:
            last_taken = (moment, digest)
            prev = (moment, digest)
            continue
        if _distance(digest, last_taken[1]) > change:
            calm_since = calm_since if calm_since is not None else moment
            if prev and moment - calm_since >= 10 and _distance(digest, prev[1]) <= calm:
                gradual.append(moment)
                last_taken = (moment, digest)
                calm_since = None
        else:
            calm_since = None
        if moment - last_taken[0] >= 180:
            gradual.append(moment)
            last_taken = (moment, digest)
        prev = (moment, digest)

    if len(unique) >= 5 and covered >= 0.5:
        kind = "slides"
    elif len(unique) >= 3 or len(gradual) >= 3:
        kind = "mixed"
    else:
        kind = "talking"
    moments = [max(begin, end - 2) for begin, end, _digest in unique]
    moments.extend(gradual)
    return kind, limit_moments(moments)


def limit_moments(moments, per_minute=2, per_hour=120, gap=15) -> list:
    kept = []
    for moment in sorted(float(item) for item in moments):
        if kept and moment - kept[-1] < gap:
            continue
        minute = int(moment // 60)
        hour = int(moment // 3600)
        if sum(1 for item in kept if int(item // 60) == minute) >= per_minute:
            continue
        if sum(1 for item in kept if int(item // 3600) == hour) >= per_hour:
            continue
        kept.append(moment)
    return kept
