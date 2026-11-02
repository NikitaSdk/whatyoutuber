"""Папка данных, путь к конвертеру, пауза и состояние программ."""

import threading
import tkinter as tk
from tkinter import filedialog, ttk

from ui.theme import BG, button


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, settings, components, on_save, on_update):
        super().__init__(master)
        self.title("Настройки")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.settings = settings
        self.on_save = on_save
        self.on_update = on_update
        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Папка данных WhatYouTuber").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(2, 8))
        self.data_dir = tk.StringVar(value=settings.data_dir)
        ttk.Entry(row, textvariable=self.data_dir).pack(side="left", fill="x", expand=True)
        button(row, "Обзор…", self._pick_data).pack(side="left", padx=(6, 0))

        ttk.Label(frame, text="Папка конвертера «Видео → текст» (там лежит main.py)").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(2, 8))
        self.converter = tk.StringVar(value=(settings.converter or {}).get("path") or "")
        ttk.Entry(row, textvariable=self.converter).pack(side="left", fill="x", expand=True)
        button(row, "Обзор…", self._pick_converter).pack(side="left", padx=(6, 0))

        pause_row = ttk.Frame(frame)
        pause_row.pack(fill="x", pady=(0, 8))
        ttk.Label(pause_row, text="Пауза между видео, сек").pack(side="left")
        self.pause = tk.IntVar(value=int(settings.pause_between_sec or 0))
        ttk.Spinbox(pause_row, from_=0, to=600, textvariable=self.pause, width=6).pack(side="left", padx=8)

        ttk.Label(frame, text="Имя файла с текстом").pack(anchor="w")
        self.style = tk.StringVar(value=settings.filename_style or "number")
        ttk.Radiobutton(frame, text="001 - Название", value="number", variable=self.style).pack(anchor="w")
        ttk.Radiobutton(frame, text="2023-02-14 - Название", value="date", variable=self.style).pack(anchor="w")
        self.header = tk.BooleanVar(value=bool(settings.file_header))
        ttk.Checkbutton(frame, text="Шапка в начале txt (название, канал, ссылка)", variable=self.header).pack(anchor="w", pady=(6, 8))

        ttk.Label(frame, text="Компоненты").pack(anchor="w")
        self.comp = tk.Label(frame, text=self._lines(components), bg=BG, justify="left", anchor="w", font=("Segoe UI", 9))
        self.comp.pack(anchor="w", fill="x", pady=(2, 8))

        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        button(actions, "Обновить yt-dlp", self._update).pack(side="left")
        ttk.Label(actions, text="та же среда, что у конвертера").pack(side="left", padx=8)
        button(actions, "Сохранить", self._save, primary=True).pack(side="right")
        button(actions, "Закрыть", self.destroy).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())

    def _lines(self, components) -> str:
        parts = []
        for row in components:
            mark = "✓" if row.ok else "✗"
            parts.append(f"{row.title} {mark}  {row.detail}")
        return "\n".join(parts)

    def _pick_data(self):
        path = filedialog.askdirectory(parent=self, initialdir=self.data_dir.get() or None)
        if path:
            self.data_dir.set(path)

    def _pick_converter(self):
        path = filedialog.askdirectory(parent=self, initialdir=self.converter.get() or None)
        if path:
            self.converter.set(path)

    def _save(self):
        self.on_save({
            "data_dir": self.data_dir.get().strip(),
            "converter": self.converter.get().strip(),
            "pause": int(self.pause.get() or 0),
            "style": self.style.get(),
            "header": bool(self.header.get()),
        })
        self.destroy()

    def _update(self):
        self.comp.configure(text="Обновляю yt-dlp… окно можно не закрывать.")
        self.update_idletasks()

        def work():
            try:
                code, output, components = self.on_update()
            except Exception as exc:
                code, output, components = 1, str(exc), []
            self.after(0, lambda: self._update_done(code, output, components))

        threading.Thread(target=work, daemon=True).start()

    def _update_done(self, code, output, components):
        if not self.winfo_exists():
            return
        tail = "Готово." if code == 0 else "Не удалось обновить."
        text = tail + "\n" + self._lines(components)
        if output:
            text += "\n\n" + output[-800:]
        self.comp.configure(text=text)
