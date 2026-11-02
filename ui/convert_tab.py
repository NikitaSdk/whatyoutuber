"""Вкладка «Конвертация»: настройки конвертера, очередь и журнал."""

import tkinter as tk
from tkinter import ttk

from core.converter_bridge import FAST_VRAM_MIB, LANGS, MODELS, MODES, gpu_total_mib
from core.fmt import fmt_clock, fmt_eta
from ui.theme import BG, INK, MUTED, button


class ConvertTab(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=BG, highlightthickness=0, bd=0)
        self.app = app
        converter = app.settings.converter or {}
        top = tk.Frame(self, bg=BG, highlightthickness=0, bd=0)
        top.pack(fill="x", padx=10, pady=(8, 4))
        self.language = tk.StringVar(value=converter.get("language") or "Авто")
        self.model = tk.StringVar(value=converter.get("model") or "Авто")
        self.mode = tk.StringVar(value=converter.get("text_mode") or "Оригинал")
        memory = gpu_total_mib()
        self.small_gpu = bool(memory and memory <= FAST_VRAM_MIB)
        self.accurate = tk.BooleanVar(value=False if self.small_gpu else bool(converter.get("max_accuracy", False)))
        self.fast = tk.BooleanVar(value=bool(app.settings.fast_subtitles))
        self.shutdown = tk.BooleanVar(value=bool(app.settings.shutdown_after))

        tk.Label(top, text="Язык видео:", bg=BG, fg=INK, font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(top, textvariable=self.language, values=LANGS, width=16, state="readonly").pack(side="left", padx=(4, 10))
        tk.Label(top, text="Модель:", bg=BG, fg=INK, font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(top, textvariable=self.model, values=MODELS, width=16, state="readonly").pack(side="left", padx=(4, 10))
        tk.Label(top, text="Текст:", bg=BG, fg=INK, font=("Segoe UI", 9)).pack(side="left")
        for name in MODES:
            ttk.Radiobutton(top, text=name, value=name, variable=self.mode).pack(side="left", padx=(6, 0))

        checks = tk.Frame(self, bg=BG, highlightthickness=0, bd=0)
        checks.pack(fill="x", padx=10)
        accuracy_text = "Максимальная точность (чуть медленнее)"
        if self.small_gpu:
            gb = max(1, int(round(memory / 1024)))
            accuracy_text = f"Точный режим выключен: видеокарте {gb} ГБ он не по силам"
        accuracy = ttk.Checkbutton(checks, text=accuracy_text, variable=self.accurate)
        accuracy.pack(side="left")
        if self.small_gpu:
            accuracy.state(["disabled"])
        ttk.Checkbutton(checks, text="Сначала субтитры YouTube", variable=self.fast).pack(side="left", padx=12)
        ttk.Checkbutton(checks, text="Выключить компьютер после завершения", variable=self.shutdown).pack(side="left")
        slides = tk.Frame(self, bg=BG, highlightthickness=0, bd=0)
        slides.pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(slides, text="Слайды и доска:", bg=BG, fg=INK, font=("Segoe UI", 9)).pack(side="left")
        self.visual = tk.StringVar(value="off")
        for value, label in (("off", "выкл"), ("auto", "авто"), ("on", "всегда")):
            ttk.Radiobutton(slides, text=label, value=value, variable=self.visual).pack(side="left", padx=(8, 0))
        self.formulas = tk.BooleanVar(value=False)
        ttk.Checkbutton(slides, text="Формулы (нужен pix2tex)", variable=self.formulas).pack(side="left", padx=12)

        table_frame = tk.Frame(self, bg=BG, highlightthickness=0, bd=0)
        table_frame.pack(fill="both", expand=True, padx=10, pady=8)
        columns = ("num", "title", "dur", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        for key, title, width in (("num", "№", 50), ("title", "Название", 520), ("dur", "Длительность", 110), ("status", "Статус", 220)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w", stretch=key == "title")
        scroll = ttk.Scrollbar(table_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        bars = tk.Frame(self, bg=BG, highlightthickness=0, bd=0)
        bars.pack(fill="x", padx=10)
        self.current_label = tk.Label(bars, text="Текущее видео", bg=BG, fg=INK, font=("Segoe UI", 9), anchor="w")
        self.current_label.pack(anchor="w", fill="x")
        self.current = ttk.Progressbar(bars, maximum=1)
        self.current.pack(fill="x", pady=(0, 4))
        self.overall_label = tk.Label(bars, text="Очередь", bg=BG, fg=INK, font=("Segoe UI", 9), anchor="w")
        self.overall_label.pack(anchor="w", fill="x")
        self.overall = ttk.Progressbar(bars, maximum=1)
        self.overall.pack(fill="x")

        actions = tk.Frame(self, bg=BG, highlightthickness=0, bd=0)
        actions.pack(fill="x", padx=10, pady=8)
        self.start_btn = button(actions, "Старт", self.app.start_queue, primary=True)
        self.start_btn.pack(side="left")
        self.pause_btn = button(actions, "Пауза", self.app.pause_queue)
        self.pause_btn.pack(side="left", padx=6)
        button(actions, "Стоп", self.app.stop_queue).pack(side="left")
        button(actions, "Повторить ошибочные", self.app.retry_failed).pack(side="left", padx=6)

        self.logbox = tk.Text(self, height=8, wrap="word", state="disabled", bg="white", fg=INK, font=("Segoe UI", 9), relief="flat")
        self.logbox.pack(fill="both", expand=False, padx=10, pady=(0, 10))

    def settings_dict(self) -> dict:
        data = dict(self.app.settings.converter or {})
        data.update({
            "language": self.language.get(),
            "model": self.model.get(),
            "text_mode": self.mode.get(),
            "max_accuracy": bool(self.accurate.get()),
        })
        return data

    def set_items(self, items, videos):
        self.tree.delete(*self.tree.get_children())
        for item in items:
            if isinstance(item, dict):
                video_id = item.get("video_id")
                number = int(item.get("number") or 0)
                status = item.get("status") or ""
                error = item.get("error") or ""
            else:
                video_id = item.video_id
                number = int(item.number or 0)
                status = item.status
                error = item.error or ""
            video = videos.get(video_id)
            title = video.title if video else (video_id or "")
            dur = fmt_clock(video.duration_sec) if video and video.duration_sec else ""
            self.tree.insert("", "end", iid=video_id or str(number), values=(f"{number:03d}", title, dur, self._label(status, error)))

    def _label(self, status, error):
        names = {
            "waiting": "ждёт",
            "running": "распознаётся",
            "done": "готово",
            "error": "ошибка",
            "skipped": "пропущено",
            "need_login": "нужен вход",
        }
        text = names.get(status, status)
        if error and status in {"error", "skipped", "need_login"}:
            text = f"{text}: {error}"
        return text

    def update_status(self, video_id: str, status: str, error: str = ""):
        if not video_id or not self.tree.exists(video_id):
            return
        values = list(self.tree.item(video_id, "values"))
        if len(values) < 4:
            return
        values[3] = self._label(status, error)
        self.tree.item(video_id, values=values)

    def log(self, message: str):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", message + "\n")
        lines = int(self.logbox.index("end-1c").split(".")[0])
        if lines > 400:
            self.logbox.delete("1.0", f"{lines - 300}.0")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def clear_log(self):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")

    def set_progress(self, fraction, phase, index, total, eta):
        self.current["value"] = fraction or 0
        phase_text = {
            "скачивается": "скачивается",
            "распознавание": "распознаётся",
            "перевод": "переводится",
            "загружаю модель на видеокарту": "модель загружается на видеокарту",
        }.get(phase, phase or "")
        if phase == "распознавание" and fraction:
            phase_text = f"распознаётся {int(fraction * 100)}%"
        self.current_label.configure(text=f"Текущее видео · {phase_text}".strip())
        overall = 0
        if total:
            overall = min(1, ((index - 1) + (fraction or 0)) / total)
        self.overall["value"] = overall
        eta_text = f"осталось примерно {fmt_eta(eta)}" if eta else "оставшееся время станет точнее после первых видео"
        self.overall_label.configure(text=f"Видео {index} из {total} · {eta_text}")

    def set_paused(self, paused: bool):
        self.pause_btn.configure(text="Продолжить" if paused else "Пауза")
