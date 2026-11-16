#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChessCoach - Interactive 2D Chess Training & Analysis Application (Flet 1.0+ & 0.28 Compatible)
===============================================================================================
Built with Python's `flet` framework (fully compatible with Flet 1.0+ and 0.28.x) for the GUI
and `python-chess` for chess rules, legal move validation, and Stockfish UCI engine integration.

Key Features:
1. Collapsible Left Navigation Sidebar controlled via a top-left Hamburger Menu
   button (☰) with smooth width animation (Homepage, Engine & Board, Puzzles with
   4 indented categories, Settings, About the App, Technical Support Email,
   and Financial Support).
2. Clean top bar with the Hamburger toggle button (☰) and ChessCoach brand on the left,
   and quick Settings access on the right.
3. Scrollable Dashboard Homepage featuring categorized training cards (Daily,
   Opening, Middle Game, and End Game).
4. Interactive 2D Chessboard powered by `python-chess` with legal move indicators
   (dots for empty squares, rings for captures), best-move hint highlights,
   pawn promotion modal, castling, and en passant.
5. Non-blocking async Stockfish UCI engine integration with automatic project-folder
   Stockfish detection (including `stockfish-windows-x86-64-universal` and `stockfish` folders).
6. Settings modal allowing instant switching between Light and Dark UI themes, as well as
   preset and custom HEX Light/Dark square colors for the chessboard.
7. Add the first opening in this app called catalan opening 

"""

from level_view import LevelTrainerView
from database import ChessCoachDB
import asyncio
import glob
import os
import re
import shutil
import threading
import chess
import chess.engine
import flet as ft


# =====================================================================
# 0. Cross-Version Flet Compatibility Helpers (Flet 1.0+ & Flet 0.28.x)
# =====================================================================

def _pad_symmetric(horizontal: int = 0, vertical: int = 0):
    if hasattr(ft, "Padding") and hasattr(ft.Padding, "symmetric"):
        return ft.Padding.symmetric(horizontal=horizontal, vertical=vertical)
    return ft.padding.symmetric(horizontal=horizontal, vertical=vertical)


def _pad_only(left: int = 0, top: int = 0, right: int = 0, bottom: int = 0):
    if hasattr(ft, "Padding") and hasattr(ft.Padding, "only"):
        return ft.Padding.only(left=left, top=top, right=right, bottom=bottom)
    return ft.padding.only(left=left, top=top, right=right, bottom=bottom)


def _border_all(width: float, color: str):
    if hasattr(ft, "Border") and hasattr(ft.Border, "all"):
        return ft.Border.all(width, color)
    return ft.border.all(width, color)


def _align_center():
    if hasattr(ft, "Alignment") and hasattr(ft.Alignment, "CENTER"):
        return ft.Alignment.CENTER
    return ft.alignment.center


def _make_animation(duration_ms: int = 220):
    curve = getattr(ft.AnimationCurve, "EASE_IN_OUT", None)
    if hasattr(ft, "Animation"):
        return ft.Animation(duration_ms, curve) if curve else ft.Animation(duration_ms)
    return ft.animation.Animation(duration_ms, curve)


def _make_text_button(label: str, on_click):
    try:
        return ft.TextButton(content=label, on_click=on_click)
    except TypeError:
        return ft.TextButton(text=label, on_click=on_click)


# =====================================================================
# 1. UI Themes & Board Color Palettes
# =====================================================================

UI_THEMES = {
    "light": {
        "name": "Light Mode",
        "bg_main": "#F8FAFC",
        "bg_panel": "#FFFFFF",
        "bg_card": "#FFFFFF",
        "bg_header": "#E2E8F0",
        "bg_sidebar": "#F1F5F9",
        "fg_primary": "#0F172A",
        "fg_secondary": "#475569",
        "fg_muted": "#64748B",
        "fg_sidebar": "#0F172A",
        "fg_sidebar_sub": "#475569",
        "accent": "#2563EB",
        "accent_hover": "#1D4ED8",
        "border": "#CBD5E1",
        "card_border": "#E2E8F0",
        "section_bar_bg": "#EDF2F7",
        "btn_bg": "#E2E8F0",
        "btn_fg": "#0F172A",
        "badge_bg": "#EEF2FF",
        "badge_fg": "#3730A3",
        "fg_on_accent": "#FFFFFF",
        "success": "#15803D",
        "success_bg": "#DCFCE7",
        "warning": "#B45309",
        "warning_bg": "#FEF3C7",
        "danger": "#B91C1C",
        "danger_bg": "#FEE2E2",
    },
    "dark": {
        "name": "Dark Mode",
        "bg_main": "#0B0F19",
        "bg_panel": "#151E2E",
        "bg_card": "#151E2E",
        "bg_header": "#030712",
        "bg_sidebar": "#080D1A",
        "fg_primary": "#F8FAFC",
        "fg_secondary": "#94A3B8",
        "fg_muted": "#64748B",
        "fg_sidebar": "#F8FAFC",
        "fg_sidebar_sub": "#94A3B8",
        "accent": "#3B82F6",
        "accent_hover": "#60A5FA",
        "border": "#1F293D",
        "card_border": "#1F293D",
        "section_bar_bg": "#111827",
        "btn_bg": "#1F293D",
        "btn_fg": "#F8FAFC",
        "badge_bg": "#1E293B",
        "badge_fg": "#93C5FD",
        "fg_on_accent": "#FFFFFF",
        "success": "#4ADE80",
        "success_bg": "#0F2A1C",
        "warning": "#FBBF24",
        "warning_bg": "#2A2210",
        "danger": "#F87171",
        "danger_bg": "#2A1215",
    },
}

BOARD_THEMES = {
    "classic": {
        "name": "Classic Wood",
        "light_sq": "#F0D9B5",
        "dark_sq": "#B58863",
        "selected": "#F6F669",
        "last_move": "#CDD26A",
        "legal_dot": "#2E7D32",
        "legal_capture": "#C62828",
        "check_sq": "#EF4444",
        "hint_sq": "#3B82F6",
    },
    "modern_blue": {
        "name": "Modern Blue",
        "light_sq": "#DEE3E6",
        "dark_sq": "#8CA2AD",
        "selected": "#FFF176",
        "last_move": "#AED581",
        "legal_dot": "#1565C0",
        "legal_capture": "#D32F2F",
        "check_sq": "#EF4444",
        "hint_sq": "#2563EB",
    },
    "emerald": {
        "name": "Tournament Green",
        "light_sq": "#EEEED2",
        "dark_sq": "#769656",
        "selected": "#BACA44",
        "last_move": "#F6F669",
        "legal_dot": "#1B5E20",
        "legal_capture": "#B71C1C",
        "check_sq": "#EF4444",
        "hint_sq": "#2563EB",
    },
}

# Standard Unicode Chess Pieces
PIECE_UNICODE = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}

# Piece colours of the training screen (same look as the engine board).
PIECE_COLORS = {
    "piece_white": "#FFFFFF",
    "piece_black": "#0F172A",
    "piece_shadow": "#475569",
}

HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")

# Settings a Guest gets, and what a saved value falls back to if it is missing or invalid.
DEFAULT_UI_MODE = "dark"
DEFAULT_BOARD_PRESET = "classic"
DEFAULT_ENGINE_TIME_LIMIT = 0.5


# =====================================================================
# 2. Main ChessCoach Flet Application Class
# =====================================================================

class ChessCoachFletApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "ChessCoach - Smart Chess Trainer & Analysis"
        self.page.padding = 0
        self.page.spacing = 0
        try:
            self.page.window.width = 1180
            self.page.window.height = 780
            self.page.window.min_width = 960
            self.page.window.min_height = 660
            self.page.window.on_event = self._on_window_event
        except Exception:
            pass

        # ---- Database & Current User (Guest until a profile is chosen) ----
        # Creates chesscoach.db on the very first launch, then logs in as the last used profile.
        self.db = ChessCoachDB()
        self.db.login_last_user()

        # ---- Application & Theme State (from the user's saved settings, defaults for a Guest) ----
        self._load_user_settings()  # sets ui_mode, board_preset, square colors, engine_time_limit

        self.current_page = "homepage"  # 'homepage' or 'engine'
        self.sidebar_open = True        # Toggled via the Hamburger button (☰)

        # ---- Chessboard State (python-chess) ----
        self.board = chess.Board()
        self.board_flipped = False
        self.selected_square = None
        self.legal_moves_for_selected = []
        self.last_move = None
        self.board_size = 480
        self.sq_size = self.board_size // 8

        # ---- Stockfish Engine State & Thread Synchronization ----
        self.engine = None
        self.engine_lock = threading.Lock()
        self.engine_path = self._auto_detect_stockfish()
        self.play_vs_engine = False
        self.best_move_arrow = None  # (from_sq, to_sq) tuple for best move hint

        # ---- FilePicker Service (Flet 1.0+ registers automatically, no overlay append) ----
        self.file_picker = None
        self._init_file_picker()

        # ---- Training screen (LevelTrainerView), created when the Catalan card is opened ----
        self.level_trainer = None

        # ---- Build UI & Apply Theme ----
        self._build_layout()
        self._apply_theme()

        if self.engine_path:
            self.connect_stockfish(self.engine_path, silent=True)

    def _load_user_settings(self):
        """Copies the current user's saved settings into the app state.

        A Guest has no saved settings, so it gets the defaults. A saved value that is
        missing or no longer valid (for example a theme name that was removed) also falls
        back to the default, so a bad row can never crash the start-up.
        """
        saved = self.db.get_user_settings() or {}

        ui_mode = saved.get("ui_mode")
        self.ui_mode = ui_mode if ui_mode in UI_THEMES else DEFAULT_UI_MODE

        preset = saved.get("board_preset")
        self.board_preset = preset if preset in BOARD_THEMES else DEFAULT_BOARD_PRESET

        # A colour stored as None means "use the colours of the preset".
        preset_colors = BOARD_THEMES[self.board_preset]
        self.light_sq_color = saved.get("light_sq_color") or preset_colors["light_sq"]
        self.dark_sq_color = saved.get("dark_sq_color") or preset_colors["dark_sq"]

        limit = saved.get("engine_time_limit")
        valid_limit = isinstance(limit, (int, float)) and limit > 0
        self.engine_time_limit = limit if valid_limit else DEFAULT_ENGINE_TIME_LIMIT

    def _save_settings(self) -> bool:
        """Saves the current appearance settings for the signed-in user.

        Returns False for a Guest: the database refuses every write in Guest
        mode, so no 'if guest' check is needed here.
        The square colours are saved as real values (not None): save_user_settings
        uses COALESCE, so None would mean "keep the old value", not "use the preset".
        """
        return self.db.save_user_settings(
            ui_mode=self.ui_mode,
            board_preset=self.board_preset,
            light_sq_color=self.light_sq_color,
            dark_sq_color=self.dark_sq_color,
            engine_time_limit=self.engine_time_limit,
        )

    # -----------------------------------------------------------------
    # Accounts: the database says who is signed in, the UI follows it.
    # The logic lives in small methods (no dialog code inside), so each
    # one can be tested on its own.
    # -----------------------------------------------------------------
    def _account_label(self) -> str:
        """Text of the account button: '👤 Guest' or '👤 <display name>'."""
        user = self.db.get_current_user()
        if user is None:
            return "👤 Guest"
        name = user["display_name"] or user["username"]
        return "👤 " + (name if len(name) <= 16 else name[:15] + "…")

    def _after_account_change(self):
        """Call after the signed-in user changed: load that user's settings and repaint."""
        self._load_user_settings()
        self.account_btn_text.value = self._account_label()
        self._apply_theme()  # re-colours every view and ends with page.update()

    def _switch_account(self, user_id: int) -> bool:
        """Signs in as an existing profile. Returns False if it does not exist."""
        if self.db.login(user_id) is None:
            return False
        self._after_account_change()
        return True

    def _switch_to_guest(self):
        self.db.switch_to_guest()
        self._after_account_change()

    def _create_account(self, username: str, display_name: str = "") -> str | None:
        """Creates a profile and signs in as it.

        Returns None on success, or a message to show the user (empty name, too
        long, or already taken). UsernameTakenError is a ValueError too.
        """
        try:
            self.db.create_user(username, display_name)
        except ValueError as exc:
            return str(exc)
        self._after_account_change()
        return None

    def _init_file_picker(self):
        try:
            # In Flet 1.0+, FilePicker is a Service and takes no on_result argument
            self.file_picker = ft.FilePicker()
        except Exception:
            self.file_picker = None

    # -----------------------------------------------------------------
    # Auto-detect Stockfish binary in project subdirectories & OS paths
    # -----------------------------------------------------------------
    def _auto_detect_stockfish(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_patterns = [
            os.path.join(script_dir, "stockfish*", "**", "stockfish*.exe"),
            os.path.join(script_dir, "stockfish*", "stockfish*.exe"),
            os.path.join(script_dir, "stockfish*", "**", "stockfish"),
            os.path.join(script_dir, "stockfish*", "stockfish"),
        ]
        candidates = []
        for pattern in local_patterns:
            for matched in glob.glob(pattern, recursive=True):
                if os.path.isfile(matched):
                    candidates.append(os.path.abspath(matched))

        candidates.extend([
            r"C:\Program Files\Stockfish\stockfish.exe",
            "/usr/games/stockfish",
            "/usr/bin/stockfish",
            "/usr/local/bin/stockfish",
        ])

        which_path = shutil.which("stockfish")
        if which_path:
            candidates.insert(0, os.path.abspath(which_path))

        for path in candidates:
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                return os.path.abspath(path)
        return ""

    # -----------------------------------------------------------------
    # Build Main Application Layout (Top Bar + Collapsible Sidebar + Pages)
    # -----------------------------------------------------------------
    def _build_layout(self):
        t = UI_THEMES[self.ui_mode]

        # 1. Top Navigation Bar with Hamburger Button (☰) on the Left & Settings on the Right
        self.hamburger_icon_text = ft.Text(
            "☰",
            size=22,
            weight=ft.FontWeight.BOLD,
            color="#FFFFFF" if self.sidebar_open else t["fg_primary"],
        )
        self.hamburger_btn = ft.Container(
            content=self.hamburger_icon_text,
            padding=_pad_symmetric(horizontal=12, vertical=6),
            border_radius=8,
            bgcolor=t["accent"] if self.sidebar_open else t["btn_bg"],
            on_click=self.toggle_sidebar,
            tooltip="Open / Close Sidebar (فتح / إغلاق الشريط الجانبي)",
            ink=True,
        )

        self.brand_title = ft.Text(
            "♔ ChessCoach",
            size=20,
            weight=ft.FontWeight.BOLD,
            color=t["fg_primary"],
        )

        self.brand_container = ft.Container(
            content=self.brand_title,
            on_click=lambda e: self.show_page("homepage"),
            padding=_pad_symmetric(horizontal=6, vertical=4),
        )

        self.settings_btn_text = ft.Text(
            "⚙ Settings",
            size=13,
            weight=ft.FontWeight.BOLD,
            color=t["btn_fg"],
        )
        self.settings_btn = ft.Container(
            content=self.settings_btn_text,
            bgcolor=t["btn_bg"],
            padding=_pad_symmetric(horizontal=14, vertical=8),
            border_radius=8,
            on_click=lambda e: self.open_settings_dialog(),
            ink=True,
        )

        # Account button: shows who is signed in ("👤 Guest" or the profile name).
        self.account_btn_text = ft.Text(
            self._account_label(),
            size=13,
            weight=ft.FontWeight.BOLD,
            color=t["btn_fg"],
        )
        self.account_btn = ft.Container(
            content=self.account_btn_text,
            bgcolor=t["btn_bg"],
            padding=_pad_symmetric(horizontal=14, vertical=8),
            border_radius=8,
            on_click=lambda e: self.open_account_dialog(),
            tooltip="Account / Profile",
            ink=True,
        )

        self.top_bar = ft.Container(
            height=58,
            bgcolor=t["bg_header"],
            padding=_pad_symmetric(horizontal=18, vertical=0),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[self.hamburger_btn, self.brand_container],
                    ),
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[self.account_btn, self.settings_btn],
                    ),
                ],
            ),
        )

        # 2. Collapsible Left Sidebar
        self.sidebar_container = ft.Container(
            width=255,
            bgcolor=t["bg_sidebar"],
            animate=_make_animation(220),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._populate_sidebar()

        # 3. Main Content Views (Homepage & Engine Page)
        self.homepage_view = ft.Container(expand=True)
        self.engine_view = ft.Container(expand=True, visible=False)
        self.opening_trainer_view = ft.Container(expand=True, visible=False)

        self._build_homepage()
        self._build_engine_page()

        self.content_area = ft.Container(
            expand=True,
            bgcolor=t["bg_main"],
            content=ft.Stack(
                expand=True,
                controls=[
                    self.homepage_view,
                    self.engine_view,
                    self.opening_trainer_view,
                ],
            ),
        )

        # 4. Body Row (Collapsible Sidebar + Content Area)
        self.body_row = ft.Row(
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[self.sidebar_container, self.content_area],
        )

        self.root_column = ft.Column(
            expand=True,
            spacing=0,
            controls=[self.top_bar, self.body_row],
        )

        self.page.add(self.root_column)

    # -----------------------------------------------------------------
    # Toggle Left Sidebar Open / Closed via Hamburger Button (☰)
    # -----------------------------------------------------------------
    def toggle_sidebar(self, e=None):
        self.sidebar_open = not self.sidebar_open
        self.sidebar_container.width = 255 if self.sidebar_open else 0
        t = UI_THEMES[self.ui_mode]
        self.hamburger_btn.bgcolor = t["accent"] if self.sidebar_open else t["btn_bg"]
        self.hamburger_icon_text.color = "#FFFFFF" if self.sidebar_open else t["fg_primary"]
        self.page.update()

    # -----------------------------------------------------------------
    # Build & Refresh Unified Left Navigation Sidebar
    # -----------------------------------------------------------------
    def _make_sidebar_btn(self, text: str, on_click, is_active: bool = False, is_sub: bool = False):
        t = UI_THEMES[self.ui_mode]
        bg = t["accent"] if is_active else t["bg_sidebar"]
        fg = "#FFFFFF" if is_active else (t["fg_sidebar_sub"] if is_sub else t["fg_sidebar"])
        weight = ft.FontWeight.NORMAL if is_sub else ft.FontWeight.BOLD
        font_size = 12 if is_sub else 13
        left_pad = 24 if is_sub else 14
        v_pad = 7 if is_sub else 10

        return ft.Container(
            bgcolor=bg,
            border_radius=8,
            padding=_pad_only(left=left_pad, right=12, top=v_pad, bottom=v_pad),
            on_click=on_click,
            ink=True,
            content=ft.Row(
                controls=[
                    ft.Text(text, size=font_size, weight=weight, color=fg),
                ]
            ),
        )

    def _populate_sidebar(self):
        t = UI_THEMES[self.ui_mode]
        home_active = self.current_page == "homepage"
        engine_active = self.current_page == "engine"

        puzzle_sub_defs = [
            "Opening Puzzles",
            "Middle Game Puzzles",
            "Endgame Puzzles",
            "Different Skills Puzzles",
        ]

        sidebar_items = [
            ft.Container(
                padding=_pad_only(left=14, right=14, top=16, bottom=8),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(
                            "NAVIGATION MENU",
                            size=11,
                            weight=ft.FontWeight.BOLD,
                            color=t["fg_muted"],
                        ),
                        ft.Container(
                            content=ft.Text("✕", size=13, color=t["fg_muted"]),
                            on_click=self.toggle_sidebar,
                            tooltip="Close Sidebar (إغلاق الشريط الجانبي)",
                            padding=4,
                        ),
                    ],
                ),
            ),
            self._make_sidebar_btn(
                "🏠  Homepage",
                lambda e: self.show_page("homepage"),
                is_active=home_active,
            ),
            self._make_sidebar_btn(
                "⚡  Engine & Board",
                lambda e: self.show_page("engine"),
                is_active=engine_active,
            ),
            ft.Container(
                padding=_pad_only(left=14, top=10, bottom=4),
                content=ft.Text(
                    "🧩  Puzzles",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=t["fg_sidebar"],
                ),
            ),
        ]

        for label in puzzle_sub_defs:
            sidebar_items.append(
                self._make_sidebar_btn(
                    f"↳  {label}",
                    lambda e, lbl=label: self.show_puzzle_placeholder(lbl),
                    is_sub=True,
                )
            )

        sidebar_items.extend(
            [
                ft.Divider(height=12, color=t["border"]),
                self._make_sidebar_btn(
                    "⚙  Settings",
                    lambda e: self.open_settings_dialog(),
                ),
                self._make_sidebar_btn(
                    "ℹ  About the App",
                    lambda e: self.show_about_dialog(),
                ),
                self._make_sidebar_btn(
                    "✉  Technical Support Email",
                    lambda e: self.show_support_email_dialog(),
                ),
                self._make_sidebar_btn(
                    "☕  Financial Support",
                    lambda e: self.show_financial_support_dialog(),
                ),
            ]
        )

        self.sidebar_container.bgcolor = t["bg_sidebar"]
        self.sidebar_container.content = ft.Column(
            expand=True,
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            controls=sidebar_items,
        )

    # -----------------------------------------------------------------
    # Build Scrollable Dashboard Homepage Content
    # -----------------------------------------------------------------
    def _create_section_bar(self, title_text: str):
        t = UI_THEMES[self.ui_mode]
        return ft.Container(
            padding=_pad_only(top=10, bottom=6),
            content=ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
                controls=[
                    ft.Text(
                        f"◈  {title_text}",
                        size=18,
                        weight=ft.FontWeight.BOLD,
                        color=t["accent"],
                    ),
                    ft.Container(
                        expand=True,
                        height=2,
                        bgcolor=t["border"],
                    ),
                ],
            ),
        )

    def _create_card(self, title: str, subtitle: str = "", badge: str = "", is_small: bool = False, on_click=None):
        t = UI_THEMES[self.ui_mode]
        header_controls = [
            ft.Text(
                title,
                size=14 if is_small else 15,
                weight=ft.FontWeight.BOLD,
                color=t["fg_primary"],
                expand=True,
            )
        ]
        if badge:
            header_controls.append(
                ft.Container(
                    bgcolor=t["badge_bg"],
                    padding=_pad_symmetric(horizontal=8, vertical=3),
                    border_radius=6,
                    content=ft.Text(
                        badge,
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=t["badge_fg"],
                    ),
                )
            )

        col_controls = [
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=header_controls,
            )
        ]
        if subtitle:
            col_controls.append(
                ft.Text(
                    subtitle,
                    size=12,
                    color=t["fg_secondary"],
                )
            )

        return ft.Container(
            expand=1,
            bgcolor=t["bg_card"],
            border=_border_all(1, t["card_border"]),
            border_radius=10,
            padding=_pad_symmetric(horizontal=18, vertical=14 if is_small else 18),
            on_click=(lambda e: on_click()) if on_click else None,
            ink=True,
            content=ft.Column(
                spacing=6,
                controls=col_controls,
            ),
        )

    def _build_homepage(self):
        t = UI_THEMES[self.ui_mode]

        # Section 1: Daily Cards Row
        top_row = ft.Row(
            spacing=14,
            controls=[
                self._create_card(
                    title="Daily Revised",
                    subtitle="Review recent training drills & tactical patterns",
                    badge="Daily Training",
                    is_small=True,
                    on_click=lambda: self.show_card_placeholder("Daily Revised"),
                ),
                self._create_card(
                    title="Daily Puzzles",
                    subtitle="Sharpen your calculation with today's featured puzzles",
                    badge="Daily Tactics",
                    is_small=True,
                    on_click=lambda: self.show_card_placeholder("Daily Puzzles"),
                ),
            ],
        )

        # Section 2: Opening (Catalan Opening + 5 Coming Soon Cards)
        opening_rows = []
        for r in range(3):
            row_cards = []
            for c in range(2):
                idx = r * 2 + c + 1
                if r == 0 and c == 0:
                    row_cards.append(
                        self._create_card(
                            title="Catalan Opening",
                            subtitle="Chapter 1: An Introduction to the Closed Catalan (White)",
                            badge="Chapter 1 • Ready",
                            on_click=self.open_catalan_trainer,
                        )
                    )
                else:
                    row_cards.append(
                        self._create_card(
                            title="Coming Soon",
                            subtitle="Opening preparation module in development",
                            badge="In Progress",
                            on_click=lambda i=idx: self.show_card_placeholder(f"Opening - Card {i} (Coming Soon)"),
                        )
                    )
            opening_rows.append(ft.Row(spacing=14, controls=row_cards))

        # Section 3: Middle Game
        mid_row_1 = ft.Row(
            spacing=14,
            controls=[
                self._create_card(
                    title="General Middle Game",
                    subtitle="Core positional strategies, pawn structures & outposts",
                    badge="Strategy",
                    on_click=lambda: self.show_card_placeholder("General Middle Game"),
                ),
                self._create_card(
                    title="Opening Middle Game",
                    subtitle="Transitions from opening theory into dynamic middlegame play",
                    badge="Transition",
                    on_click=lambda: self.show_card_placeholder("Opening Middle Game"),
                ),
            ],
        )
        mid_row_2 = ft.Row(
            spacing=14,
            controls=[
                self._create_card(
                    title="Middle Game Puzzles",
                    subtitle="Tactical sacrifices, attacking patterns & defensive resources",
                    badge="Puzzles",
                    on_click=lambda: self.show_card_placeholder("Middle Game Puzzles"),
                ),
                ft.Container(expand=1),
            ],
        )

        # Section 4: End Game
        end_row = ft.Row(
            spacing=14,
            controls=[
                self._create_card(
                    title="General End Game",
                    subtitle="Essential theoretical endgames, king activity & pawn races",
                    badge="Fundamentals",
                    on_click=lambda: self.show_card_placeholder("General End Game"),
                ),
                self._create_card(
                    title="End Game Puzzles",
                    subtitle="Precise endgame calculation drills and technique tests",
                    badge="Puzzles",
                    on_click=lambda: self.show_card_placeholder("End Game Puzzles"),
                ),
            ],
        )

        self.homepage_view.bgcolor = t["bg_main"]
        self.homepage_view.content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            controls=[
                ft.Container(
                    padding=_pad_symmetric(horizontal=30, vertical=24),
                    content=ft.Column(
                        spacing=14,
                        controls=[
                            ft.Text(
                                "Welcome to ChessCoach",
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                color=t["fg_primary"],
                            ),
                            top_row,
                            self._create_section_bar("Opening"),
                            *opening_rows,
                            self._create_section_bar("Middle Game"),
                            mid_row_1,
                            mid_row_2,
                            self._create_section_bar("End Game"),
                            end_row,
                        ],
                    ),
                )
            ],
        )

    # -----------------------------------------------------------------
    # Build Engine & Interactive 2D Chessboard View
    # -----------------------------------------------------------------
    def _build_engine_page(self):
        t = UI_THEMES[self.ui_mode]

        self.status_banner = ft.Text(
            "White to move",
            size=16,
            weight=ft.FontWeight.BOLD,
            color=t["fg_primary"],
        )

        # 8x8 Grid container for the 2D Chessboard
        self.board_grid_col = ft.Column(spacing=0, tight=True)
        self.board_frame = ft.Container(
            width=self.board_size,
            height=self.board_size,
            border=_border_all(2, t["border"]),
            border_radius=4,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=self.board_grid_col,
        )

        # Board Action Buttons
        self.btn_new_game = self._make_action_btn("🔄 New Game", lambda e: self.reset_board())
        self.btn_undo = self._make_action_btn("↩ Undo Move", lambda e: self.undo_move())
        self.btn_flip = self._make_action_btn("⇅ Flip Board", lambda e: self.flip_board())

        board_column = ft.Column(
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=12,
            controls=[
                self.status_banner,
                self.board_frame,
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10,
                    controls=[self.btn_new_game, self.btn_undo, self.btn_flip],
                ),
            ],
        )

        # Right Panel: Stockfish Engine Controls & Move History
        if not hasattr(self, "engine_status_lbl"):
            self.engine_status_lbl = ft.Text(
                "Status: External Stockfish not connected (Built-in tactical analyzer active)",
                size=12,
                color=t["fg_secondary"],
            )
        else:
            self.engine_status_lbl.color = t["fg_secondary"]

        if not hasattr(self, "eval_score_lbl"):
            self.eval_score_lbl = ft.Text(
                "Evaluation: 0.00 (Equal)",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=t["fg_primary"],
            )
        else:
            self.eval_score_lbl.color = t["fg_primary"]

        if not hasattr(self, "best_move_lbl"):
            self.best_move_lbl = ft.Text(
                "Suggested Best Move: —",
                size=13,
                color=t["accent"],
            )
        else:
            self.best_move_lbl.color = t["accent"]

        if not hasattr(self, "legal_moves_lbl"):
            self.legal_moves_lbl = ft.Text(
                "",
                size=11,
                font_family="monospace",
                color=t["fg_secondary"],
            )
        else:
            self.legal_moves_lbl.color = t["fg_secondary"]

        if not hasattr(self, "history_text_lbl"):
            self.history_text_lbl = ft.Text(
                "No moves played yet.",
                size=12,
                font_family="monospace",
                color=t["fg_primary"],
                selectable=True,
            )
        else:
            self.history_text_lbl.color = t["fg_primary"]

        self.chk_vs_engine = ft.Checkbox(
            label="Auto-play vs Engine (Engine plays Black)",
            value=self.play_vs_engine,
            on_change=self._on_vs_engine_toggle,
        )

        btn_connect_sf = self._make_action_btn(
            "📂 Set Stockfish Path",
            self.browse_stockfish_dialog,
            expand=True,
        )
        btn_hint = self._make_action_btn(
            "💡 Best Move Hint",
            self.request_engine_hint,
            primary=True,
            expand=True,
        )
        btn_play_now = self._make_action_btn(
            "▶ Play Engine Move Now",
            self.play_engine_move_now,
        )

        eval_box = ft.Container(
            bgcolor=t["bg_main"],
            border=_border_all(1, t["border"]),
            border_radius=8,
            padding=12,
            content=ft.Column(
                spacing=4,
                controls=[self.eval_score_lbl, self.best_move_lbl],
            ),
        )

        history_box = ft.Container(
            expand=True,
            bgcolor=t["bg_main"],
            border=_border_all(1, t["border"]),
            border_radius=8,
            padding=10,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[self.history_text_lbl],
            ),
        )

        self.engine_panel = ft.Container(
            width=360,
            bgcolor=t["bg_panel"],
            border=_border_all(1, t["border"]),
            border_radius=10,
            padding=16,
            content=ft.Column(
                expand=True,
                spacing=10,
                controls=[
                    ft.Text(
                        "🤖 Chess Engine (Stockfish)",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=t["fg_primary"],
                    ),
                    self.engine_status_lbl,
                    ft.Row(spacing=8, controls=[btn_connect_sf, btn_hint]),
                    ft.Row(controls=[ft.Container(expand=True, content=btn_play_now)]),
                    self.chk_vs_engine,
                    eval_box,
                    ft.Text(
                        "✅ Legal Moves in Current Position:",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=t["fg_primary"],
                    ),
                    self.legal_moves_lbl,
                    ft.Text(
                        "📜 Move History:",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=t["fg_primary"],
                    ),
                    history_box,
                ],
            ),
        )

        self.engine_view.bgcolor = t["bg_main"]
        self.engine_view.padding = 18
        self.engine_view.content = ft.Row(
            expand=True,
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[board_column, self.engine_panel],
        )

        self.draw_board(update_ui=False)
        self.update_status_and_history(update_ui=False)

    def _make_action_btn(self, text: str, on_click, primary: bool = False, expand: bool = False):
        t = UI_THEMES[self.ui_mode]
        bg = t["accent"] if primary else t["btn_bg"]
        fg = "#FFFFFF" if primary else t["btn_fg"]
        return ft.Container(
            expand=expand,
            bgcolor=bg,
            border_radius=8,
            padding=_pad_symmetric(horizontal=12, vertical=9),
            alignment=_align_center(),
            on_click=on_click,
            ink=True,
            content=ft.Text(text, size=12, weight=ft.FontWeight.BOLD, color=fg),
        )

    async def _on_vs_engine_toggle(self, e):
        self.play_vs_engine = bool(self.chk_vs_engine.value)
        if not self.board.is_game_over() and self.play_vs_engine and self.board.turn == chess.BLACK:
            await self.play_engine_move_now()

    # -----------------------------------------------------------------
    # Page Switching
    # -----------------------------------------------------------------
    def show_page(self, page_name: str):
        self.current_page = page_name
        self.homepage_view.visible = page_name == "homepage"
        self.engine_view.visible = page_name == "engine"
        self.opening_trainer_view.visible = page_name == "opening_trainer"
        self._populate_sidebar()
        if page_name == "engine":
            self.draw_board(update_ui=False)
            self.update_status_and_history(update_ui=False)
        self.page.update()

    def open_catalan_trainer(self):
        """Opens the training screen (learn / quiz levels) of Catalan chapter 1."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        json_file = os.path.join(script_dir, "catalan_ch01_v2.json")
        try:
            self.level_trainer = LevelTrainerView(
                page=self.page,
                chapter_path=json_file,
                theme=UI_THEMES[self.ui_mode],
                board_colors=self._board_colors(),
                db=self.db,
                on_back=lambda: self.show_page("homepage"),
            )
            self.opening_trainer_view.content = self.level_trainer.root
            self.show_page("opening_trainer")
        except Exception as exc:
            self.level_trainer = None
            self._show_info_dialog(
                "Opening Trainer Error",
                f"Could not load Catalan Opening chapter:\n{exc}",
            )

    def _board_colors(self) -> dict:
        """Board colours for the training screen: the preset's highlight colours,
        the user's square colours and the piece colours."""
        return {
            **BOARD_THEMES[self.board_preset],
            "light_sq": self.light_sq_color,
            "dark_sq": self.dark_sq_color,
            **PIECE_COLORS,
        }

    def _refresh_boards(self):
        """Redraws every board after a board colour change in Settings."""
        self.draw_board(update_ui=False)
        if self.level_trainer is not None:
            self.level_trainer.set_theme(UI_THEMES[self.ui_mode], self._board_colors(), update=False)
        self.page.update()

    # -----------------------------------------------------------------
    # Render 2D Chessboard, Pieces, Legal Moves & Best Move Hint
    # -----------------------------------------------------------------
    def draw_board(self, update_ui: bool = True):
        theme = BOARD_THEMES[self.board_preset]
        sq = self.sq_size

        king_in_check_sq = None
        if self.board.is_check():
            king_in_check_sq = self.board.king(self.board.turn)

        legal_target_squares = {move.to_square for move in self.legal_moves_for_selected}
        hint_squares = set(self.best_move_arrow) if self.best_move_arrow else set()

        rows = []
        for row in range(8):
            row_cells = []
            for col in range(8):
                file_idx = 7 - col if self.board_flipped else col
                rank_idx = row if self.board_flipped else 7 - row
                square = chess.square(file_idx, rank_idx)

                is_light = (file_idx + rank_idx) % 2 == 1
                fill_color = self.light_sq_color if is_light else self.dark_sq_color

                if square == self.selected_square:
                    fill_color = theme["selected"]
                elif self.last_move and square in (self.last_move.from_square, self.last_move.to_square):
                    fill_color = theme["last_move"]

                if square == king_in_check_sq:
                    fill_color = theme["check_sq"]

                coord_color = self.dark_sq_color if is_light else self.light_sq_color
                stack_items = []

                # Coordinate labels on outer ranks/files
                if col == 0:
                    stack_items.append(
                        ft.Container(
                            left=4,
                            top=2,
                            content=ft.Text(
                                str(rank_idx + 1),
                                size=10,
                                weight=ft.FontWeight.BOLD,
                                color=coord_color,
                            ),
                        )
                    )
                if row == 7:
                    stack_items.append(
                        ft.Container(
                            right=4,
                            bottom=2,
                            content=ft.Text(
                                chess.FILE_NAMES[file_idx],
                                size=10,
                                weight=ft.FontWeight.BOLD,
                                color=coord_color,
                            ),
                        )
                    )

                # Best-move hint border highlight
                if square in hint_squares:
                    is_hint_target = self.best_move_arrow and square == self.best_move_arrow[1]
                    stack_items.append(
                        ft.Container(
                            width=sq,
                            height=sq,
                            border=_border_all(4 if is_hint_target else 3, theme["hint_sq"]),
                            border_radius=4,
                        )
                    )

                # Piece rendering with subtle shadow
                piece = self.board.piece_at(square)
                if piece:
                    symbol = PIECE_UNICODE[piece.symbol()]
                    piece_fg = "#FFFFFF" if piece.color == chess.WHITE else "#0F172A"
                    stack_items.append(
                        ft.Container(
                            width=sq,
                            height=sq,
                            alignment=_align_center(),
                            padding=_pad_only(left=2, top=3),
                            content=ft.Text(
                                symbol,
                                size=36,
                                color="#475569",
                            ),
                        )
                    )
                    stack_items.append(
                        ft.Container(
                            width=sq,
                            height=sq,
                            alignment=_align_center(),
                            content=ft.Text(
                                symbol,
                                size=36,
                                color=piece_fg,
                            ),
                        )
                    )

                # Legal move indicators (ring for captures, dot for empty squares)
                if square in legal_target_squares and self.selected_square is not None:
                    is_capture = (
                        self.board.piece_at(square) is not None
                        or self.board.is_en_passant(chess.Move(self.selected_square, square))
                    )
                    if is_capture:
                        stack_items.append(
                            ft.Container(
                                width=sq,
                                height=sq,
                                alignment=_align_center(),
                                content=ft.Container(
                                    width=sq - 8,
                                    height=sq - 8,
                                    border=_border_all(4, theme["legal_capture"]),
                                    border_radius=(sq - 8) // 2,
                                ),
                            )
                        )
                    else:
                        stack_items.append(
                            ft.Container(
                                width=sq,
                                height=sq,
                                alignment=_align_center(),
                                content=ft.Container(
                                    width=18,
                                    height=18,
                                    bgcolor=theme["legal_dot"],
                                    border_radius=9,
                                ),
                            )
                        )

                cell = ft.Container(
                    width=sq,
                    height=sq,
                    bgcolor=fill_color,
                    on_click=lambda e, s=square: self.on_square_click(s),
                    content=ft.Stack(width=sq, height=sq, controls=stack_items),
                )
                row_cells.append(cell)
            rows.append(ft.Row(spacing=0, tight=True, controls=row_cells))

        self.board_grid_col.controls = rows
        if update_ui:
            self.page.update()

    # -----------------------------------------------------------------
    # Handle Board Square Clicks & Execute Legal Moves
    # -----------------------------------------------------------------
    def on_square_click(self, clicked_sq: int):
        if self.board.is_game_over():
            return

        if self.selected_square is not None:
            candidate_moves = [
                m for m in self.legal_moves_for_selected if m.to_square == clicked_sq
            ]
            if candidate_moves:
                chosen_move = candidate_moves[0]
                if len(candidate_moves) > 1 or chosen_move.promotion is not None:
                    self._open_promotion_dialog(self.selected_square, clicked_sq)
                    return

                self.execute_move(chosen_move)
                return

        piece = self.board.piece_at(clicked_sq)
        if piece and piece.color == self.board.turn:
            self.selected_square = clicked_sq
            self.legal_moves_for_selected = [
                m for m in self.board.legal_moves if m.from_square == clicked_sq
            ]
        else:
            self.selected_square = None
            self.legal_moves_for_selected = []

        self.draw_board()

    def _open_promotion_dialog(self, from_sq: int, to_sq: int):
        t = UI_THEMES[self.ui_mode]
        options = [
            ("♕ Queen", chess.QUEEN),
            ("♖ Rook", chess.ROOK),
            ("♗ Bishop", chess.BISHOP),
            ("♘ Knight", chess.KNIGHT),
        ]

        def pick_promo(piece_type: int):
            self._close_dialog(dlg)
            move = chess.Move(from_sq, to_sq, promotion=piece_type)
            self.execute_move(move)

        promo_buttons = [
            self._make_action_btn(label, lambda e, pt=pt: pick_promo(pt), primary=(pt == chess.QUEEN))
            for label, pt in options
        ]

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=t["bg_panel"],
            title=ft.Text("Pawn Promotion", weight=ft.FontWeight.BOLD, color=t["fg_primary"]),
            content=ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    ft.Text("Promote pawn to:", color=t["fg_secondary"]),
                    ft.Row(spacing=8, controls=promo_buttons),
                ],
            ),
        )
        self._open_dialog(dlg)

    def execute_move(self, move: chess.Move):
        if move not in self.board.legal_moves:
            return
        self.board.push(move)
        self.last_move = move
        self.selected_square = None
        self.legal_moves_for_selected = []
        self.best_move_arrow = None

        self.draw_board(update_ui=False)
        self.update_status_and_history(update_ui=True)

        if not self.board.is_game_over() and self.play_vs_engine and self.board.turn == chess.BLACK:
            if hasattr(self.page, "run_task"):
                self.page.run_task(self._delayed_engine_reply)

    async def _delayed_engine_reply(self):
        await asyncio.sleep(0.25)
        await self.play_engine_move_now()

    def update_status_and_history(self, update_ui: bool = True):
        if self.board.is_checkmate():
            winner = "White" if self.board.turn == chess.BLACK else "Black"
            status_text = f"🏆 Checkmate! {winner} wins!"
        elif self.board.is_stalemate():
            status_text = "🤝 Draw by Stalemate"
        elif self.board.is_insufficient_material():
            status_text = "🤝 Draw by Insufficient Material"
        elif self.board.is_check():
            turn_str = "White" if self.board.turn == chess.WHITE else "Black"
            status_text = f"⚠️ Check! {turn_str} to move"
        else:
            turn_str = "White" if self.board.turn == chess.WHITE else "Black"
            status_text = f"{turn_str} to move"

        self.status_banner.value = status_text

        legal_san_list = [self.board.san(m) for m in self.board.legal_moves]
        preview = ", ".join(legal_san_list[:22])
        if len(legal_san_list) > 22:
            preview += f" ... (+{len(legal_san_list) - 22} more)"
        self.legal_moves_lbl.value = (
            f"Count ({len(legal_san_list)}): {preview if preview else 'No legal moves'}"
        )

        temp_board = chess.Board()
        moves_text = []
        move_stack = list(self.board.move_stack)
        for i in range(0, len(move_stack), 2):
            move_num = (i // 2) + 1
            w_san = temp_board.san(move_stack[i])
            temp_board.push(move_stack[i])
            b_san = ""
            if i + 1 < len(move_stack):
                b_san = temp_board.san(move_stack[i + 1])
                temp_board.push(move_stack[i + 1])
            moves_text.append(f"{move_num:>2}. {w_san:<8} {b_san:<8}")

        self.history_text_lbl.value = "\n".join(moves_text) if moves_text else "No moves played yet."

        if update_ui:
            self.page.update()

    def reset_board(self):
        self.board.reset()
        self.selected_square = None
        self.legal_moves_for_selected = []
        self.last_move = None
        self.best_move_arrow = None
        self.eval_score_lbl.value = "Evaluation: 0.00 (Equal)"
        self.best_move_lbl.value = "Suggested Best Move: —"
        self.draw_board(update_ui=False)
        self.update_status_and_history(update_ui=True)

    def undo_move(self):
        if len(self.board.move_stack) > 0:
            self.board.pop()
            if self.play_vs_engine and len(self.board.move_stack) > 0 and self.board.turn == chess.BLACK:
                self.board.pop()
            self.last_move = self.board.peek() if len(self.board.move_stack) > 0 else None
            self.selected_square = None
            self.legal_moves_for_selected = []
            self.best_move_arrow = None
            self.draw_board(update_ui=False)
            self.update_status_and_history(update_ui=True)

    def flip_board(self):
        self.board_flipped = not self.board_flipped
        self.draw_board(update_ui=True)

    # -----------------------------------------------------------------
    # Stockfish UCI Engine Connection & Non-Blocking Async Analysis
    # -----------------------------------------------------------------
    async def browse_stockfish_dialog(self, e=None):
        if self.file_picker is not None:
            try:
                files = await self.file_picker.pick_files(
                    dialog_title="Select Stockfish Executable Binary",
                    allow_multiple=False,
                )
                if files and len(files) > 0 and getattr(files[0], "path", None):
                    self.connect_stockfish(files[0].path, silent=False)
                    return
            except Exception:
                pass
        self._open_manual_path_dialog()

    def _open_manual_path_dialog(self):
        t = UI_THEMES[self.ui_mode]
        path_field = ft.TextField(
            label="Full path to Stockfish executable (.exe or binary)",
            value=self.engine_path or "",
            color=t["fg_primary"],
        )

        def save_path(e):
            self._close_dialog(dlg)
            if path_field.value:
                self.connect_stockfish(path_field.value.strip(), silent=False)

        dlg = ft.AlertDialog(
            bgcolor=t["bg_panel"],
            title=ft.Text("Set Stockfish Path", weight=ft.FontWeight.BOLD, color=t["fg_primary"]),
            content=path_field,
            actions=[
                _make_text_button("Cancel", lambda e: self._close_dialog(dlg)),
                _make_text_button("Connect", save_path),
            ],
        )
        self._open_dialog(dlg)

    def connect_stockfish(self, path: str, silent: bool = False):
        abs_path = os.path.abspath(path)
        if not os.path.isfile(abs_path) or not os.access(abs_path, os.X_OK):
            if not silent:
                self._show_info_dialog(
                    "Invalid Executable",
                    "The selected file is not a valid executable binary.",
                )
            return

        with self.engine_lock:
            try:
                if self.engine:
                    self.engine.quit()
                self.engine = chess.engine.SimpleEngine.popen_uci(abs_path)
                self.engine_path = abs_path
                engine_name = self.engine.id.get("name", "Stockfish UCI")
                self.engine_status_lbl.value = f"🟢 Connected: {engine_name}"
                self.page.update()
                if not silent:
                    self._show_info_dialog(
                        "Engine Connected",
                        f"Successfully connected to chess engine:\n{engine_name}",
                    )
            except Exception as exc:
                self.engine = None
                self.engine_status_lbl.value = (
                    "🟡 External Stockfish not linked (Built-in tactical analyzer active)"
                )
                self.page.update()
                if not silent:
                    self._show_info_dialog(
                        "Stockfish Connection Error",
                        f"Could not launch the selected engine binary:\n{exc}\n\n"
                        "Please make sure you selected a valid Stockfish UCI executable.",
                    )

    def _evaluate_material_fallback(self, board: chess.Board) -> float:
        values = {
            chess.PAWN: 1.0,
            chess.KNIGHT: 3.1,
            chess.BISHOP: 3.3,
            chess.ROOK: 5.0,
            chess.QUEEN: 9.0,
            chess.KING: 0.0,
        }
        score = 0.0
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p:
                val = values[p.piece_type]
                score += val if p.color == chess.WHITE else -val
        return score

    def _choose_best_move_and_score(self, board_snapshot: chess.Board):
        if board_snapshot.is_game_over():
            return None, "Game Over"

        with self.engine_lock:
            if self.engine is not None:
                try:
                    info = self.engine.analyse(
                        board_snapshot,
                        chess.engine.Limit(time=self.engine_time_limit),
                    )
                    pv = info.get("pv", [])
                    best_move = pv[0] if pv else None
                    score_obj = info["score"].white()
                    if score_obj.is_mate():
                        score_str = f"Mate in {abs(score_obj.mate())}"
                    else:
                        cp = (score_obj.score() or 0) / 100.0
                        score_str = f"{cp:+.2f}"
                    return best_move, f"{score_str} (Stockfish)"
                except Exception:
                    pass

        # Built-in 1-ply tactical heuristic fallback on the isolated snapshot
        best_move = None
        best_val = -9999.0 if board_snapshot.turn == chess.WHITE else 9999.0
        center_squares = {chess.D4, chess.E4, chess.D5, chess.E5}

        for move in board_snapshot.legal_moves:
            board_snapshot.push(move)
            if board_snapshot.is_checkmate():
                board_snapshot.pop()
                return move, "Checkmate!"
            val = self._evaluate_material_fallback(board_snapshot)
            if move.to_square in center_squares:
                val += 0.25 if board_snapshot.turn == chess.BLACK else -0.25
            board_snapshot.pop()

            if board_snapshot.turn == chess.WHITE and val > best_val:
                best_val = val
                best_move = move
            elif board_snapshot.turn == chess.BLACK and val < best_val:
                best_val = val
                best_move = move

        return best_move, f"{best_val:+.2f} (Built-in Eval)"

    async def request_engine_hint(self, e=None):
        if self.board.is_game_over():
            return

        board_snapshot = self.board.copy()
        expected_fen = board_snapshot.fen()

        best_move, score_text = await asyncio.to_thread(
            self._choose_best_move_and_score, board_snapshot
        )
        if best_move and self.board.fen() == expected_fen:
            san_str = board_snapshot.san(best_move)
            self.best_move_arrow = (best_move.from_square, best_move.to_square)
            self.eval_score_lbl.value = f"Evaluation: {score_text}"
            self.best_move_lbl.value = (
                f"Suggested Best Move: {san_str} ({best_move.uci()})"
            )
            self.draw_board(update_ui=True)

    async def play_engine_move_now(self, e=None):
        if self.board.is_game_over():
            return

        board_snapshot = self.board.copy()
        expected_fen = board_snapshot.fen()

        best_move, score_text = await asyncio.to_thread(
            self._choose_best_move_and_score, board_snapshot
        )
        if best_move and self.board.fen() == expected_fen:
            san_str = board_snapshot.san(best_move)
            self.eval_score_lbl.value = f"Evaluation: {score_text}"
            self.best_move_lbl.value = f"Engine Played: {san_str}"
            self.execute_move(best_move)

    # -----------------------------------------------------------------
    # Dialog Helpers & Informational Modals (Flet 1.0+ & 0.28 Compatible)
    # -----------------------------------------------------------------
    def _open_dialog(self, dlg: ft.AlertDialog):
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(dlg)
        elif hasattr(self.page, "open"):
            self.page.open(dlg)
        else:
            self.page.dialog = dlg
            dlg.open = True
            self.page.update()

    def _close_dialog(self, dlg: ft.AlertDialog = None):
        if hasattr(self.page, "pop_dialog"):
            self.page.pop_dialog()
        elif hasattr(self.page, "close") and dlg is not None:
            self.page.close(dlg)
        elif dlg is not None:
            dlg.open = False
            self.page.update()

    def _show_info_dialog(self, title: str, message: str):
        t = UI_THEMES[self.ui_mode]
        dlg = ft.AlertDialog(
            bgcolor=t["bg_panel"],
            title=ft.Text(title, weight=ft.FontWeight.BOLD, color=t["fg_primary"]),
            content=ft.Text(message, color=t["fg_secondary"]),
            actions=[
                _make_text_button("OK", lambda e: self._close_dialog(dlg)),
            ],
        )
        self._open_dialog(dlg)

    def show_about_dialog(self):
        self._show_info_dialog(
            "About ChessCoach",
            "ChessCoach - Smart Chess Trainer & Analysis\n\n"
            "Version: 2.1.0 (Flet 1.0+ Edition)\n"
            "Framework: Python Flet GUI\n"
            "Rules & Logic: python-chess library\n"
            "Engine: Stockfish UCI Integration\n\n"
            "An interactive 2D chess analysis and training platform.",
        )

    def show_support_email_dialog(self):
        self._show_info_dialog(
            "Technical Support Email",
            "Technical Support\n\n"
            "No technical support email address has been configured for this project yet.\n\n"
            "(Integration Point: Set your support contact in chesscoach_flet.py)",
        )

    def show_financial_support_dialog(self):
        self._show_info_dialog(
            "Financial Support",
            "Financial Support\n\n"
            "No financial support channels or payment methods are configured for this project.\n\n"
            "(Integration Point: Configure support links in chesscoach_flet.py)",
        )

    def show_puzzle_placeholder(self, puzzle_type: str = "Puzzles"):
        self._show_info_dialog(
            puzzle_type,
            f"{puzzle_type}\n\n"
            "This puzzle training module is currently in development.\n"
            "Interactive exercises and tactical drills will be available in an upcoming release.",
        )

    def show_card_placeholder(self, card_name: str):
        self._show_info_dialog(
            card_name,
            f"{card_name}\n\n"
            "This module is currently in development.\n"
            "Full training content and interactive features will be available in an upcoming update.",
        )

    # -----------------------------------------------------------------
    # Settings Dialog (UI Light/Dark Mode + Chessboard Square Colors)
    # -----------------------------------------------------------------
    def open_settings_dialog(self):
        t = UI_THEMES[self.ui_mode]

        light_preview = ft.Container(
            width=28,
            height=28,
            bgcolor=self.light_sq_color,
            border=_border_all(1, t["border"]),
            border_radius=6,
        )
        dark_preview = ft.Container(
            width=28,
            height=28,
            bgcolor=self.dark_sq_color,
            border=_border_all(1, t["border"]),
            border_radius=6,
        )

        light_input = ft.TextField(
            label="Light Square HEX",
            value=self.light_sq_color,
            width=150,
            text_size=12,
        )
        dark_input = ft.TextField(
            label="Dark Square HEX",
            value=self.dark_sq_color,
            width=150,
            text_size=12,
        )

        def on_ui_mode_change(e):
            self.ui_mode = e.control.value
            self._save_settings()
            self._apply_theme()

        def on_preset_change(e):
            p = e.control.value
            self.board_preset = p
            self.light_sq_color = BOARD_THEMES[p]["light_sq"]
            self.dark_sq_color = BOARD_THEMES[p]["dark_sq"]
            light_input.value = self.light_sq_color
            dark_input.value = self.dark_sq_color
            light_preview.bgcolor = self.light_sq_color
            dark_preview.bgcolor = self.dark_sq_color
            self._save_settings()
            self._refresh_boards()

        def apply_custom_colors(e):
            l_val = (light_input.value or "").strip()
            d_val = (dark_input.value or "").strip()
            if HEX_COLOR_RE.match(l_val):
                self.light_sq_color = l_val
                light_preview.bgcolor = l_val
            if HEX_COLOR_RE.match(d_val):
                self.dark_sq_color = d_val
                dark_preview.bgcolor = d_val
            self._save_settings()
            self._refresh_boards()

        ui_radio_group = ft.RadioGroup(
            value=self.ui_mode,
            on_change=on_ui_mode_change,
            content=ft.Column(
                spacing=4,
                controls=[
                    ft.Radio(value="light", label="☀️ Light Mode (Light UI Theme)"),
                    ft.Radio(value="dark", label="🌙 Dark Mode (Dark UI Theme)"),
                ],
            ),
        )

        preset_radio_group = ft.RadioGroup(
            value=self.board_preset,
            on_change=on_preset_change,
            content=ft.Column(
                spacing=4,
                controls=[
                    ft.Radio(value=key, label=data["name"])
                    for key, data in BOARD_THEMES.items()
                ],
            ),
        )

        dlg = ft.AlertDialog(
            bgcolor=t["bg_panel"],
            title=ft.Text(
                "⚙ Appearance & Chessboard Settings",
                size=18,
                weight=ft.FontWeight.BOLD,
                color=t["fg_primary"],
            ),
            content=ft.Container(
                width=420,
                content=ft.Column(
                    tight=True,
                    spacing=14,
                    controls=[
                        ft.Text(
                            "1. Application Interface Theme (UI Mode)",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=t["fg_primary"],
                        ),
                        ui_radio_group,
                        ft.Divider(color=t["border"]),
                        ft.Text(
                            "2. Chessboard Square Colors (Light & Dark)",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=t["fg_primary"],
                        ),
                        preset_radio_group,
                        ft.Row(
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=10,
                            controls=[light_preview, light_input, dark_preview, dark_input],
                        ),
                        self._make_action_btn("🎨 Apply Custom HEX Colors", apply_custom_colors),
                    ],
                ),
            ),
            actions=[
                _make_text_button("✓ Save & Close", lambda e: self._close_dialog(dlg)),
            ],
        )
        self._open_dialog(dlg)

    # -----------------------------------------------------------------
    # Account Dialog (Guest / existing profiles / new profile)
    # -----------------------------------------------------------------
    def open_account_dialog(self):
        t = UI_THEMES[self.ui_mode]
        current = self.db.get_current_user()

        if current is None:
            status = "Guest mode: everything works, but nothing is saved."
        else:
            status = f"Signed in as {current['display_name']} (@{current['username']})"

        def switch_to(user_id: int):
            self._switch_account(user_id)
            self._close_dialog(dlg)

        def continue_as_guest(e):
            self._switch_to_guest()
            self._close_dialog(dlg)

        # One button per saved profile; the current one is highlighted with a tick.
        profile_buttons = []
        for user in self.db.list_users():
            is_current = current is not None and user["user_id"] == current["user_id"]
            label = f"{'✓ ' if is_current else ''}{user['display_name']}  (@{user['username']})"
            profile_buttons.append(
                self._make_action_btn(
                    label,
                    lambda e, uid=user["user_id"]: switch_to(uid),
                    primary=is_current,
                )
            )
        if profile_buttons:
            profiles_area = ft.Container(
                height=min(len(profile_buttons) * 44, 176),
                content=ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, controls=profile_buttons),
            )
        else:
            profiles_area = ft.Text("No profiles yet. Create one below.", size=12, color=t["fg_secondary"])

        username_input = ft.TextField(label="Username (unique)", width=190, text_size=12)
        display_input = ft.TextField(label="Display name (optional)", width=190, text_size=12)
        # Our own error line instead of TextField.error_text: that property's name
        # differs between Flet versions, a plain Text works the same everywhere.
        error_label = ft.Text("", size=12, color="#EF4444", visible=False)

        def show_error(message: str):
            error_label.value = f"⚠ {message}"
            error_label.visible = True
            try:
                error_label.update()  # refresh just this control inside the open dialog
            except Exception:
                self.page.update()

        def create_profile(e):
            error = self._create_account(username_input.value or "", display_input.value or "")
            if error:
                show_error(error)  # keep the dialog open and show why
                return
            self._close_dialog(dlg)

        dlg = ft.AlertDialog(
            bgcolor=t["bg_panel"],
            title=ft.Text("👤 Account / Profile", size=18, weight=ft.FontWeight.BOLD, color=t["fg_primary"]),
            content=ft.Container(
                width=420,
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        ft.Text(status, size=12, color=t["fg_secondary"]),
                        ft.Divider(color=t["border"]),
                        ft.Text("Profiles", size=13, weight=ft.FontWeight.BOLD, color=t["fg_primary"]),
                        profiles_area,
                        self._make_action_btn(
                            "✓ Guest (nothing is saved)" if current is None else "Continue as Guest",
                            continue_as_guest,
                            primary=current is None,
                        ),
                        ft.Divider(color=t["border"]),
                        ft.Text("New profile", size=13, weight=ft.FontWeight.BOLD, color=t["fg_primary"]),
                        ft.Row(spacing=10, controls=[username_input, display_input]),
                        error_label,
                        self._make_action_btn("➕ Create & sign in", create_profile, primary=True),
                    ],
                ),
            ),
            actions=[
                _make_text_button("Close", lambda e: self._close_dialog(dlg)),
            ],
        )
        self._open_dialog(dlg)

    # -----------------------------------------------------------------
    # Apply Selected UI Theme Across All Views
    # -----------------------------------------------------------------
    def _apply_theme(self):
        t = UI_THEMES[self.ui_mode]
        self.page.theme_mode = ft.ThemeMode.DARK if self.ui_mode == "dark" else ft.ThemeMode.LIGHT
        self.page.bgcolor = t["bg_main"]

        # Top Bar
        self.top_bar.bgcolor = t["bg_header"]
        self.brand_title.color = t["fg_primary"]
        self.hamburger_btn.bgcolor = t["accent"] if self.sidebar_open else t["btn_bg"]
        self.hamburger_icon_text.color = "#FFFFFF" if self.sidebar_open else t["fg_primary"]
        self.settings_btn.bgcolor = t["btn_bg"]
        self.settings_btn_text.color = t["btn_fg"]
        self.account_btn.bgcolor = t["btn_bg"]
        self.account_btn_text.color = t["btn_fg"]

        # Content & Views
        self.content_area.bgcolor = t["bg_main"]
        self._populate_sidebar()
        self._build_homepage()
        self._build_engine_page()
        self.homepage_view.visible = self.current_page == "homepage"
        self.engine_view.visible = self.current_page == "engine"
        self.opening_trainer_view.visible = self.current_page == "opening_trainer"
        if self.level_trainer is not None:  # also re-reads progress after an account change
            self.level_trainer.set_theme(t, self._board_colors(), update=False)
        self.page.update()

    # -----------------------------------------------------------------
    # Clean Shutdown on Window Close
    # -----------------------------------------------------------------
    def _on_window_event(self, e):
        if getattr(e, "data", "") == "close":
            self.cleanup()

    def cleanup(self):
        with self.engine_lock:
            if self.engine is not None:
                try:
                    self.engine.quit()
                except Exception:
                    pass
                self.engine = None


def main(page: ft.Page):
    ChessCoachFletApp(page)


if __name__ == "__main__":
    # Compatible with both Flet 1.0+ (`ft.run(main)`) and legacy Flet 0.28 (`ft.app(target=main)`)
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)