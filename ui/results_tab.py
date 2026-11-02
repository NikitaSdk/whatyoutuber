"""Вкладка «Результат»: готовые тексты, оглавление и поиск по словам."""

import os
import tkinter as tk
from tkinter import messagebox, ttk

from core.export import combine_texts, search_texts
from core.fmt import fmt_clock
from core.export import text_path
from ui.theme import INK, button


class ResultsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.folders = {}

        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Подборка:").pack(side="left")
        self.pick = tk.StringVar()
        self.box = ttk.Combobox(top, textvariable=self.pick, state="readonly", width=48)
        self.box.pack(side="left", padx=8)
        self.box.bind("<<ComboboxSelected>>", lambda _e: self.reload())
        button(top, "Открыть папку", self.open_folder).pack(side="left")
        button(top, "Открыть оглавление", self.open_toc).pack(side="left", padx=6)
        button(top, "Собрать все тексты в один файл", self.combine).pack(side="left")

        mid = ttk.Frame(self, padding=(10, 0))
        mid.pack(fill="both", expand=True)
        columns = ("file", "source", "dur", "words")
        self.tree = ttk.Treeview(mid, columns=columns, show="headings")
        for key, title, width in (
            ("file", "Файл", 420),
            ("source", "Источник", 260),
            ("dur", "Длительность", 110),
            ("words", "Слов", 80),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, stretch=key == "file")
        scroll = ttk.Scrollbar(mid, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self.open_selected)

        search = ttk.Frame(self, padding=10)
        search.pack(fill="both")
        ttk.Label(search, text="Поиск по текстам:").pack(anchor="w")
        row = ttk.Frame(search)
        row.pack(fill="x", pady=4)
        self.query = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.find())
        button(row, "Найти", self.find).pack(side="left", padx=6)
        self.hits = tk.Listbox(search, height=6, font=("Segoe UI", 9), activestyle="none")
        self.hits.pack(fill="both", expand=True)
        self.hits.bind("<Double-1>", self.open_hit)
        self._hit_files = []

    def reload(self):
        channel = self.app.channel
        folder = self.app.channel_folder
        self.folders = {}
        names = []
        if channel and folder:
            from core.storage import list_collections, list_topics
            for path, collection in list_collections(folder):
                names.append(collection.name)
                self.folders[collection.name] = path
            for path, collection in list_topics(self.app.settings):
                label = f"тема: {collection.name}"
                names.append(label)
                self.folders[label] = path
        self.box.configure(values=names)
        current = self.pick.get()
        if current not in names:
            prefer = self.app.collection.name if self.app.collection else ""
            current = prefer if prefer in names else (names[0] if names else "")
            self.pick.set(current)
        self._fill()

    def _selected(self):
        path = self.folders.get(self.pick.get())
        if not path:
            return None, None
        from core.storage import load_collection
        return path, load_collection(path)

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        path, collection = self._selected()
        holder = self.app._videos_for(collection) if collection else None
        if not path or not collection or not holder:
            return
        videos = holder.videos
        texts = path / "Тексты"
        style = self.app.settings.filename_style
        for video_id in collection.order:
            video = videos.get(video_id)
            if video is None:
                continue
            number = int(collection.numbers.get(video_id) or 0)
            file_path = text_path(path, number, video.title or video_id, video.upload_date, style, video_id=video_id)
            filename = file_path.name
            source = "—"
            words = ""
            if file_path.is_file():
                body = file_path.read_text(encoding="utf-8")
                for line in body.splitlines():
                    if line.startswith("Источник текста:"):
                        source = line.split(":", 1)[1].strip()
                        break
                words = str(len(body.split()))
            self.tree.insert("", "end", iid=video_id, values=(filename, source, fmt_clock(video.duration_sec), words))

    def open_selected(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        path, collection = self._selected()
        if not path or not collection:
            return
        video_id = selected[0]
        holder = self.app._videos_for(collection)
        video = holder.videos.get(video_id) if holder else None
        if video is None:
            messagebox.showinfo("Результат", "Этого текста ещё нет.", parent=self)
            return
        number = int(collection.numbers.get(video_id) or 0)
        target = text_path(path, number, video.title, video.upload_date, self.app.settings.filename_style, video_id=video_id)
        if target.is_file():
            os.startfile(target)
        else:
            messagebox.showinfo("Результат", "Этого текста ещё нет.", parent=self)

    def open_folder(self):
        path, _collection = self._selected()
        if path and path.is_dir():
            os.startfile(path)

    def open_toc(self):
        path, _collection = self._selected()
        target = path / "Оглавление.txt" if path else None
        if target and target.is_file():
            os.startfile(target)
        else:
            messagebox.showinfo("Результат", "Оглавление появится после сохранения подборки.", parent=self)

    def combine(self):
        path, collection = self._selected()
        if not path or not collection:
            return
        holder = self.app._videos_for(collection)
        target = combine_texts(path, holder, collection.order, collection.numbers, self.app.settings.filename_style)
        messagebox.showinfo("Результат", f"Файл собран:\n{target}", parent=self)

    def find(self):
        self.hits.delete(0, "end")
        self._hit_files = []
        path, collection = self._selected()
        if not path or not collection:
            return
        found = search_texts(
            path, self.app._videos_for(collection), collection.order, collection.numbers,
            self.app.settings.filename_style, self.query.get(),
        )
        for hit in found:
            self.hits.insert("end", f"{hit['number']:03d}  {hit['title']}   {hit['snippet']}")
            self._hit_files.append(hit["file"])
        if not found:
            self.hits.insert("end", "Ничего не найдено")

    def open_hit(self, _event):
        selection = self.hits.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self._hit_files):
            return
        os.startfile(self._hit_files[index])
