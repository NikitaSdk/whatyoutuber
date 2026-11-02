"""Вкладка «Поиск»: видео со всех каналов по смыслу запроса."""

import tkinter as tk
import webbrowser
from tkinter import ttk

from core.catalog import watch_url
from core.fmt import fmt_clock
from ui.theme import button


class SearchTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.rows = []
        self._checked = set()

        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        self.summary = ttk.Label(top, text="Введите запрос над вкладками и нажмите Enter.")
        self.summary.pack(side="left")
        ttk.Label(top, text="уровень от").pack(side="left", padx=(16, 4))
        self.min_level = tk.IntVar(value=1)
        spin = ttk.Spinbox(top, from_=1, to=5, textvariable=self.min_level, width=4, command=self._paint)
        spin.pack(side="left")
        self.warn = ttk.Label(top, text="")
        self.warn.pack(side="right")

        self.channels = ttk.Frame(self, padding=(10, 0))
        self.channels.pack(fill="x")
        self._channel_vars = {}

        mid = ttk.Frame(self, padding=(10, 6))
        mid.pack(fill="both", expand=True)
        columns = ("check", "level", "channel", "title", "fragment", "where", "dur")
        self.tree = ttk.Treeview(mid, columns=columns, show="headings", selectmode="browse")
        for key, title, width in (
            ("check", "", 36),
            ("level", "Уровень", 80),
            ("channel", "Канал", 160),
            ("title", "Название", 320),
            ("fragment", "Фрагмент", 140),
            ("where", "Где найдено", 140),
            ("dur", "Длит.", 80),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, stretch=key in {"title", "channel"})
        scroll = ttk.Scrollbar(mid, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<Double-1>", self._open)
        self.tree.bind("<Button-3>", self._menu)

        bottom = ttk.Frame(self, padding=(10, 8))
        bottom.pack(fill="x")
        self.marked = ttk.Label(bottom, text="Отмечено 0 видео")
        self.marked.pack(side="left")
        button(bottom, "В подборку →", self._to_collection, primary=True).pack(side="right")

    def show(self, rows: list, warning: str = ""):
        self.rows = list(rows)
        self._checked = {row["id"] for row in rows}
        self.warn.configure(text=warning)
        self._channel_checks()
        self._paint()

    def _channel_checks(self):
        for child in self.channels.winfo_children():
            child.destroy()
        self._channel_vars = {}
        names = []
        seen = set()
        for row in self.rows:
            if row["channel_id"] in seen:
                continue
            seen.add(row["channel_id"])
            names.append(row)
        if not names:
            return
        ttk.Label(self.channels, text="Каналы:").pack(side="left")
        for row in names:
            var = tk.BooleanVar(value=True)
            self._channel_vars[row["channel_id"]] = var
            ttk.Checkbutton(self.channels, text=row["channel"], variable=var, command=self._paint).pack(side="left", padx=4)

    def _visible(self):
        minimum = int(self.min_level.get() or 1)
        allowed = {key for key, var in self._channel_vars.items() if var.get()} or None
        rows = []
        for row in self.rows:
            if row["level"] < minimum:
                continue
            if allowed is not None and row["channel_id"] not in allowed:
                continue
            rows.append(row)
        return rows

    def _paint(self):
        self.tree.delete(*self.tree.get_children())
        shown = self._visible()
        channels = {row["channel_id"] for row in shown}
        self.summary.configure(text=f"Найдено {len(shown)} видео в {len(channels)} каналах")
        for row in shown:
            mark = "☑" if row["id"] in self._checked else "☐"
            stars = "★" * row["level"] + "☆" * (5 - row["level"])
            fragment = row["fragment"]
            self.tree.insert("", "end", iid=row["id"], values=(
                mark, stars, row["channel"], row["title"], fragment, row["where"], row["dur"],
            ))
        visible = {row["id"] for row in shown}
        self.marked.configure(text=f"Отмечено {len(self._checked & visible)} видео")

    def _row(self, video_id):
        return next((row for row in self.rows if row["id"] == video_id), None)

    def _click(self, event):
        row_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not row_id or column != "#1":
            return
        if row_id in self._checked:
            self._checked.discard(row_id)
        else:
            self._checked.add(row_id)
        self._paint()
        return "break"

    def _open(self, _event):
        selected = self.tree.selection()
        if not selected:
            return
        row = self._row(selected[0])
        if not row:
            return
        webbrowser.open(f"{watch_url(row['id'])}&t={int(row['start'])}s")

    def _menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        row = self._row(row_id)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Все упоминания", command=lambda: self._moments(row))
        menu.add_command(label="Открыть канал в программе", command=lambda: self.app.open_saved(row["channel_id"]))
        menu.tk_popup(event.x_root, event.y_root)

    def _moments(self, row):
        window = tk.Toplevel(self)
        window.title(row["title"] or "Упоминания")
        window.geometry("360x280")
        box = tk.Listbox(window, font=("Segoe UI", 10))
        box.pack(fill="both", expand=True)
        stamps = row.get("moments") or [row["start"]]
        for stamp in stamps:
            box.insert("end", fmt_clock(stamp))
        def open_stamp(_event=None):
            picked = box.curselection()
            if not picked:
                return
            second = stamps[picked[0]]
            webbrowser.open(f"{watch_url(row['id'])}&t={int(second)}s")
        box.bind("<Double-1>", open_stamp)

    def _to_collection(self):
        visible = {row["id"] for row in self._visible()}
        chosen = [row for row in self.rows if row["id"] in self._checked and row["id"] in visible]
        if not chosen:
            return
        self.app.save_topic(chosen)
