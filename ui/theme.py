"""Цвета и шрифт в духе макета: светлый фон, синяя кнопка, синее выделение."""

import tkinter as tk
from tkinter import ttk

BG = "#f3f4f6"
WHITE = "#ffffff"
INK = "#1f2933"
MUTED = "#667085"
LINE = "#e4e7ec"
BLUE = "#1a6fb5"
BLUE_ACTIVE = "#155f9c"
SELECT = "#d9eaf8"
GREEN = "#18794e"
RED = "#b42318"
AMBER_BG = "#fff6db"
AMBER = "#7a5b12"
FONT = ("Segoe UI", 9)
FONT_B = ("Segoe UI", 10, "bold")
FONT_S = ("Segoe UI", 8)


def apply(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=INK, font=FONT)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=WHITE)
    style.configure("TLabel", background=BG, foreground=INK, font=FONT)
    style.configure("Card.TLabel", background=WHITE, foreground=INK, font=FONT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT)
    style.configure("CardMuted.TLabel", background=WHITE, foreground=MUTED, font=FONT)
    style.configure("Title.TLabel", background=WHITE, foreground=INK, font=FONT_B)
    style.configure("Section.TLabel", background=WHITE, foreground=MUTED, font=("Segoe UI", 8))
    style.configure("Green.TLabel", background=WHITE, foreground=GREEN, font=FONT)
    style.configure("Red.TLabel", background=WHITE, foreground=RED, font=FONT)
    style.configure("TEntry", padding=4)
    style.configure("TButton", padding=(10, 4), font=FONT)
    style.configure("Treeview", rowheight=26, font=FONT, background=WHITE, fieldbackground=WHITE, borderwidth=0)
    style.configure("Treeview.Heading", font=FONT, background="#f7f8fa", foreground=MUTED, relief="flat")
    style.map("Treeview", background=[("selected", "#c5ddf3")])
    style.configure("TNotebook", background=BG, borderwidth=0, bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.configure("TNotebook.Tab", padding=(16, 6), font=FONT, background="#e9ebef", borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", WHITE)], foreground=[("selected", INK)])
    style.configure("TCheckbutton", background=BG, font=FONT)
    style.configure("Bar.TCheckbutton", background=BG, font=FONT)
    style.configure("TRadiobutton", background=BG, font=FONT)
    style.map("TCheckbutton", background=[("active", BG), ("disabled", BG)])
    style.map("TRadiobutton", background=[("active", BG)])
    return style


def button(parent, text, command, primary=False):
    if primary:
        return tk.Button(
            parent, text=text, command=command, bg=BLUE, fg="white",
            activebackground=BLUE_ACTIVE, activeforeground="white",
            relief="flat", padx=14, pady=6, font=FONT, cursor="hand2", bd=0,
        )
    return tk.Button(
        parent, text=text, command=command, bg="#eef1f4", fg=INK,
        activebackground="#e4e7ec", activeforeground=INK,
        relief="flat", padx=10, pady=6, font=FONT, cursor="hand2", bd=0,
        highlightthickness=1, highlightbackground=LINE, highlightcolor=LINE,
    )
