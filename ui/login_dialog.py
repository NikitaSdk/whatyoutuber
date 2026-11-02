"""Диалог входа: без входа, браузер или файл cookies.txt."""

import tkinter as tk
from tkinter import filedialog, ttk

from ui.theme import BG, INK, WHITE, button

BROWSERS = ["firefox", "chrome", "edge", "brave", "opera"]
CHROMIUM = {"chrome", "edge", "brave", "opera"}


class LoginDialog(tk.Toplevel):
    def __init__(self, master, auth: dict, on_check, on_save):
        super().__init__(master)
        self.title("Вход в YouTube")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.auth = dict(auth or {})
        self.on_check = on_check
        self.on_save = on_save
        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        self.mode = tk.StringVar(value=self.auth.get("mode") or "none")
        self.browser = tk.StringVar(value=self.auth.get("browser") or "firefox")
        self.cookie = tk.StringVar(value=self.auth.get("cookie_file") or "")

        ttk.Radiobutton(frame, text="Без входа", value="none", variable=self.mode, command=self._sync).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(anchor="w", fill="x", pady=(6, 0))
        ttk.Radiobutton(row, text="Взять вход из браузера:", value="browser", variable=self.mode, command=self._sync).pack(side="left")
        self.browser_box = ttk.Combobox(row, textvariable=self.browser, values=BROWSERS, width=12, state="readonly")
        self.browser_box.pack(side="left", padx=6)
        self.browser_box.bind("<<ComboboxSelected>>", lambda _e: self._sync())

        file_row = ttk.Frame(frame)
        file_row.pack(anchor="w", fill="x", pady=(6, 0))
        ttk.Radiobutton(file_row, text="Файл cookies.txt:", value="file", variable=self.mode, command=self._sync).pack(side="left")
        ttk.Entry(file_row, textvariable=self.cookie, width=42).pack(side="left", padx=6)
        button(file_row, "Обзор…", self._browse).pack(side="left")

        self.warn = tk.Label(frame, text="", bg="#fff6db", fg="#7a5b12", wraplength=460, justify="left", font=("Segoe UI", 8), padx=8, pady=6)
        self.result = tk.Label(frame, text=self.auth.get("last_message") or "", bg=BG, fg=INK, wraplength=480, justify="left", font=("Segoe UI", 9))
        self.result.pack(anchor="w", pady=(10, 0))
        note = ("Спонсорские и закрытые видео откроются, только если у этого аккаунта есть к ним доступ. "
                "Пароль программа не видит: из браузера берётся только уже существующий вход.")
        ttk.Label(frame, text=note, wraplength=480).pack(anchor="w", pady=(8, 0))

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(12, 0))
        button(actions, "Проверить вход", self._check).pack(side="left")
        button(actions, "Сохранить", self._save, primary=True).pack(side="right")
        button(actions, "Отмена", self.destroy).pack(side="right", padx=(0, 8))
        self._sync()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _sync(self):
        show = self.mode.get() == "browser" and self.browser.get() in CHROMIUM
        if show:
            self.warn.configure(text="В Windows вход из Chrome, Edge, Brave и Opera часто не читается: браузер шифрует cookies. Надёжнее Firefox или файл cookies.txt.")
            self.warn.pack(anchor="w", fill="x", pady=(10, 0), before=self.result)
        else:
            self.warn.pack_forget()

    def _browse(self):
        path = filedialog.askopenfilename(parent=self, title="cookies.txt", filetypes=[("Текст", "*.txt"), ("Все файлы", "*.*")])
        if path:
            self.cookie.set(path)
            self.mode.set("file")

    def _payload(self) -> dict:
        data = dict(self.auth)
        data.update({
            "mode": self.mode.get(),
            "browser": self.browser.get(),
            "cookie_file": self.cookie.get().strip(),
        })
        return data

    def _check(self):
        self.result.configure(text="Проверяю...")
        self.update_idletasks()
        ok, message = self.on_check(self._payload())
        self.auth["last_ok"] = ok
        self.auth["last_message"] = message
        self.result.configure(text=message, fg="#18794e" if ok else "#b42318")

    def _save(self):
        self.on_save(self._payload())
        self.destroy()
