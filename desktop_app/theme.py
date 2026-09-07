"""
Dark visual theme inspired by Discord's own dark mode.

Adds no new dependencies: it's built entirely on top of ttk.Style (using
'clam' as the base theme, which is the most flexible one to customize).
Imported and applied once when the app starts, via apply_theme(root).
"""
import tkinter as tk
from tkinter import ttk

# --- Color palette ---------------------------------------------------
BG_PRIMARY = "#313338"      # main window background
BG_SECONDARY = "#2b2d31"    # panels, cards, headers
BG_TERTIARY = "#1e1f22"     # inputs and table background
BG_ROW_ALT = "#26272b"      # zebra striping in tables
BG_HOVER = "#3a3c43"

ACCENT = "#5865F2"          # Discord's "blurple"
ACCENT_HOVER = "#4752c4"
DANGER = "#ed4245"
DANGER_HOVER = "#c13b3e"
WARNING = "#faa61a"
WARNING_HOVER = "#d68e15"
SUCCESS = "#23a55a"

TEXT_PRIMARY = "#f2f3f5"
TEXT_HEADER = "#ffffff"
TEXT_MUTED = "#949ba4"

BORDER = "#1e1f22"

SEVERITY_COLORS = {
    "critical": "#ed4245",
    "high": "#ff8c42",
    "medium": "#f5c400",
    "low": "#949ba4",
}

FONT_FAMILY = "Segoe UI"
FONT_DEFAULT = (FONT_FAMILY, 10)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_HEADER = (FONT_FAMILY, 13, "bold")
FONT_STAT_NUMBER = (FONT_FAMILY, 20, "bold")
FONT_STAT_LABEL = (FONT_FAMILY, 9, "bold")


def apply_theme(root: tk.Tk) -> ttk.Style:
    """Applies the dark theme to the root window and returns the configured ttk.Style object."""
    root.configure(bg=BG_PRIMARY)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG_PRIMARY, foreground=TEXT_PRIMARY,
                     font=FONT_DEFAULT, borderwidth=0, focuscolor=ACCENT)

    # --- Frames ---
    style.configure("TFrame", background=BG_PRIMARY)
    style.configure("Card.TFrame", background=BG_SECONDARY)

    # --- Labels ---
    style.configure("TLabel", background=BG_PRIMARY, foreground=TEXT_PRIMARY, font=FONT_DEFAULT)
    style.configure("Header.TLabel", background=BG_PRIMARY, foreground=TEXT_HEADER, font=FONT_HEADER)
    style.configure("Muted.TLabel", background=BG_PRIMARY, foreground=TEXT_MUTED, font=FONT_DEFAULT)
    style.configure("Card.TLabel", background=BG_SECONDARY, foreground=TEXT_PRIMARY, font=FONT_DEFAULT)
    style.configure("StatNumber.TLabel", background=BG_SECONDARY, foreground=TEXT_HEADER,
                     font=FONT_STAT_NUMBER)
    style.configure("StatLabel.TLabel", background=BG_SECONDARY, foreground=TEXT_MUTED,
                     font=FONT_STAT_LABEL)
    style.configure("StatusBar.TLabel", background=BG_SECONDARY, foreground=TEXT_MUTED,
                     font=FONT_DEFAULT, padding=(10, 5))

    # --- Buttons ---
    style.configure("TButton", background=BG_SECONDARY, foreground=TEXT_PRIMARY,
                     font=FONT_BOLD, padding=(12, 7), borderwidth=0, relief="flat")
    style.map("TButton",
              background=[("active", BG_HOVER), ("pressed", BG_HOVER)],
              foreground=[("disabled", TEXT_MUTED)])

    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                     font=FONT_BOLD, padding=(12, 7), borderwidth=0)
    style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("pressed", ACCENT_HOVER)])

    style.configure("Danger.TButton", background=DANGER, foreground="#ffffff",
                     font=FONT_BOLD, padding=(12, 7), borderwidth=0)
    style.map("Danger.TButton", background=[("active", DANGER_HOVER), ("pressed", DANGER_HOVER)])

    style.configure("Warning.TButton", background=WARNING, foreground="#1e1f22",
                     font=FONT_BOLD, padding=(12, 7), borderwidth=0)
    style.map("Warning.TButton", background=[("active", WARNING_HOVER), ("pressed", WARNING_HOVER)])

    # --- Text entries ---
    style.configure("TEntry", fieldbackground=BG_TERTIARY, background=BG_TERTIARY,
                     foreground=TEXT_PRIMARY, insertcolor=TEXT_PRIMARY,
                     borderwidth=1, relief="flat", padding=6, bordercolor=BORDER)
    style.map("TEntry", bordercolor=[("focus", ACCENT)])

    # --- Checkbuttons ---
    style.configure("TCheckbutton", background=BG_PRIMARY, foreground=TEXT_PRIMARY, font=FONT_DEFAULT)
    style.map("TCheckbutton", background=[("active", BG_PRIMARY)])

    # --- Dropdown menus (ttk.OptionMenu uses TMenubutton) ---
    style.configure("TMenubutton", background=BG_TERTIARY, foreground=TEXT_PRIMARY,
                     font=FONT_DEFAULT, padding=(10, 6), borderwidth=0, relief="flat",
                     arrowcolor=TEXT_MUTED)
    style.map("TMenubutton", background=[("active", BG_HOVER)])

    # --- Tabs (Notebook) ---
    style.configure("TNotebook", background=BG_PRIMARY, borderwidth=0, tabmargins=(0, 8, 0, 0))
    style.configure("TNotebook.Tab", background=BG_SECONDARY, foreground=TEXT_MUTED,
                     font=FONT_BOLD, padding=(18, 10), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", BG_PRIMARY)],
              foreground=[("selected", TEXT_HEADER)])

    # --- LabelFrame ---
    style.configure("TLabelframe", background=BG_PRIMARY, borderwidth=1, relief="flat",
                     bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG_PRIMARY, foreground=TEXT_MUTED, font=FONT_BOLD)

    # --- Treeview (tables) ---
    style.configure("Treeview", background=BG_TERTIARY, fieldbackground=BG_TERTIARY,
                     foreground=TEXT_PRIMARY, borderwidth=0, rowheight=26, font=FONT_DEFAULT)
    style.configure("Treeview.Heading", background=BG_SECONDARY, foreground=TEXT_MUTED,
                     font=FONT_BOLD, borderwidth=0, relief="flat", padding=(8, 8))
    style.map("Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", "#ffffff")])
    style.map("Treeview.Heading", background=[("active", BG_SECONDARY)])

    # --- Scrollbars ---
    style.configure("Vertical.TScrollbar", background=BG_SECONDARY, troughcolor=BG_PRIMARY,
                     bordercolor=BG_PRIMARY, arrowcolor=TEXT_MUTED, borderwidth=0, relief="flat")
    style.map("Vertical.TScrollbar", background=[("active", BG_HOVER)])

    return style


def tag_configure_zebra(tree: ttk.Treeview):
    """Applies zebra striping (two alternating dark shades) to a Treeview."""
    tree.tag_configure("oddrow", background=BG_ROW_ALT)
    tree.tag_configure("evenrow", background=BG_TERTIARY)


def zebra_tag(index: int) -> str:
    return "oddrow" if index % 2 else "evenrow"