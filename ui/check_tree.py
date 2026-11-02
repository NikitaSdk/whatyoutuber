"""Таблица с галочками. У обычного Treeview их нет — рисуем ☐ и ☑."""

import tkinter as tk
from tkinter import ttk


class CheckTree(ttk.Frame):
    def __init__(self, master, on_toggle, on_open, on_menu, on_sort):
        super().__init__(master)
        self.on_toggle = on_toggle
        self.on_open = on_open
        self.on_menu = on_menu
        self.on_sort = on_sort
        self._sort = {}

        columns = ("check", "num", "title", "playlist", "date", "dur", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        headings = [
            ("check", "", 42, False),
            ("num", "№", 46, True),
            ("title", "Название", 360, True),
            ("playlist", "Плейлист", 180, True),
            ("date", "Дата", 100, True),
            ("dur", "Длит.", 72, True),
            ("status", "Статус", 140, True),
        ]
        for key, title, width, stretch in headings:
            self.tree.heading(key, text=title, command=lambda name=key: self._heading(name))
            self.tree.column(key, width=width, minwidth=36, stretch=stretch, anchor="w")
        self.tree.column("check", anchor="center", stretch=False)
        self.tree.column("num", anchor="center", stretch=False)
        self.tree.column("dur", anchor="center", stretch=False)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("checked", background="#e7f2fb")
        self.tree.tag_configure("dim", foreground="#98a2b3")
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<Double-1>", self._double)
        self.tree.bind("<Button-3>", self._right)

    def _heading(self, name):
        if name == "check":
            return
        reverse = self._sort.get(name, False)
        if getattr(self, "_last", None) == name:
            reverse = not reverse
        self._last = name
        self._sort[name] = reverse
        self.on_sort(name, reverse)

    def set_rows(self, rows: list):
        ids = [row["id"] for row in rows]
        if ids and ids == list(self.tree.get_children()):
            for row in rows:
                self.update_row(row)
            return
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", "end", iid=row["id"], values=self._values(row), tags=self._tags(row))

    def update_row(self, row: dict):
        if self.tree.exists(row["id"]):
            self.tree.item(row["id"], values=self._values(row), tags=self._tags(row))

    def _values(self, row):
        mark = "☑" if row.get("checked") else "☐"
        return (mark, row.get("num"), row.get("title"), row.get("playlist"), row.get("date"), row.get("dur"), row.get("status"))

    def _tags(self, row):
        tags = []
        if row.get("checked"):
            tags.append("checked")
        if row.get("dim"):
            tags.append("dim")
        return tags

    def _click(self, event):
        row = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if row and column == "#1":
            self.on_toggle(row)

    def _double(self, event):
        row = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if row and column != "#1":
            self.on_open(row)

    def _right(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.on_menu(row, event.x_root, event.y_root)
