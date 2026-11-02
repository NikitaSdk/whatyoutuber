"""Вкладка «Канал»: ссылка, карточка, списки слева и таблица видео."""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from core.auth import describe_auth, pill
from core.catalog import build_groups
from core.filters import DURATIONS, PERIODS, period_label, visible_ids
from core.fmt import fmt_clock, fmt_date, fmt_hm, fmt_scanned, initials, plural
from core.selection import export_order, group_mark, summary
from ui.check_tree import CheckTree
from ui.theme import BG, BLUE, GREEN, INK, LINE, MUTED, RED, SELECT, WHITE, button


class ChannelTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self._keys = None
        self._rows = {}
        self._groups = []
        self.search = tk.StringVar()
        self.exclude = tk.StringVar()
        self.duration = tk.StringVar(value=DURATIONS[0][0])
        self.period = tk.StringVar(value=PERIODS[0][0])
        self.subs = tk.BooleanVar(value=False)
        self._syncing = False
        self.sort_name = "num"
        self.sort_reverse = False
        self._filter_job = None
        for var in (self.search, self.exclude, self.duration, self.period):
            var.trace_add("write", self._schedule_table)
        self.subs.trace_add("write", lambda *_: self.app.subtitle_search_changed())

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        side = tk.Frame(body, bg=WHITE, width=168, highlightbackground=LINE, highlightthickness=1)
        side.pack(side="left", fill="y", padx=(0, 8))
        side.pack_propagate(False)
        self.side = side
        tk.Label(side, text="МОИ КАНАЛЫ", bg=WHITE, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=8, pady=(8, 4))
        self.channels = tk.Listbox(side, bd=0, highlightthickness=0, activestyle="none", font=("Segoe UI", 9), bg=WHITE, fg=INK)
        self.channels.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        self.channels.bind("<<ListboxSelect>>", self._pick_channel)
        self.channels.bind("<Motion>", self._channel_hint)
        self.channels.bind("<Leave>", lambda _e: self._hide_hint())
        self._hint = None
        self._channel_ids = []

        main = ttk.Frame(body)
        main.pack(side="left", fill="both", expand=True)

        link = ttk.Frame(main)
        link.pack(fill="x")
        ttk.Label(link, text="Ссылка на канал:").pack(side="left")
        self.url = tk.StringVar()
        entry = ttk.Entry(link, textvariable=self.url)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        entry.bind("<Return>", lambda _e: self.app.toggle_scan())
        button(link, "Вставить", self.app.paste).pack(side="left")
        self.scan_btn = button(link, "Сканировать", self.app.toggle_scan, primary=True)
        self.scan_btn.pack(side="left", padx=(6, 0))

        self.card = tk.Frame(main, bg=WHITE, highlightbackground=LINE, highlightthickness=1)
        self.card.pack(fill="x", pady=(8, 8))
        self.avatar = tk.Canvas(self.card, width=42, height=42, bg=WHITE, highlightthickness=0)
        self.avatar.pack(side="left", padx=10, pady=10)
        text = tk.Frame(self.card, bg=WHITE)
        text.pack(side="left", fill="x", expand=True, pady=8)
        self.card_title = tk.Label(text, text="Канал ещё не выбран", bg=WHITE, fg=INK, font=("Segoe UI", 12, "bold"), anchor="w")
        self.card_title.pack(anchor="w")
        self.card_meta = tk.Label(text, text="Вставьте ссылку и нажмите «Сканировать».", bg=WHITE, fg=MUTED, anchor="w")
        self.card_meta.pack(anchor="w")
        index_row = tk.Frame(text, bg=WHITE)
        index_row.pack(anchor="w", fill="x")
        self.index_line = tk.Label(index_row, text="", bg=WHITE, fg=MUTED, anchor="w")
        self.index_line.pack(side="left")
        self.index_btn = tk.Label(index_row, text="", bg=WHITE, fg=BLUE, cursor="hand2")
        self.index_btn.pack(side="left", padx=(8, 0))
        self.index_btn.bind("<Button-1>", lambda _e: self.app.start_index_asr())
        actions = tk.Frame(self.card, bg=WHITE)
        actions.pack(side="right", padx=10)
        self.pill_dot = tk.Canvas(actions, width=10, height=10, bg=WHITE, highlightthickness=0)
        self.pill_dot.pack(side="left", padx=(0, 4))
        self.pill = tk.Label(actions, text="", bg=WHITE, fg=MUTED)
        self.pill.pack(side="left")
        tk.Label(actions, text="Настроить вход", bg=WHITE, fg=BLUE, cursor="hand2").pack(side="left", padx=10)
        actions.winfo_children()[-1].bind("<Button-1>", lambda _e: self.app.open_login())
        self.update_btn = button(actions, "Обновить канал", self.app.update_channel)
        self.update_btn.pack(side="left", padx=(4, 0))

        panes = ttk.Panedwindow(main, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = tk.Frame(panes, bg=WHITE, highlightbackground=LINE, highlightthickness=1)
        right = tk.Frame(panes, bg=WHITE, highlightbackground=LINE, highlightthickness=1)
        panes.add(left, weight=1)
        panes.add(right, weight=4)

        self.left_canvas = tk.Canvas(left, bg=WHITE, highlightthickness=0, width=280)
        left_scroll = ttk.Scrollbar(left, orient="vertical", command=self.left_canvas.yview)
        self.left_inner = tk.Frame(self.left_canvas, bg=WHITE)
        self.left_inner.bind("<Configure>", lambda _e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))
        self._left_window = self.left_canvas.create_window((0, 0), window=self.left_inner, anchor="nw")
        self.left_canvas.bind("<Configure>", self._fit_left)
        self.left_canvas.configure(yscrollcommand=left_scroll.set)
        self.left_canvas.pack(side="left", fill="both", expand=True)
        left_scroll.pack(side="right", fill="y")
        self.left_canvas.bind("<Enter>", lambda _e: self.left_canvas.bind_all("<MouseWheel>", self._wheel))
        self.left_canvas.bind("<Leave>", lambda _e: self.left_canvas.unbind_all("<MouseWheel>"))
        hint = tk.Label(
            left,
            text="Галочка — взять целиком.\nКлик по названию — посмотреть видео и выбрать отдельные.",
            bg="#f8fafc", fg=MUTED, justify="left", anchor="w", padx=8, pady=8, font=("Segoe UI", 8),
        )
        hint.pack(side="bottom", fill="x")

        head = tk.Frame(right, bg=WHITE)
        head.pack(fill="x", padx=8, pady=(8, 0))
        titles = tk.Frame(head, bg=WHITE)
        titles.pack(side="left", fill="x", expand=True)
        self.view_title = tk.Label(titles, text="", bg=WHITE, fg=INK, font=("Segoe UI", 12, "bold"), anchor="w")
        self.view_title.pack(anchor="w")
        self.view_meta = tk.Label(titles, text="", bg=WHITE, fg=MUTED, anchor="w")
        self.view_meta.pack(anchor="w")
        tools = tk.Frame(head, bg=WHITE)
        tools.pack(side="right")
        button(tools, "Отметить все", self.app.mark_all).pack(side="left", padx=2)
        button(tools, "Снять все", self.app.clear_all).pack(side="left", padx=2)
        button(tools, "Инвертировать", self.app.invert_visible).pack(side="left", padx=2)
        button(tools, "Открыть на YouTube", self.app.open_current).pack(side="left", padx=2)

        filters = tk.Frame(right, bg=WHITE)
        filters.pack(fill="x", padx=8, pady=8)
        search = ttk.Entry(filters, textvariable=self.search)
        search.pack(side="left", fill="x", expand=True)
        self._placeholder(search, "Поиск по названию и описанию")
        exclude = ttk.Entry(filters, textvariable=self.exclude, width=24)
        exclude.pack(side="left", padx=6)
        self._placeholder(exclude, "Исключить слова: анонс, розыгрыш")
        ttk.Combobox(filters, textvariable=self.duration, values=[name for name, _v in DURATIONS], width=20, state="readonly").pack(side="left")
        ttk.Checkbutton(filters, text="искать в субтитрах", variable=self.subs).pack(side="left", padx=8)
        extra = tk.Frame(right, bg=WHITE)
        extra.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Combobox(extra, textvariable=self.period, values=[name for name, _v in PERIODS], width=18, state="readonly").pack(side="left")
        self.period_note = tk.Label(extra, text="", bg=WHITE, fg=MUTED)
        self.period_note.pack(side="left", padx=8)
        button(extra, "Отметить найденные", self.app.mark_found).pack(side="right")
        self.table = CheckTree(right, self.app.toggle_video, self.app.open_video, self.app.video_menu, self._sort)
        self.table.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        foot = tk.Frame(main, bg=BG)
        foot.pack(fill="x", pady=(8, 0))
        info = tk.Frame(foot, bg=BG)
        info.pack(side="left", fill="x", expand=True)
        self.total = tk.Label(info, text="Отмечено: 0 видео · 0 мин", bg=BG, fg=INK, font=("Segoe UI", 10, "bold"), anchor="w")
        self.total.pack(anchor="w")
        self.detail = tk.Label(info, text="", bg=BG, fg=MUTED, anchor="w")
        self.detail.pack(anchor="w")
        button(foot, "Перевести в текст →", lambda: self.app.save_lists(True), primary=True).pack(side="right")
        button(foot, "Сохранить списки (ссылки, названия, таблица)", lambda: self.app.save_lists(False)).pack(side="right", padx=(0, 8))
        self._draw_avatar("?")
        self._paint_pill()

    def _placeholder(self, entry, text):
        def show(_event=None):
            if not entry.get():
                entry.configure(foreground="#98a2b3")
                entry.insert(0, text)
        def hide(_event=None):
            if entry.get() == text:
                entry.delete(0, "end")
                entry.configure(foreground="#1f2933")
        entry.bind("<FocusIn>", hide)
        entry.bind("<FocusOut>", show)
        show()

    def set_scanning(self, active: bool):
        self.scan_btn.configure(text="Остановить" if active else "Сканировать")

    def set_status(self, text: str):
        if text:
            self.card_meta.configure(text=text)

    def _fit_left(self, event):
        if event.width > 1:
            self.left_canvas.itemconfigure(self._left_window, width=event.width)

    def repaint(self):
        """После возврата из панели задач Windows оставляет холсты чёрными, пока их не нарисовать заново."""
        self._fill_card()
        self._paint_pill()
        width = self.left_canvas.winfo_width()
        if width > 1:
            self.left_canvas.itemconfigure(self._left_window, width=width)
        box = self.left_canvas.bbox("all")
        if box:
            self.left_canvas.configure(scrollregion=box)

    def _wheel(self, event):
        self.left_canvas.yview_scroll(int(-event.delta / 120), "units")

    def set_index(self, text: str, no_text: int = 0):
        self.index_line.configure(text=text or "")
        self.index_btn.configure(text="Распознать без субтитров" if no_text else "")

    def _hide_hint(self):
        if self._hint is not None:
            self._hint.destroy()
            self._hint = None

    def _channel_hint(self, event):
        self._hide_hint()
        index = self.channels.nearest(event.y)
        if index < 0 or index >= len(self._channel_ids):
            return
        name = self.channels.get(index)
        font = tkfont.Font(font=self.channels.cget("font"))
        if font.measure(name) <= self.channels.winfo_width():
            return
        tip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tk.Label(tip, text=name, bg="#111827", fg="white", padx=6, pady=3).pack()
        tip.geometry(f"+{event.x_root + 12}+{event.y_root + 12}")
        self._hint = tip

    def _pick_channel(self, _event):
        self.channels.xview_moveto(0)
        selection = self.channels.curselection()
        if not selection:
            return
        self.app.open_saved(self._channel_ids[selection[0]])

    def _schedule_table(self, *_args):
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(160, self._apply_table)

    def _apply_table(self):
        self._filter_job = None
        self.reload_table()

    def _sort(self, name, reverse):
        self.sort_name = name
        self.sort_reverse = reverse
        self.reload_table()

    def current_filters(self):
        search = self.search.get().strip()
        exclude = self.exclude.get().strip()
        if search.startswith("Поиск по названию"):
            search = ""
        if exclude.startswith("Исключить слова"):
            exclude = ""
        duration = dict(DURATIONS).get(self.duration.get())
        period = dict(PERIODS).get(self.period.get())
        return search, exclude, duration, period, self.subs.get()

    def reload(self, structure: bool = False):
        if not hasattr(self, "table"):
            return
        self._fill_channels()
        self._fill_card()
        self._paint_pill()
        channel = self.app.channel
        groups = build_groups(channel) if channel else []
        self._groups = groups
        signature = tuple((key, title, tuple(ids)) for key, title, ids in groups)
        if not channel:
            for child in self.left_inner.winfo_children():
                child.destroy()
            self._rows = {}
            self._keys = signature
        elif structure or signature != self._keys:
            self._keys = signature
            self._build_left(groups)
        else:
            self._sync_left(groups)
        self.reload_table()

    def _fill_channels(self):
        rows = self.app.saved_channels
        ids = [row["id"] for row in rows]
        if ids == self._channel_ids and self.channels.size() == len(ids):
            return
        self._channel_ids = ids
        self.channels.delete(0, "end")
        names = [row["title"] or row["handle"] or row["id"] for row in rows]
        for name in names:
            self.channels.insert("end", name)
        font = tkfont.Font(font=self.channels.cget("font"))
        need = max((font.measure(name) for name in names), default=0) + 32
        self.side.configure(width=max(168, min(340, need)))
        self.channels.xview_moveto(0)

    def _fill_card(self):
        channel = self.app.channel
        if not channel:
            self._draw_avatar("?")
            self.card_title.configure(text="Канал ещё не выбран")
            self.card_meta.configure(text="Вставьте ссылку и нажмите «Сканировать».")
            return
        self._draw_avatar(initials(channel.title))
        handle = f"@{channel.handle}" if channel.handle else channel.url
        videos = len(channel.tabs.get("videos") or [])
        streams = len(channel.tabs.get("streams") or [])
        shorts = len(channel.tabs.get("shorts") or [])
        playlists = len(channel.playlists)
        when = fmt_scanned(channel.scanned_at)
        scanned = f" · отсканировано {when}" if when else ""
        playlists_word = plural(playlists, "плейлист", "плейлиста", "плейлистов")
        streams_word = plural(streams, "стрим", "стрима", "стримов")
        self.card_title.configure(text=channel.title or "Канал")
        self.card_meta.configure(
            text=f"{handle} · {videos} видео · {streams} {streams_word} · {shorts} Shorts · {playlists} {playlists_word}{scanned}"
        )

    def _draw_avatar(self, letters: str):
        self.avatar.delete("all")
        self.avatar.create_oval(2, 2, 40, 40, fill=BLUE, outline=BLUE)
        self.avatar.create_text(21, 21, text=letters[:2], fill="white", font=("Segoe UI", 9, "bold"))

    def _paint_pill(self):
        text, color = pill(self.app.settings.auth)
        fg = {"green": GREEN, "red": RED, "gray": MUTED}[color]
        dot = {"green": GREEN, "red": RED, "gray": "#c5c9d2"}[color]
        self.pill.configure(text=text, fg=fg)
        self.pill_dot.delete("all")
        self.pill_dot.create_oval(1, 1, 9, 9, fill=dot, outline=dot)

    def _build_left(self, groups):
        for child in self.left_inner.winfo_children():
            child.destroy()
        self._rows = {}
        sections = [item for item in groups if item[0].startswith("tab:")]
        playlists = [item for item in groups if item[0].startswith("pl:") or item[0] == "loose"]
        self._section_label("РАЗДЕЛЫ КАНАЛА")
        for item in sections:
            self._add_row(item)
        self._section_label("ПЛЕЙЛИСТЫ")
        if not any(item[0].startswith("pl:") for item in groups):
            tk.Label(self.left_inner, text="У канала нет плейлистов", bg=WHITE, fg=MUTED, anchor="w").pack(fill="x", padx=8, pady=2)
        for item in playlists:
            self._add_row(item)
        self._sync_left(groups)

    def _section_label(self, text):
        tk.Label(self.left_inner, text=text, bg=WHITE, fg=MUTED, font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=8, pady=(8, 2))

    def _add_row(self, item):
        key, _title, _ids = item
        row = tk.Frame(self.left_inner, bg=WHITE)
        row.pack(fill="x", padx=4, pady=1)
        var = tk.IntVar(value=0)
        check = ttk.Checkbutton(row, variable=var, command=lambda k=key: self._click_group(k))
        check.pack(side="left")
        title = tk.Label(row, text="", bg=WHITE, fg=INK, anchor="w", cursor="hand2")
        title.pack(side="left", fill="x", expand=True)
        title.bind("<Button-1>", lambda _e, k=key: self.app.select_nav(k))
        count = tk.Label(row, text="", bg=WHITE, fg=MUTED, anchor="e")
        count.pack(side="right", padx=(4, 6))
        row.bind("<Button-1>", lambda _e, k=key: self.app.select_nav(k))
        self._rows[key] = {"frame": row, "var": var, "title": title, "count": count, "check": check}

    def _click_group(self, key):
        if self._syncing:
            return
        self.app.click_group(key)

    def _sync_left(self, groups):
        manual = self.app.manual
        current = self.app.nav_key
        self._syncing = True
        try:
            for key, title, ids in groups:
                widgets = self._rows.get(key)
                if not widgets:
                    continue
                mark = group_mark(manual, ids)
                widgets["var"].set({"on": 1, "off": 0, "partial": 0}[mark])
                state = ["alternate"] if mark == "partial" else ["!alternate"]
                try:
                    widgets["check"].state(state)
                except tk.TclError:
                    pass
                got = sum(1 for video_id in ids if video_id in manual)
                widgets["count"].configure(text=f"{got} из {len(ids)}" if got and got < len(ids) else str(len(ids)))
                widgets["title"].configure(text=title)
                bg = SELECT if key == current else WHITE
                widgets["frame"].configure(bg=bg)
                widgets["title"].configure(bg=bg)
                widgets["count"].configure(bg=bg)
        finally:
            self._syncing = False

    def current_ids(self):
        for key, _title, ids in self._groups:
            if key == self.app.nav_key:
                return list(ids), _title
        if self._groups:
            return list(self._groups[0][2]), self._groups[0][1]
        return [], ""

    def reload_table(self):
        if not hasattr(self, "table"):
            return
        channel = self.app.channel
        ids, title = self.current_ids()
        if not channel:
            self.view_title.configure(text="")
            self.view_meta.configure(text="")
            self.table.set_rows([])
            self._footer([])
            return
        search, exclude, duration, period, subs = self.current_filters()
        subtitle_text = self.app.subtitle_text if subs and search.strip() else {}
        shown = visible_ids(ids, channel.videos, search, exclude, duration, period, subtitle_text)
        self.period_note.configure(text=period_label(ids, channel.videos))
        rows = [self._row(video_id, index + 1, title) for index, video_id in enumerate(ids)]
        by_id = {row["id"]: row for row in rows}
        visible = [by_id[video_id] for video_id in shown if video_id in by_id]
        visible.sort(key=self._sort_key, reverse=self.sort_reverse and self.sort_name != "num")
        if self.sort_name == "num" and self.sort_reverse:
            visible.reverse()
        self.table.set_rows(visible)
        marked = sum(1 for video_id in ids if video_id in self.app.manual)
        seconds = sum(int(channel.videos[video_id].duration_sec or 0) for video_id in ids if video_id in channel.videos)
        self.view_title.configure(text=title)
        self.view_meta.configure(text=f"{len(ids)} видео · {fmt_hm(seconds)} · отмечено {marked}")
        self._footer(build_groups(channel))

    def refresh_row(self, video_id: str):
        ids, title = self.current_ids()
        if video_id not in ids or not self.table.tree.exists(video_id):
            self.period_note.configure(text=period_label(ids, self.app.channel.videos) if self.app.channel else "")
            return
        self.table.update_row(self._row(video_id, ids.index(video_id) + 1, title))

    def _row(self, video_id: str, number: int, playlist_title: str) -> dict:
        video = self.app.channel.videos[video_id]
        bits = []
        if video.availability == "18+":
            bits.append("18+")
        if video.is_new:
            bits.append("новое")
        if video.foreign_channel:
            bits.append("с другого канала")
        if video.removed_from_channel:
            bits.append("удалено")
        name = video.title or video_id
        if bits:
            name = " · ".join(bits) + "  " + name
        snippet = self.app.snippets.get(video_id) or ""
        if snippet and self.subs.get() and self.search.get().strip():
            name = f"{name}    {snippet}"
        status = self.app.status_of(video)
        from core.visual import _KIND, presentation_links
        if video.visual_kind:
            status = f"{status} · {_KIND.get(video.visual_kind, video.visual_kind)}"
        if presentation_links(video.description):
            status = f"{status} · есть презентация"
        if self.subs.get() and self.search.get().strip() and video.has_subtitles is False and not snippet:
            status = "нет субтитров"
        dim = video.availability == "unavailable" or video.removed_from_channel
        return {
            "id": video_id,
            "checked": video_id in self.app.manual,
            "num": number,
            "title": name,
            "playlist": playlist_title,
            "date": fmt_date(video.upload_date),
            "dur": fmt_clock(video.duration_sec) if video.duration_sec else "",
            "status": status,
            "dim": dim,
        }

    def _sort_key(self, row):
        name = self.sort_name
        if name == "title":
            return row["title"].lower()
        if name == "date":
            return row["date"]
        if name == "dur":
            parts = [int(p) for p in (row["dur"] or "0").split(":") if p.isdigit()]
            acc = 0
            for part in parts:
                acc = acc * 60 + part
            return acc
        if name == "status":
            return row["status"]
        if name == "playlist":
            return row["playlist"].lower()
        return row["num"]

    def _footer(self, groups):
        channel = self.app.channel
        if not channel:
            self.total.configure(text="Отмечено: 0 видео · 0 мин")
            self.detail.configure(text="")
            return
        info = summary(groups, self.app.manual, channel.videos, self.app.ready_ids())
        self.total.configure(text=f"Отмечено: {info['count']} видео · {fmt_hm(info['seconds'])}")
        self.detail.configure(
            text=(
                f"плейлистов целиком: {info['whole_playlists']} · отдельных видео: {info['individual']} · "
                f"уже есть текст: {info['ready']} (будут пропущены) · 18+: {info['adult']} ({describe_auth(self.app.settings.auth)})"
            )
        )

    def visible_video_ids(self):
        return list(self.table.tree.get_children())
