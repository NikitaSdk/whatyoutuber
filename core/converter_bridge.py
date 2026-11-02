"""Вызов конвертера «Видео → текст» без изменений в его папке.

Файл конвертера не редактируется. WhatYouTuber загружает его main.py как библиотеку
и вызывает ту же функцию from_audio, которой пользуется его собственное окно.
Отдельный запуск python main.py в папке конвертера по-прежнему открывает его окно.
"""

import gc
import importlib.util
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.errors import Cancelled, explain

# Точный режим конвертера — float16 и луч 5. На видеокарте до 8 ГБ он не помещается,
# конвертер сбрасывает модель и считает весь ролик на процессоре.
FAST_VRAM_MIB = 8192
_VRAM = None
_SPEED_NOTE = False

LANGS = [
    "Авто", "Русский", "Украинский", "Английский", "Немецкий", "Французский",
    "Испанский", "Итальянский", "Португальский", "Польский", "Турецкий",
    "Арабский", "Китайский", "Японский", "Корейский",
]
MODELS = ["Авто", "small", "medium", "large-v3-turbo", "large-v3"]
MODES = ["Оригинал", "Перевод на русский", "Оригинал + перевод"]

_MODULES = {}
_CANCEL = threading.local()
_AUDIO = threading.local()


@dataclass
class ConvertResult:
    text: str
    language: str
    model: str
    duration: float
    title: str
    source: str
    paragraphs: list = field(default_factory=list)


def converter_file(path: str) -> Path:
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    main_py = folder / "main.py"
    if not main_py.is_file():
        raise RuntimeError(
            "Не найдена папка конвертера «Видео → текст». "
            "Откройте настройки и укажите каталог, в котором лежит его main.py."
        )
    return main_py


def gpu_total_mib() -> int:
    """Сколько памяти у первой видеокарты. 0, если её не видно."""
    global _VRAM
    if _VRAM is not None:
        return _VRAM
    total = 0
    try:
        raw = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            text=True,
            timeout=4,
            stderr=subprocess.DEVNULL,
        )
        line = raw.strip().splitlines()[0].strip()
        total = int(line)
    except Exception:
        total = 0
    _VRAM = total
    return total


def use_fast_gpu(max_accuracy: bool, memory_mib: int | None = None) -> tuple[bool, str]:
    """Какой флаг точности отдать конвертеру и что сказать человеку.

    На тесной видеокарте точный режим не «чуть медленнее», а в разы: модель
    не влезает, и конвертер дочитывает ролик на процессоре.
    """
    memory = gpu_total_mib() if memory_mib is None else int(memory_mib)
    if memory and memory <= FAST_VRAM_MIB:
        gb = max(1, int(round(memory / 1024)))
        return False, (
            f"На видеокарте {gb} ГБ включён быстрый режим large-v3-turbo. "
            "Точный режим сюда не помещается, поэтому он выключен."
        )
    if not max_accuracy:
        return False, "Быстрый режим: large-v3-turbo на видеокарте, один проход."
    return True, ""


def pin_model(module) -> None:
    """Держит уже загруженную модель. Конвертер иначе выкидывает её из памяти после сбоя."""
    if getattr(module, "_wy_pinned", False):
        return
    original = module.get_model
    held = {}

    def pinned(name, device, compute, log):
        key = (name, device, compute)
        with module._MODEL_LOCK:
            model = held.get(key)
            if model is not None:
                module._MODEL_CACHE[key] = model
                return model
            for old in list(held):
                held.pop(old, None)
                module._MODEL_CACHE.pop(old, None)
        gc.collect()
        model = original(name, device, compute, log)
        with module._MODEL_LOCK:
            held.clear()
            held[key] = model
            module._MODEL_CACHE[key] = model
        return model

    module.get_model = pinned
    module._wy_pinned = True
    module._wy_held = held


def _warm_key(settings: dict, accurate: bool) -> tuple[str, str]:
    name = settings.get("model") or "Авто"
    if name in {"", "Авто"}:
        name = "large-v3-turbo"
    if name == "large-v3" or accurate:
        compute = "float16"
    else:
        compute = "int8_float16"
    return name, compute


def install_speed(module) -> None:
    """Быстрый проход на тесной видеокарте и живые строки прогресса.

    Файл конвертера не меняется: правка живёт только в загруженной копии.
    Пакет 16 на этой видеокарте занимает около 3 ГБ и считает примерно в сто раз
    быстрее длины ролика. Проценты идут по ходу, а не одной пачкой в конце.
    """
    if getattr(module, "_wy_speed", False):
        return
    module.ONE_SHOT_SEC = 8 * 60 * 60
    if hasattr(module, "resolve_language"):
        original_resolve = module.resolve_language

        def resolve_language(model, path, duration, title, track_lang, user_lang, log):
            if not user_lang:
                track = module.normalize_lang(track_lang)
                if track:
                    log(f"Язык речи: {module.lang_label(track)} — по звуковой дорожке")
                    return track
            return original_resolve(model, path, duration, title, track_lang, user_lang, log)

        module.resolve_language = resolve_language

    if hasattr(module, "run_batched"):
        def run_batched(model, audio, lang, beam, batch, prompt, vad=None, clips=None):
            from faster_whisper import BatchedInferencePipeline
            pipe = BatchedInferencePipeline(model=model)
            fast = int(beam or 1) <= 1
            kwargs = dict(
                language=lang,
                task="transcribe",
                beam_size=int(beam or 1),
                best_of=1 if fast else 5,
                batch_size=max(1, int(batch or 1)),
                without_timestamps=True,
                temperature=0.0,
                multilingual=False,
                condition_on_previous_text=not fast,
            )
            if fast:
                # 30 секунд речи укладываются в этот предел. Дальше модель уже повторяет шум.
                kwargs["max_new_tokens"] = 192
            if clips:
                kwargs["vad_filter"] = False
                kwargs["clip_timestamps"] = clips
            else:
                kwargs["vad_filter"] = True
                kwargs["vad_parameters"] = dict(vad or module.VAD)
            return pipe.transcribe(audio, **kwargs)

        module.run_batched = run_batched

    if hasattr(module, "transcribe_file"):
        def transcribe_file(model, path, duration, lang, settings, log, on_paragraph):
            total = float(duration or module.probe_duration(path) or 1)
            beam = int(settings.get("beam") or 1)
            batch = int(settings.get("batch") or 8)
            memory = gpu_total_mib()
            if memory and memory <= FAST_VRAM_MIB:
                # На этой видеокарте пакет 16 быстрее пакета 4 и занимает около 3 ГБ.
                beam, batch = 1, 16
            log("Распознаю речь... Текст сразу пишется в файл.")
            started = time.time()
            paragraphs = module.Paragraphs()
            last_pct = -1

            def emit(end):
                nonlocal last_pct
                pct = min(99, int(float(end) / total * 100))
                if pct // 5 == last_pct // 5:
                    return
                spent = time.time() - started
                speed = end / spent if spent > 0 else 0
                left = (total - end) / speed if speed > 1 else 0
                log(
                    f"  {pct}%   {module.fmt_dur(end)} из {module.fmt_dur(total)}"
                    f"   {speed:.0f}×   осталось ~{module.fmt_dur(left)}"
                )
                last_pct = pct

            def consume(audio, clips=None):
                segments, _info = module.run_batched(model, audio, lang, beam, batch, None, dict(module.VAD), clips)
                for seg in segments:
                    event = getattr(_CANCEL, "event", None)
                    if event is not None and event.is_set():
                        raise Cancelled()
                    text = seg.text or ""
                    if not str(text).strip():
                        continue
                    start = float(seg.start or 0)
                    end = float(seg.end or start)
                    item = paragraphs.add(start, end, text)
                    if item and on_paragraph:
                        on_paragraph(*item)
                    emit(end)

            consume(path)
            tail = paragraphs.flush()
            if tail and on_paragraph:
                on_paragraph(*tail)
            if module.text_too_thin(paragraphs.items, total):
                log(
                    f"Получилось только {module.word_count(paragraphs.items)} слов на {module.fmt_dur(total)}. "
                    "Повторяю без пропуска тишины..."
                )
                paragraphs = module.Paragraphs()
                clips = []
                cursor = 0.0
                while cursor < total - 0.05:
                    clips.append({"start": cursor, "end": min(total, cursor + 30.0)})
                    cursor += 30.0
                consume(path, clips)
                tail = paragraphs.flush()
                if tail and on_paragraph:
                    on_paragraph(*tail)
            spent = max(time.time() - started, 0.001)
            log(f"Готово за {module.fmt_dur(spent)} ({total / spent:.0f}× быстрее ролика).")
            return paragraphs.items

        module.transcribe_file = transcribe_file

    if hasattr(module, "ydl_common") and hasattr(module, "download_audio"):
        slot = threading.local()
        original_ydl = module.ydl_common
        original_download = module.download_audio

        def ydl_common(**extra):
            opts = original_ydl(**extra)
            if extra.get("skip_download"):
                return opts

            def hook(event):
                log = getattr(slot, "log", None)
                if log is None or event.get("status") != "downloading":
                    return
                total = event.get("total_bytes") or event.get("total_bytes_estimate") or 0
                done = event.get("downloaded_bytes") or 0
                if total <= 0 or done <= 0:
                    return
                pct = int(done / total * 100)
                last = getattr(slot, "pct", -10)
                if pct < 100 and pct // 10 == last // 10:
                    return
                slot.pct = pct
                speed = event.get("speed") or 0
                eta = event.get("eta") or 0
                log(
                    f"  скачивание {pct}%   {done / 1048576:.1f} из {total / 1048576:.1f} МБ"
                    f"   {speed / 1048576:.1f} МБ/с   осталось ~{module.fmt_dur(eta)}"
                )

            opts["progress_hooks"] = [hook]
            if getattr(_AUDIO, "on", False):
                opts["format"] = "worstaudio/bestaudio"
            return opts

        def download_audio(url, folder, log):
            slot.log = log
            slot.pct = -10
            started = time.time()
            try:
                path, title, duration, track_lang = original_download(url, folder, log)
            finally:
                slot.log = None
            spent = max(time.time() - started, 0.001)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            log(f"Скачивание заняло {module.fmt_dur(spent)}, {size_mb / spent:.1f} МБ/с.")
            return path, title, duration, track_lang

        module.ydl_common = ydl_common
        module.download_audio = download_audio

    module._wy_speed = True


def prepare(settings: dict, log=None) -> None:
    """Один раз грузит модель на видеокарту до первого ролика очереди."""
    global _SPEED_NOTE
    module = load_converter(settings.get("path") or "")
    pin_model(module)
    install_speed(module)
    accurate, note = use_fast_gpu(bool(settings.get("max_accuracy", False)))
    if note and log and not _SPEED_NOTE:
        _SPEED_NOTE = True
        log(note)
    module._CUDA_BROKEN = False
    if not module.cuda_available():
        if log:
            log("Видеокарта недоступна, распознавание пойдёт на процессоре.")
        return
    name, compute = _warm_key(settings, accurate)
    try:
        module.get_model(name, "cuda", compute, log or (lambda _message: None))
    except Exception as exc:
        if log:
            log(f"Не удалось заранее загрузить модель ({exc}). Попробую на первом ролике.")
        return
    if log:
        log(f"Модель «{name}» на видеокарте. Следующие ролики пойдут без повторной загрузки.")


def fetch_audio(url: str, settings: dict, log):
    """Скачивает звук следующего ролика, пока текущий ещё распознаётся."""
    module = load_converter(settings.get("path") or "")
    folder = tempfile.TemporaryDirectory()
    try:
        path, _title, _duration, _lang = module.download_audio(url, folder.name, log)
    except Exception:
        folder.cleanup()
        raise

    def cleanup():
        try:
            folder.cleanup()
        except Exception:
            pass

    return path, cleanup


def load_converter(path: str):
    main_py = converter_file(path)
    key = str(main_py.resolve())
    cached = _MODULES.get(key)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location("videotext_converter", key)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось прочитать конвертер: {main_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULES[key] = module
    return module


def _body(module, paragraphs, translated, mode: str) -> str:
    lines = []

    def block(items):
        for start, text in items:
            lines.append(module.fmt_ts(start, False))
            lines.append(text)
            lines.append("")

    if mode == "ru" and translated is not None:
        block(translated)
    elif mode == "both" and translated is not None:
        lines.append("=== ОРИГИНАЛ ===")
        lines.append("")
        block(paragraphs)
        lines.append("=== ПЕРЕВОД НА РУССКИЙ ===")
        lines.append("")
        block(translated)
    else:
        block(paragraphs)
    return "\n".join(lines).strip() + "\n"


def convert(url: str, settings: dict, progress, cancel: threading.Event, log=None) -> ConvertResult:
    """Ссылка и настройки → текст. Файл на диск пишет уже WhatYouTuber."""
    global _SPEED_NOTE
    module = load_converter(settings.get("path") or "")
    pin_model(module)
    install_speed(module)
    language_name = settings.get("language") or "Авто"
    if language_name not in getattr(module, "LANGS", {}):
        language_name = "Авто"
    model_name = settings.get("model") or "Авто"
    if model_name not in getattr(module, "MODELS", MODELS):
        model_name = "Авто"
    mode_name = settings.get("text_mode") or "Оригинал"
    mode = module.MODES.get(mode_name, "orig")
    accurate, note = use_fast_gpu(bool(settings.get("max_accuracy", False)))
    # Один сбой памяти не должен переводить всю оставшуюся очередь на процессор.
    if gpu_total_mib():
        module._CUDA_BROKEN = False
    _CANCEL.event = cancel
    _AUDIO.on = bool(settings.get("index_audio"))
    state = {"model": "" if model_name == "Авто" else model_name}
    owner = threading.current_thread()

    def bridge_log(message: str):
        text = str(message)
        if log:
            log(text)
        found = re.search(r"(\d+)\s*%", text)
        if found:
            phase = "скачивается" if "скачивание" in text else "распознавание"
            progress(int(found.group(1)) / 100, phase)
        model = re.search(r"Модель:\s*(\S+)", text)
        if model:
            state["model"] = model.group(1)
        if "Скачиваю звук" in text or "Смотрю звуковые" in text:
            progress(0, "скачивается")
        if "Загружаю модель" in text:
            progress(0, "загружаю модель на видеокарту")
        if "Перевожу" in text:
            progress(0.92, "перевод")
        if cancel.is_set() and threading.current_thread() is owner:
            raise Cancelled()

    if note and not _SPEED_NOTE:
        _SPEED_NOTE = True
        bridge_log(note)

    try:
        paragraphs, src_lang, title, duration = module.from_audio(
            url,
            module.LANGS.get(language_name),
            model_name,
            accurate,
            bridge_log,
        )
    except Cancelled:
        raise
    except Exception as exc:
        from core.errors import AppError, diagnose
        if isinstance(exc, AppError):
            raise
        kind, text = diagnose(exc)
        raise AppError(text, kind) from exc
    if cancel.is_set():
        raise Cancelled()
    if not paragraphs or not any((text or "").strip() for _start, text in paragraphs):
        raise RuntimeError("В видео не удалось распознать речь.")

    translated = None
    if mode != "orig":
        if module.is_ru(src_lang):
            translated = paragraphs
            bridge_log("Речь уже на русском, отдельный перевод не нужен.")
        else:
            try:
                translated = module.translate_paragraphs(paragraphs, src_lang, bridge_log)
            except Exception as exc:
                bridge_log(f"Перевод не удался ({exc}). Сохраняю оригинал.")
                translated = paragraphs
                mode = "orig"
    body = _body(module, paragraphs, translated, mode)
    mode_label = {"orig": "оригинал", "ru": "перевод на русский", "both": "оригинал + перевод"}.get(mode, "оригинал")
    model_label = state["model"] or model_name
    return ConvertResult(
        text=body,
        language=src_lang or "",
        model=model_label,
        duration=float(duration or 0),
        title=title or "",
        source=f"конвертер (модель {model_label}, {mode_label})",
        paragraphs=[(float(start), text) for start, text in (paragraphs or [])],
    )
