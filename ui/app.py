"""Главное окно. Долгие задачи кладут события в очередь, окно забирает их само."""

import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from core.auth import check_login
from core.catalog import build_groups, group_by_key, watch_url
from core.components import check_components, missing_banner, update_ytdlp
from core.converter_bridge import convert, fetch_audio, prepare
from core.errors import Cancelled
from core.export import assign_numbers, file_ready, text_path, write_lists, write_toc
from core.models import Collection
from core.queue_runner import build_items, retry_failed, run as run_queue
from core.scanner import scan
from core.selection import export_order, group_mark, set_group, toggle_one, invert, check_only_visible, whole_playlist_ids
from core.storage import (
    append_log, bootstrap_exists, list_channels, list_collections, load_channel,
    load_collection, load_queue, save_channel, save_collection, save_settings, subtitle_cache, topics_root,
)
from core.subtitles import body_from_cache, fetch, search_current
from ui.channel_tab import ChannelTab
from ui.convert_tab import ConvertTab
from ui.login_dialog import LoginDialog
from ui.results_tab import ResultsTab
from ui.search_tab import SearchTab
from ui.settings_dialog import SettingsDialog
from ui.theme import AMBER, AMBER_BG, BG, apply, button


class App(tk.Tk):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.title("WhatYouTuber")
        self.geometry("1180x740")
        self.minsize(980, 640)
        self.configure(bg=BG)
        apply(self)
        self._icon()

        self.events = queue.Queue()
        self.channel = None
        self.channel_folder = None
        self.manual = set()
        self.nav_key = "tab:videos"
        self.saved_channels = []
        self.statuses = {}
        self.snippets = {}
        self.subtitle_text = {}
        self.collection = None
        self.collection_folder = None
        self.queue_items = []
        self.scanning = False
        self.converting = False
        self.scan_stop = threading.Event()
        self.detail_stop = threading.Event()
        self.sub_stop = threading.Event()
        self.pause_details = threading.Event()
        self.convert_stop = threading.Event()
        self.convert_pause = threading.Event()
        self._priority = []
        self._persist_job = None
        self._save_lock = threading.Lock()
        self._disk_log = queue.Queue()
        threading.Thread(target=self._write_log, daemon=True).start()

        self.banner = tk.Label(self, text="", bg=AMBER_BG, fg=AMBER, anchor="w", justify="left", padx=10, pady=6, font=("Segoe UI", 8))

        self.notebook = ttk.Notebook(self)
        self.channel_tab = ChannelTab(self.notebook, self)
        self.convert_tab = ConvertTab(self.notebook, self)
        self.results_tab = ResultsTab(self.notebook, self)
        self.search_tab = SearchTab(self.notebook, self)
        self.notebook.add(self.channel_tab, text="Канал")
        self.notebook.add(self.convert_tab, text="Конвертация")
        self.notebook.add(self.results_tab, text="Результат")
        self.notebook.add(self.search_tab, text="Поиск")
        self.notebook.pack(fill="both", expand=True)
        self.global_query = tk.StringVar()
        self.search_scope = tk.StringVar(value="везде")
        bar = ttk.Frame(self)
        bar.place(in_=self.notebook, relx=1.0, x=-8, y=2, anchor="ne")
        search_entry = ttk.Entry(bar, textvariable=self.global_query, width=28)
        search_entry.pack(side="left")
        search_entry.bind("<Return>", lambda _e: self.run_search())
        ttk.Combobox(
            bar, textvariable=self.search_scope, state="readonly", width=12,
            values=["везде", "речь", "названия", "мои тексты"],
        ).pack(side="left", padx=(4, 0))
        self._show_banner()

        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(label="Настройки", command=self.open_settings)
        file_menu.add_command(label="Настроить вход", command=self.open_login)
        menu.add_cascade(label="Файл", menu=file_menu)
        self.config(menu=menu)

        self.bind_all("<Control-KeyPress>", self._ctrl)
        self._was_minimized = False
        self.bind("<Unmap>", self._on_unmap)
        self.bind("<Map>", self._on_map)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_saved()
        self.channel_tab.reload(True)
        if not bootstrap_exists() and os.environ.get("WY_TEST") != "1":
            self.after(200, self.ask_data_dir)
        self.after(100, self._poll)

    def _on_unmap(self, event):
        if event.widget is self:
            self._was_minimized = True

    def _on_map(self, event):
        if event.widget is not self or not self._was_minimized:
            return
        self._was_minimized = False
        self.after(30, self._repaint_after_restore)

    def _repaint_after_restore(self):
        try:
            self.configure(bg=BG)
            self.channel_tab.repaint()
            self.update_idletasks()
        except tk.TclError:
            pass

    def _icon(self):
        path = Path((self.settings.converter or {}).get("path") or "") / "icon.ico"
        if path.is_file():
            try:
                self.iconbitmap(str(path))
            except tk.TclError:
                pass

    def _ctrl(self, event):
        actions = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>", 65: "<<SelectAll>>"}
        if str(event.keysym).lower() in {"v", "c", "x", "a"}:
            return None
        action = actions.get(event.keycode)
        if action:
            try:
                event.widget.event_generate(action)
            except tk.TclError:
                return None
            return "break"
        return None

    def _show_banner(self):
        text = missing_banner(check_components((self.settings.converter or {}).get("path") or ""))
        if text:
            self.banner.configure(text=text)
            if not self.banner.winfo_manager():
                self.banner.pack(fill="x", before=self.notebook)
        elif self.banner.winfo_manager():
            self.banner.pack_forget()

    def ask_data_dir(self):
        messagebox.showinfo(
            "WhatYouTuber",
            "Выберите папку, где хранить каналы и тексты.\nЕсли закрыть окно, будет использован Рабочий стол.",
            parent=self,
        )
        chosen = filedialog.askdirectory(parent=self, title="Папка WhatYouTuber")
        if chosen:
            self.settings.data_dir = chosen
        save_settings(self.settings)
        self.refresh_saved()

    def log(self, message: str):
        self._disk_log.put(str(message))

    def _write_log(self):
        while True:
            line = self._disk_log.get()
            try:
                append_log(self.settings, line)
            except OSError:
                pass

    def refresh_saved(self):
        try:
            self.saved_channels = list_channels(self.settings)
        except OSError:
            self.saved_channels = []

    def paste(self):
        try:
            self.channel_tab.url.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def toggle_scan(self):
        if self.scanning:
            self.scan_stop.set()
            self.channel_tab.set_status("Останавливаю сканирование...")
            return
        text = self.channel_tab.url.get().strip()
        if text.startswith("Поиск по названию"):
            text = ""
        if not text:
            messagebox.showinfo("Сканирование", "Вставьте ссылку на канал, видео или плейлист.", parent=self)
            return
        self.scanning = True
        self.scan_stop = threading.Event()
        self.channel_tab.set_scanning(True)
        self.channel_tab.set_status("Сканирую...")
        previous = self.channel
        auth = dict(self.settings.auth)

        def work():
            try:
                channel, fresh = scan(text, auth, self.scan_stop, lambda message: self.events.put(("status", message)), previous)
                self.events.put(("scan_done", (channel, fresh)))
            except Exception as exc:
                self.events.put(("scan_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def update_channel(self):
        if not self.channel:
            return
        self.channel_tab.url.set(self.channel.url)
        self.toggle_scan()

    def open_saved(self, channel_id: str):
        row = next((item for item in self.saved_channels if item["id"] == channel_id), None)
        if not row:
            return
        channel, ui = load_channel(Path(row["folder"]))
        self._adopt(channel, Path(row["folder"]), ui, fresh=[])

    def _adopt(self, channel, folder, ui, fresh):
        self.channel = channel
        self.channel_folder = folder
        self.manual = set(ui.get("manual") or [])
        groups = group_by_key(channel)
        nav = ui.get("nav") or ""
        if nav not in groups:
            nav = f"pl:{channel.playlists[0].id}" if channel.playlists else "tab:videos"
        self.nav_key = nav
        if channel.url:
            self.channel_tab.url.set(channel.url)
        self.refresh_statuses()
        self.channel_tab.reload(True)
        self.results_tab.reload()
        self._start_details()
        if fresh:
            self._offer_new(fresh)

    def _offer_new(self, fresh):
        if not self.channel_folder:
            return
        fresh_set = set(fresh)
        for folder, collection in list_collections(self.channel_folder):
            for playlist_id in collection.whole_playlists:
                playlist = next((item for item in self.channel.playlists if item.id == playlist_id), None)
                if not playlist:
                    continue
                extra = [video_id for video_id in playlist.video_ids if video_id in fresh_set and video_id not in collection.order]
                if not extra:
                    continue
                title = playlist.title
                if messagebox.askyesno(
                    "Новые видео",
                    f"В плейлисте «{title}» {len(extra)} новых видео — добавить и сконвертировать?",
                    parent=self,
                ):
                    self._extend_collection(folder, collection, extra)
                    self.start_queue()

    def _extend_collection(self, folder, collection, extra):
        order = list(collection.order) + [video_id for video_id in extra if video_id not in collection.order]
        collection.order = order
        collection.numbers = assign_numbers(collection.numbers, order)
        collection.single_videos = [video_id for video_id in collection.single_videos if video_id in order]
        save_collection(folder, collection)
        self._write_collection_files(folder, collection)
        self.collection = collection
        self.collection_folder = folder
        for video_id in extra:
            video = self.channel.videos.get(video_id)
            if video:
                video.is_new = False
        self.persist()

    def select_nav(self, key: str):
        self.nav_key = key
        groups = group_by_key(self.channel) if self.channel else {}
        self._priority = list(groups.get(key, ("", []))[1] or [])
        self.channel_tab.reload()
        self.persist()
        if self.channel_tab.subs.get() and self.channel_tab.current_filters()[0]:
            self._start_subs()

    def click_group(self, key: str):
        if not self.channel:
            return
        _title, ids = group_by_key(self.channel).get(key, ("", []))
        turn_on = group_mark(self.manual, ids) != "on"
        self.manual = set_group(self.manual, ids, turn_on)
        self.nav_key = key
        self._priority = list(ids)
        self.channel_tab.reload()
        self.persist()

    def toggle_video(self, video_id: str):
        self.manual = toggle_one(self.manual, video_id, video_id not in self.manual)
        self.channel_tab.reload()
        self.persist()

    def _current_ids(self):
        if not self.channel:
            return []
        _title, ids = group_by_key(self.channel).get(self.nav_key, ("", []))
        return list(ids or [])

    def mark_all(self):
        self.manual = set_group(self.manual, self._current_ids(), True)
        self.channel_tab.reload()
        self.persist()

    def clear_all(self):
        self.manual = set_group(self.manual, self._current_ids(), False)
        self.channel_tab.reload()
        self.persist()

    def invert_visible(self):
        self.manual = invert(self.manual, self._current_ids())
        self.channel_tab.reload()
        self.persist()

    def mark_found(self):
        self.manual = check_only_visible(self.manual, self._current_ids(), self.channel_tab.visible_video_ids())
        self.channel_tab.reload()
        self.persist()

    def open_current(self):
        if not self.channel:
            return
        if self.nav_key.startswith("pl:"):
            webbrowser.open(f"https://www.youtube.com/playlist?list={self.nav_key.split(':', 1)[1]}")
            return
        url = self.channel.url.rstrip("/")
        suffix = {"tab:streams": "/streams", "tab:shorts": "/shorts"}.get(self.nav_key, "/videos")
        webbrowser.open(url + suffix)

    def open_video(self, video_id: str):
        webbrowser.open(watch_url(video_id))

    def video_menu(self, video_id: str, x: int, y: int):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Скопировать ссылку", command=lambda: self._copy(watch_url(video_id)))
        video = self.channel.videos.get(video_id) if self.channel else None
        menu.add_command(label="Скопировать название", command=lambda: self._copy(video.title if video else ""))
        menu.add_command(label="Показать описание", command=lambda: self.show_description(video_id))
        from core.visual import presentation_links
        links = presentation_links(video.description if video else "")
        if links:
            menu.add_command(label="Открыть презентацию", command=lambda: webbrowser.open(links[0]))
        menu.tk_popup(x, y)

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def show_description(self, video_id: str):
        video = self.channel.videos.get(video_id) if self.channel else None
        if not video:
            return
        window = tk.Toplevel(self)
        window.title(video.title or "Описание")
        window.geometry("560x360")
        box = tk.Text(window, wrap="word")
        box.pack(fill="both", expand=True)
        box.insert("1.0", video.description or "Описание ещё не загружено.")
        box.configure(state="disabled")

    def persist(self):
        if self._persist_job:
            self.after_cancel(self._persist_job)
        self._persist_job = self.after(250, self._persist_now)

    def _persist_now(self):
        self._persist_job = None
        if not self.channel or not self.settings.data_dir:
            return
        channel = self.channel
        payload = {"channel": channel.to_dict(), "ui": {"manual": sorted(self.manual), "nav": self.nav_key}}
        settings = self.settings

        def work():
            with self._save_lock:
                try:
                    from core.storage import channel_dir, write_json
                    folder = channel_dir(settings, channel)
                    write_json(folder / "канал.json", payload)
                    self.channel_folder = folder
                except Exception as exc:
                    self.events.put(("status", f"Не удалось сохранить канал: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def save_lists(self, convert_after: bool):
        if not self.channel:
            messagebox.showinfo("Подборка", "Сначала отсканируйте канал.", parent=self)
            return
        groups = build_groups(self.channel)
        ordered = [(video_id, source) for video_id, source in export_order(groups, self.manual)
                   if self.channel.videos.get(video_id) and self.channel.videos[video_id].availability != "unavailable"]
        if not ordered:
            messagebox.showinfo("Подборка", "Отметьте хотя бы одно видео.", parent=self)
            return
        default = ""
        if self.nav_key.startswith("pl:"):
            default = group_by_key(self.channel).get(self.nav_key, ("", []))[0]
        name = simpledialog.askstring("Подборка", "Имя подборки:", initialvalue=default or self.channel.title, parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        self.persist()
        folder = None
        existing = None
        for path, collection in list_collections(self.channel_folder):
            if collection.name == name:
                folder, existing = path, collection
                break
        if folder is None:
            from core.storage import collection_dir
            folder = collection_dir(self.channel_folder, name)
            existing = Collection(name=name, channel_id=self.channel.id, created_at=datetime.now().isoformat(timespec="minutes"))
        order = [video_id for video_id, _source in ordered]
        existing.order = order
        existing.numbers = assign_numbers(existing.numbers, order)
        existing.whole_playlists = whole_playlist_ids(self.manual, groups)
        covered = set()
        for key, _title, ids in groups:
            playlist_id = key.split(":", 1)[1] if key.startswith("pl:") else ""
            if playlist_id in existing.whole_playlists:
                covered.update(ids)
        existing.single_videos = [video_id for video_id in order if video_id not in covered]
        existing.name = name
        save_collection(folder, existing)
        self._write_collection_files(folder, existing, ordered)
        for video_id in order:
            video = self.channel.videos.get(video_id)
            if video:
                video.is_new = False
        self.collection = existing
        self.collection_folder = folder
        self.persist()
        self.refresh_statuses()
        self.channel_tab.reload()
        self.results_tab.reload()
        self.queue_items, _ratio = build_items(self.channel, existing.order, existing.numbers, folder, self.settings.filename_style)
        self.convert_tab.set_items(self.queue_items, self.channel.videos)
        self.log(f"Списки сохранены: {folder}")
        if convert_after:
            self.notebook.select(self.convert_tab)
        else:
            messagebox.showinfo("Списки сохранены", str(folder), parent=self)

    def _videos_for(self, collection):
        if collection and collection.kind == "topic":
            return self._topic_channel(collection)
        return self.channel

    def _write_collection_files(self, folder, collection, ordered=None):
        holder = self._videos_for(collection)
        videos = holder.videos if holder else {}
        if ordered is None:
            rows = []
            for video_id in collection.order:
                video = videos.get(video_id)
                if video:
                    rows.append((video, ""))
        else:
            rows = [(videos[video_id], source) for video_id, source in ordered if video_id in videos]
        write_lists(folder, holder, rows, collection.numbers, self.settings.filename_style)
        statuses = {}
        raw = load_queue(folder)
        for item in raw.get("items") or []:
            statuses[item.get("video_id")] = {
                "done": "готово", "error": "ошибка", "skipped": "пропущено", "need_login": "нужен вход",
            }.get(item.get("status"), "ожидает")
        for video_id in collection.order:
            number = int(collection.numbers.get(video_id) or 0)
            video = videos.get(video_id)
            if not video:
                continue
            path = text_path(folder, number, video.title or video_id, video.upload_date, self.settings.filename_style, video_id=video_id)
            if file_ready(path):
                statuses[video_id] = "готово"
        write_toc(folder, holder, collection.order, collection.numbers, statuses, self.settings.filename_style)

    def start_queue(self):
        if self.converting:
            return
        if not self.collection or not self.collection_folder:
            messagebox.showinfo("Конвертация", "Сначала сохраните подборку кнопкой «Перевести в текст».", parent=self)
            return
        self._remember_options()
        playback = self._playback_channel()
        self.queue_items, _ratio = build_items(
            playback, self.collection.order, self.collection.numbers,
            self.collection_folder, self.settings.filename_style,
        )
        self.convert_tab.set_items(self.queue_items, playback.videos)
        if not any(item.status == "waiting" for item in self.queue_items):
            messagebox.showinfo("Конвертация", "В очереди нет видео, которые ещё нужно расшифровать.", parent=self)
            return
        self.converting = True
        self.convert_stop = threading.Event()
        self.convert_pause.clear()
        self.pause_details.set()
        self.convert_tab.set_paused(False)
        self.convert_tab.clear_log()
        self.notebook.select(self.convert_tab)
        folder = self.collection_folder
        settings = self.settings
        channel = self._playback_channel()
        items = self.queue_items
        visual = self.convert_tab.visual.get()
        formulas = bool(self.convert_tab.formulas.get())
        if self.collection:
            self.collection.visual = visual
            save_collection(self.collection_folder, self.collection)

        def subtitles_text(video_id):
            payload = fetch(video_id, settings.auth, subtitle_cache(self.channel_folder or folder, video_id))
            video = channel.videos.get(video_id)
            cues = payload.get("cues") or []
            if video is not None:
                video.has_subtitles = bool(cues)
            body, source = body_from_cache(payload)
            paragraphs = [(float(cue.get("start") or 0), cue.get("text") or "") for cue in cues]
            return body, source, paragraphs

        def work():
            def emit_log(message):
                self.events.put(("queue", {"type": "log", "message": message}))

            try:
                prepare(settings.converter, emit_log)
            except Exception as exc:
                emit_log(str(exc))

            def prefetch(url, log):
                return fetch_audio(url, settings.converter, log)

            try:
                run_queue(
                    channel, items, folder, settings, settings.auth,
                    lambda event: self.events.put(("queue", event)),
                    self.convert_stop, self.convert_pause, convert,
                    subtitles_text if settings.fast_subtitles else None,
                    prefetch,
                    visual,
                    formulas,
                )
            except Exception as exc:
                self.events.put(("queue", {"type": "log", "message": str(exc)}))
                self.events.put(("queue", {"type": "queue_done", "items": [], "stopped": True}))

        threading.Thread(target=work, daemon=True).start()

    def pause_queue(self):
        if not self.converting:
            return
        if self.convert_pause.is_set():
            self.convert_pause.clear()
            self.convert_tab.set_paused(False)
        else:
            self.convert_pause.set()
            self.convert_tab.set_paused(True)

    def stop_queue(self):
        self.convert_stop.set()
        self.convert_pause.clear()

    def retry_failed(self):
        if self.converting or not self.queue_items:
            return
        count = retry_failed(self.queue_items)
        if not count:
            messagebox.showinfo("Конвертация", "Ошибочных видео нет.", parent=self)
            return
        from core.queue_runner import remember
        remember(self.collection_folder, self.queue_items, 0)
        self.start_queue()

    def _remember_options(self):
        self.settings.converter = self.convert_tab.settings_dict()
        self.settings.fast_subtitles = bool(self.convert_tab.fast.get())
        self.settings.shutdown_after = bool(self.convert_tab.shutdown.get())
        save_settings(self.settings)

    def _playback_channel(self):
        collection = self.collection
        if not collection or collection.kind != "topic":
            return self.channel
        return self._topic_channel(collection)

    def _topic_channel(self, collection):
        from core.models import Channel
        merged = Channel(id=f"topic:{collection.name}", title=collection.name, videos={})
        folders = {row["id"]: row["folder"] for row in self.saved_channels}
        loaded = {}
        if self.channel and self.channel.id:
            loaded[self.channel.id] = self.channel
        for channel_id in collection.channels or []:
            if channel_id in loaded or channel_id not in folders:
                continue
            channel, _ui = load_channel(Path(folders[channel_id]))
            loaded[channel_id] = channel
        wanted = set(collection.order or [])
        for channel in loaded.values():
            for video_id, video in channel.videos.items():
                if video_id in wanted:
                    video.channel_title = channel.title
                    merged.videos[video_id] = video
        return merged

    def run_search(self):
        query = self.global_query.get().strip()
        if not query:
            return
        scope = self.search_scope.get() or "везде"
        data_dir = self.settings.data_dir

        def work():
            from core.index_db import index_file
            from core.lemma import ensure_synonyms
            from core.search import search
            synonyms = Path(data_dir) / "синонимы.txt"
            ensure_synonyms(synonyms)
            try:
                rows = search(index_file(data_dir), query, synonyms, scope=scope)
            except Exception as exc:
                self.events.put(("status", f"Поиск не удался: {exc}"))
                rows = []
            self.events.put(("search", {"rows": rows, "query": query}))

        threading.Thread(target=work, daemon=True).start()

    def _show_search(self, payload):
        from core.fmt import fmt_clock
        from core.index_db import IndexDB, index_file
        rows = []
        lookup = self._channel_cache()
        for item in payload.get("rows") or []:
            title, channel_title, duration = lookup(item.channel_id, item.video_id)
            fragment = ""
            if item.end and item.end > item.start:
                fragment = f"{fmt_clock(item.start)}–{fmt_clock(item.end)}"
            elif item.snippet:
                fragment = item.snippet[:40]
            rows.append({
                "id": item.video_id,
                "channel_id": item.channel_id,
                "channel": channel_title,
                "title": title,
                "level": item.level,
                "fragment": fragment,
                "where": item.where,
                "dur": duration,
                "start": item.start,
                "moments": item.moments,
                "snippet": item.snippet,
            })
        warning = ""
        no_text = IndexDB(index_file(self.settings.data_dir)).no_text_total()
        if no_text:
            warning = f"{no_text} видео без текста — по ним поиск только по названию и главам"
        self.search_tab.show(rows, warning)
        self.notebook.select(self.search_tab)

    def _channel_cache(self):
        cache = {}
        if self.channel:
            cache[self.channel.id] = self.channel

        from core.fmt import fmt_clock

        def lookup(channel_id, video_id):
            channel = cache.get(channel_id)
            if channel is None:
                row = next((item for item in self.saved_channels if item["id"] == channel_id), None)
                if row:
                    channel, _ui = load_channel(Path(row["folder"]))
                    cache[channel_id] = channel
            video = channel.videos.get(video_id) if channel else None
            title = video.title if video else video_id
            channel_title = channel.title if channel else channel_id
            duration = fmt_clock(video.duration_sec) if video and video.duration_sec else ""
            return title, channel_title, duration

        return lookup

    def save_topic(self, rows):
        from core.naming import safe_name
        name = simpledialog.askstring("Тематическая подборка", "Имя подборки:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        folder = topics_root(self.settings) / safe_name(name, 80)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "Тексты").mkdir(exist_ok=True)
        order = []
        for row in rows:
            if row["id"] not in order:
                order.append(row["id"])
        collection = Collection(
            name=name,
            channel_id="",
            kind="topic",
            channels=sorted({row["channel_id"] for row in rows}),
            order=order,
            numbers=assign_numbers({}, order),
            created_at=datetime.now().isoformat(timespec="minutes"),
            visual=self.convert_tab.visual.get(),
        )
        save_collection(folder, collection)
        self.collection = collection
        self.collection_folder = folder
        playback = self._topic_channel(collection)
        self._write_collection_files(folder, collection, [(video_id, "тема") for video_id in order if video_id in playback.videos])
        self.queue_items, _ratio = build_items(playback, order, collection.numbers, folder, self.settings.filename_style)
        self.convert_tab.set_items(self.queue_items, playback.videos)
        self.results_tab.reload()
        self.notebook.select(self.convert_tab)
        self.log(f"Тематическая подборка: {folder}")

    def start_index_asr(self):
        if not self.channel or self.converting:
            return
        from core.index_db import IndexDB, index_file
        from core.indexer import run_asr
        ids = IndexDB(index_file(self.settings.data_dir)).no_text_ids(self.channel.id)
        if not ids:
            messagebox.showinfo("Индекс", "Нет видео без текста.", parent=self)
            return
        if not messagebox.askyesno(
            "Индекс",
            f"Без субтитров {len(ids)} видео. Распознать звук только для поиска? В подборку текст не пишется.",
            parent=self,
        ):
            return
        self.converting = True
        self.pause_details.set()
        channel = self.channel
        settings = self.settings
        stop = self.convert_stop
        stop.clear()
        pause = self.convert_pause

        def emit(event):
            self.events.put(("detail", event))

        def work():
            try:
                run_asr(ids, channel, index_file(settings.data_dir), {"converter": settings.converter}, emit, stop, pause, convert)
            except Exception as exc:
                self.events.put(("status", str(exc)))
            self.events.put(("asr_done", None))

        threading.Thread(target=work, daemon=True).start()

    def _store_transcript(self, event):
        payload = {
            "id": event.get("id"),
            "channel_id": event.get("channel_id") or (self.channel.id if self.channel else ""),
            "duration": float(event.get("duration") or 0),
            "paragraphs": list(event.get("paragraphs") or []),
            "slides": list(event.get("slides") or []),
            "source": event.get("source") or "transcript",
            "title": event.get("title") or "",
            "description": event.get("description") or "",
        }
        data_dir = self.settings.data_dir

        def work():
            try:
                from core.index_db import IndexDB, index_file
                from core.indexer import to_windows
                windows = to_windows([{"start": start, "text": text} for start, text in payload["paragraphs"]])
                for slide in payload["slides"]:
                    text = (slide.get("text") or "").strip()
                    if slide.get("latex"):
                        text = (text + " " + " ".join(slide.get("latex") or [])).strip()
                    if text:
                        windows.append((int(float(slide.get("t") or 0) // 60 * 60), text, "slide"))
                if not windows:
                    return
                IndexDB(index_file(data_dir)).replace_video(
                    payload["id"], payload["channel_id"], payload["duration"], windows,
                    (payload["title"], payload["description"], ""), payload["source"], "", "indexed",
                )
            except Exception as exc:
                self.events.put(("status", f"Индекс текста: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def subtitle_search_changed(self):
        self.channel_tab.reload_table()
        if self.channel_tab.subs.get() and self.channel_tab.current_filters()[0]:
            self._start_subs()

    def _start_details(self):
        self._start_indexer()

    def _start_indexer(self):
        if not self.channel or not self.settings.data_dir:
            return
        self.detail_stop.set()
        self.detail_stop = threading.Event()
        stop = self.detail_stop
        channel = self.channel
        auth = dict(self.settings.auth)
        from core.index_db import index_file
        from core.indexer import run_indexer
        from core.lemma import ensure_synonyms
        db_path = index_file(self.settings.data_dir)
        ensure_synonyms(Path(self.settings.data_dir) / "синонимы.txt")

        def priority():
            return list(self._priority)

        def emit(event):
            self.events.put(("detail", event))

        threading.Thread(
            target=lambda: run_indexer(channel, auth, db_path, priority, emit, stop, self.pause_details),
            daemon=True,
        ).start()

    def _start_subs(self):
        if not self.channel or not self.channel_folder:
            return
        self.sub_stop.set()
        self.sub_stop = threading.Event()
        stop = self.sub_stop
        query = self.channel_tab.current_filters()[0]
        ids = self._current_ids()
        folder = self.channel_folder
        auth = dict(self.settings.auth)

        def emit(event):
            self.events.put(("sub", event))

        threading.Thread(
            target=lambda: search_current(ids, auth, lambda video_id: subtitle_cache(folder, video_id), query, emit, stop, self.pause_details),
            daemon=True,
        ).start()

    def refresh_statuses(self):
        self.statuses = {}
        if not self.channel_folder or not self.channel:
            return
        for folder, collection in list_collections(self.channel_folder):
            raw = load_queue(folder)
            known = {item.get("video_id"): item for item in raw.get("items") or []}
            for video_id in collection.order:
                video = self.channel.videos.get(video_id)
                number = int(collection.numbers.get(video_id) or 0)
                if video:
                    path = text_path(folder, number, video.title or video_id, video.upload_date, self.settings.filename_style, video_id=video_id)
                    if file_ready(path):
                        self.statuses[video_id] = "done"
                        continue
                item = known.get(video_id) or {}
                status = item.get("status")
                if status:
                    self.statuses[video_id] = status
        for item in self.queue_items:
            self.statuses[item.video_id] = item.status

    def ready_ids(self):
        return {video_id for video_id, status in self.statuses.items() if status == "done"}

    def status_of(self, video) -> str:
        if video.removed_from_channel:
            return "удалено с канала"
        if video.availability == "unavailable":
            return "недоступно"
        code = self.statuses.get(video.id)
        return {
            "done": "Текст готов ✓",
            "error": "ошибка ⚠",
            "running": "в очереди",
            "waiting": "в очереди",
            "need_login": "нужен вход",
            "skipped": "пропущено",
        }.get(code, "не конвертировано")

    def open_login(self):
        LoginDialog(self, self.settings.auth, self._check_login, self._save_auth)

    def _check_login(self, auth):
        ok, message = check_login(auth)
        return ok, message

    def _save_auth(self, auth):
        if "last_ok" not in auth:
            ok, message = check_login(auth)
            auth["last_ok"] = ok
            auth["last_message"] = message
        self.settings.auth = auth
        save_settings(self.settings)
        self.channel_tab._paint_pill()
        self.channel_tab.reload_table()

    def open_settings(self):
        SettingsDialog(self, self.settings, check_components(self.settings.converter.get("path") or ""), self._save_settings, self._update_ytdlp)

    def _save_settings(self, data):
        self.settings.data_dir = data["data_dir"] or self.settings.data_dir
        self.settings.converter["path"] = data["converter"]
        self.settings.pause_between_sec = data["pause"]
        self.settings.filename_style = data["style"]
        self.settings.file_header = data["header"]
        save_settings(self.settings)
        self.refresh_saved()
        self._show_banner()
        self._icon()

    def _update_ytdlp(self):
        code, output = update_ytdlp()
        self.log(output[-500:] if output else f"yt-dlp: код {code}")
        return code, output, check_components(self.settings.converter.get("path") or "")

    def _poll(self):
        handled = 0
        try:
            while handled < 40:
                kind, payload = self.events.get_nowait()
                self._handle(kind, payload)
                handled += 1
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(50 if handled >= 40 else 100, self._poll)

    def _handle(self, kind, payload):
        if kind == "status":
            self.channel_tab.set_status(payload)
            self.log(payload)
            return
        if kind == "scan_error":
            self.scanning = False
            self.channel_tab.set_scanning(False)
            self.channel_tab.set_status(payload)
            self.log(payload)
            messagebox.showerror("Сканирование", payload, parent=self)
            return
        if kind == "scan_done":
            channel, fresh = payload
            self.scanning = False
            self.channel_tab.set_scanning(False)
            ui = {"manual": sorted(self.manual), "nav": self.nav_key} if self.channel and self.channel.id == channel.id else {}
            try:
                with self._save_lock:
                    folder = save_channel(self.settings, channel, ui)
            except OSError as exc:
                messagebox.showerror("Сканирование", str(exc), parent=self)
                return
            self.refresh_saved()
            self._adopt(channel, folder, ui, fresh)
            self.channel_tab.set_status("")
            self.log(f"Канал прочитан: {channel.title}, видео {len(channel.videos)}")
            return
        if kind == "detail":
            self._apply_detail(payload)
            return
        if kind == "search":
            self._show_search(payload)
            return
        if kind == "asr_done":
            self.converting = False
            self.pause_details.clear()
            self.channel_tab.set_status("Распознавание для поиска закончено.")
            self._start_indexer()
            return
        if kind == "sub":
            self._apply_sub(payload)
            return
        if kind == "queue":
            self._apply_queue(payload)

    def _apply_detail(self, event):
        if event.get("type") == "log" and event.get("message"):
            self.convert_tab.log(event["message"])
            self.log(event["message"])
            return
        if not self.channel:
            return
        if event.get("type") in {"index_progress", "index_done"}:
            done = int(event.get("done") or 0)
            total = int(event.get("total") or 0)
            no_text = int(event.get("no_text") or 0)
            self.channel_tab.set_index(f"Индекс: {done} из {total} · {no_text} без текста", no_text)
            if done and (done % 25 == 0 or done == total):
                self.persist()
            return
        if event.get("type") == "index_status":
            self.channel_tab.set_status(event.get("message") or "")
            self.log(event.get("message") or "")
            return
        if event.get("type") == "detail":
            video = self.channel.videos.get(event.get("id"))
            if not video:
                return
            for key, value in (event.get("fields") or {}).items():
                if key == "title" and not value:
                    continue
                if key == "duration_sec" and not value:
                    continue
                setattr(video, key, value)
            self.channel_tab.refresh_row(video.id)
            return
        if event.get("type") == "detail_progress":
            done = int(event.get("done") or 0)
            total = int(event.get("total") or 0)
            if done and (done % 25 == 0 or done == total):
                self.persist()
            if done == total:
                self.channel_tab.reload_table()

    def _apply_sub(self, event):
        video_id = event.get("id")
        if event.get("type") == "sub_hit" and self.channel and video_id in self.channel.videos:
            video = self.channel.videos[video_id]
            video.has_subtitles = not event.get("empty")
            if event.get("snippet"):
                self.snippets[video_id] = event["snippet"]
                self.subtitle_text[video_id] = event["snippet"]
            for key, value in (event.get("fields") or {}).items():
                if key == "title" and not value:
                    continue
                if key == "duration_sec" and not value:
                    continue
                setattr(video, key, value)
            self.channel_tab.refresh_row(video_id)
            if event.get("done") == event.get("total"):
                self.channel_tab.reload_table()

    def _apply_queue(self, event):
        if event.get("type") == "transcript":
            self._store_transcript(event)
        if event.get("type") == "log" and event.get("message"):
            self.convert_tab.log(event["message"])
            self.log(event["message"])
        if event.get("type") == "progress":
            self.convert_tab.set_progress(
                event.get("fraction") or 0,
                event.get("phase") or "",
                event.get("index") or 0,
                event.get("total") or 0,
                event.get("eta") or 0,
            )
        if event.get("type") in {"queue", "queue_done"} and event.get("items") is not None and (self.channel or (self.collection and self.collection.kind == "topic")):
            from core.models import QueueItem
            self.queue_items = [QueueItem.from_dict(item) for item in event.get("items") or []]
            video_id = event.get("id")
            status = event.get("status")
            if video_id and status and self.convert_tab.tree.exists(video_id):
                self.statuses[video_id] = status
                self.convert_tab.update_status(video_id, status, event.get("error") or "")
                if self.channel_tab.table.tree.exists(video_id):
                    self.channel_tab.refresh_row(video_id)
            else:
                for item in self.queue_items:
                    self.statuses[item.video_id] = item.status
                videos = self._playback_channel().videos if self.collection and self.collection.kind == "topic" else self.channel.videos
                self.convert_tab.set_items(self.queue_items, videos)
        if event.get("type") == "auth_failed":
            self.settings.auth["last_ok"] = False
            self.settings.auth["last_message"] = event.get("message") or "Вход не работает"
            save_settings(self.settings)
            self.channel_tab._paint_pill()
        if event.get("type") == "queue_done":
            self.converting = False
            self.pause_details.clear()
            self.convert_tab.set_paused(False)
            self.refresh_statuses()
            self.channel_tab.reload_table()
            self.results_tab.reload()
            if self.settings.shutdown_after and not event.get("stopped") and os.environ.get("WY_TEST") != "1":
                subprocess.Popen(["shutdown", "/s", "/t", "60", "/c", "WhatYouTuber закончил расшифровку"])
                self.convert_tab.log("Компьютер выключится через 60 секунд. Отмена: shutdown /a")
            if getattr(self, "_quit_after", False):
                self._finish_close()

    def close(self):
        if self.converting:
            if not messagebox.askyesno("Выход", "Идёт конвертация. Остановить и выйти?", parent=self):
                return
            self._quit_after = True
            self.convert_stop.set()
            self.convert_pause.clear()
            return
        self._finish_close()

    def _finish_close(self):
        self._quit_after = False
        self.scan_stop.set()
        self.detail_stop.set()
        self.sub_stop.set()
        self.convert_stop.set()
        if self._persist_job:
            self.after_cancel(self._persist_job)
            self._persist_job = None
        if self.channel and self.settings.data_dir:
            try:
                with self._save_lock:
                    save_channel(self.settings, self.channel, {"manual": sorted(self.manual), "nav": self.nav_key})
            except OSError:
                pass
        self.destroy()
