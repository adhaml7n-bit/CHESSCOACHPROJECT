"""
ChessCoach - opening hub screen (OpeningHubView)
================================================
The start page of an opening, built from the owner's design of 2026-11-17:
the introduction and a board with the ideal setup on top, the chapters below.
A ready chapter shows its progress and a Start / Resume training / Practice
again button; a chapter without content shows "Coming soon".

Data comes from an opening file such as catalan_opening.json (opening_hub.py);
colours come from UI_THEMES and the board colours the app passes in.
"""

import chess
import flet as ft

from board_pieces import piece_controls
from flet_compat import border_all, pad_symmetric
from level_trainer import summarize_chapter
from opening_hub import chapter_unlock_states, load_hub_chapters, load_opening

SETUP_SQUARE = 38
SETUP_PIECE = 24
SETUP_CARD_WIDTH = 350
CARD_SIDE_WIDTH = 260  # right side of a chapter card: badge, progress bar, button
BUTTON_LABELS = {"not_started": "Start", "in_progress": "Resume training →", "completed": "Practice again"}


class OpeningHubView:
    """The start page of one opening. Put `root` into the page.

    on_open_chapter(path) is called with a chapter file when its button is
    pressed. passed_now is the app's {(user id, chapter id): levels passed}
    dict, so a Guest's progress in this app session shows on the cards too.
    """

    def __init__(self, page, opening_path, theme: dict, board_colors: dict, db=None,
                 on_open_chapter=None, passed_now: dict | None = None):
        self.page = page
        self.theme = theme
        self.board_colors = board_colors
        self.db = db
        self.on_open_chapter = on_open_chapter
        self.passed_now = passed_now if passed_now is not None else {}
        self.opening = load_opening(opening_path)
        self.chapters = load_hub_chapters(self.opening)
        self.root = ft.Container(expand=True, padding=pad_symmetric(horizontal=28, vertical=24))
        self.render(update=False)

    # -----------------------------------------------------------------
    # Public
    # -----------------------------------------------------------------
    def set_theme(self, theme: dict, board_colors: dict, update: bool = True) -> None:
        """Called by the app after a theme, board colour or account change."""
        self.theme = theme
        self.board_colors = board_colors
        self.render(update)

    def render(self, update: bool = True) -> None:
        """Rebuilds the page; also re-reads the progress shown on the chapter cards."""
        t = self.theme
        self.root.bgcolor = t["bg_main"]
        controls = [self._top(), ft.Container(height=8), self._text("Chapters to master".upper(), size=20, bold=True)]
        note = self.opening.get("release_note")
        if note:
            controls.append(self._text(note, size=13, color=t["fg_secondary"]))
        summaries = [self._summary(item["chapter"]) if item["chapter"] is not None else None for item in self.chapters]
        unlocked = chapter_unlock_states(self.chapters, summaries)
        controls.extend(
            self._chapter_card(item, summary, is_open)
            for item, summary, is_open in zip(self.chapters, summaries, unlocked)
        )
        self.root.content = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=16, controls=controls)
        if update:
            self.page.update()

    # -----------------------------------------------------------------
    # Building blocks
    # -----------------------------------------------------------------
    def _text(self, value: str, size: int = 14, color: str | None = None, bold: bool = False) -> ft.Text:
        return ft.Text(value, size=size, color=color or self.theme["fg_primary"],
                       weight=ft.FontWeight.BOLD if bold else None)

    def _badge(self, label: str, bgcolor: str, color: str) -> ft.Container:
        return ft.Container(
            bgcolor=bgcolor,
            border_radius=8,
            padding=pad_symmetric(horizontal=10, vertical=4),
            content=ft.Text(label, size=12, weight=ft.FontWeight.BOLD, color=color),
        )

    def _button(self, label: str, on_click) -> ft.Container:
        t = self.theme
        return ft.Container(
            bgcolor=t["accent"],
            border_radius=8,
            padding=pad_symmetric(horizontal=16, vertical=10),
            on_click=on_click,
            ink=True,
            content=ft.Text(label, size=14, weight=ft.FontWeight.BOLD, color=t["fg_on_accent"]),
        )

    def _progress(self, done: int, total: int) -> ft.Container:
        t = self.theme
        if done <= 0:
            parts = [(1, t["border"])]
        elif done >= total:
            parts = [(1, t["success"])]
        else:
            parts = [(done, t["success"]), (total - done, t["border"])]
        return ft.Container(
            width=CARD_SIDE_WIDTH,
            content=ft.Row(spacing=0, controls=[
                ft.Container(expand=weight, height=6, bgcolor=color) for weight, color in parts
            ]),
        )

    # -----------------------------------------------------------------
    # Top: introduction and ideal setup
    # -----------------------------------------------------------------
    def _top(self) -> ft.Row:
        opening, t = self.opening, self.theme
        left = [self._text(opening["title"].upper(), size=34, bold=True)]
        if opening.get("subtitle"):
            left.append(self._text(opening["subtitle"].upper(), size=20, color=t["fg_secondary"]))
        left.append(ft.Container(height=4))
        left.append(self._text(opening["intro"], size=15))
        focus = opening.get("strategic_focus") or []
        if focus:
            left.append(ft.Column(spacing=2, controls=[
                self._text("Strategic focus", size=15, bold=True),
                self._text(" • ".join(focus), size=15),
            ]))
        controls = [ft.Container(expand=True, content=ft.Column(spacing=10, controls=left))]
        if opening.get("setup"):
            controls.append(self._setup_card(opening["setup"]))
        return ft.Row(spacing=24, vertical_alignment=ft.CrossAxisAlignment.START, controls=controls)

    def _setup_card(self, setup: dict) -> ft.Container:
        t = self.theme
        return ft.Container(
            width=SETUP_CARD_WIDTH,
            bgcolor=t["bg_panel"],
            border=border_all(1, t["card_border"]),
            border_radius=12,
            padding=16,
            content=ft.Column(
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    self._text(setup.get("title", "Ideal setup").upper(), size=15, bold=True),
                    self._setup_board(setup),
                ],
            ),
        )

    def _setup_board(self, setup: dict) -> ft.Container:
        """The setup position: the focus square (e.g. the g2-bishop) filled, its path outlined."""
        c, size = self.board_colors, SETUP_SQUARE
        board = chess.Board(setup["fen"])
        focus = chess.parse_square(setup["focus_square"]) if setup.get("focus_square") else None
        path = {chess.parse_square(name) for name in setup.get("path", [])}
        white_bottom = self.opening.get("player_color", "white") == "white"
        rows = []
        for row in range(8):
            rank = 7 - row if white_bottom else row
            cells = []
            for col in range(8):
                file = col if white_bottom else 7 - col
                square = chess.square(file, rank)
                is_light = (file + rank) % 2 == 1
                fill = c["last_move"] if square == focus else (c["light_sq"] if is_light else c["dark_sq"])
                items = []
                if square in path:
                    items.append(ft.Container(width=size, height=size, border_radius=3,
                                              border=border_all(3, c["hint_sq"])))
                piece = board.piece_at(square)
                if piece:  # a picture from assets/pieces (glyph as backup), see board_pieces.py
                    items.extend(piece_controls(piece, size, c, glyph_size=SETUP_PIECE))
                cells.append(ft.Container(width=size, height=size, bgcolor=fill,
                                          content=ft.Stack(width=size, height=size, controls=items)))
            rows.append(ft.Row(spacing=0, tight=True, controls=cells))
        return ft.Container(
            border_radius=4,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(spacing=0, tight=True, controls=rows),
        )

    # -----------------------------------------------------------------
    # Bottom: chapter cards
    # -----------------------------------------------------------------
    def _summary(self, chapter: dict) -> dict:
        chapter_id = chapter["chapter_meta"]["chapter_id"]
        rows = {}
        if self.db is not None:
            try:
                rows = self.db.get_chapter_progress(chapter_id)
            except Exception as exc:  # a locked database must not hide the page
                print(f"[ChessCoach] Could not read progress: {exc}")
        user = getattr(self.db, "current_user_id", None)
        return summarize_chapter(chapter, rows, self.passed_now.get((user, chapter_id), set()))

    def _open(self, path: str) -> None:
        if self.on_open_chapter:
            self.on_open_chapter(path)

    def _chapter_card(self, item: dict, summary: dict | None, unlocked: bool) -> ft.Container:
        t = self.theme
        title = f"Chapter {item['number']}: {item['title']}"
        chapter = item["chapter"]
        if chapter is None or summary is None:
            return self._coming_soon_card(title, item["error"])

        lines = len(chapter["lines"])
        pass_mark = chapter["chapter_meta"].get("min_accuracy_to_pass", 0)
        details = (f"{summary['levels_total']} levels • {lines} branch{'es' if lines != 1 else ''} • "
                   f"Target accuracy: {pass_mark}%")
        if not unlocked:
            return self._locked_card(title, details, item["number"] - 1)

        side = [
            self._badge(f"{summary['percent']}% complete".upper(), t["success"], t["bg_main"]),
            self._progress(summary["levels_passed"], summary["levels_total"]),
            self._button(BUTTON_LABELS[summary["status"]].upper(), lambda e, p=item["path"]: self._open(p)),
        ]
        return ft.Container(
            bgcolor=t["bg_panel"],
            border=border_all(1, t["card_border"]),
            border_radius=12,
            padding=20,
            content=ft.Row(
                spacing=20,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(expand=True, content=ft.Column(spacing=8, controls=[
                        self._text(title, size=22, bold=True),
                        self._text(details, size=14, color=t["fg_secondary"]),
                    ])),
                    ft.Container(width=CARD_SIDE_WIDTH, content=ft.Column(
                        spacing=10, horizontal_alignment=ft.CrossAxisAlignment.END, controls=side)),
                ],
            ),
        )

    def _locked_card(self, title: str, details: str, previous_number: int) -> ft.Container:
        t = self.theme
        locked_btn = ft.Container(
            bgcolor=t["btn_bg"],
            border_radius=8,
            padding=pad_symmetric(horizontal=16, vertical=10),
            content=ft.Text(f"FINISH CHAPTER {previous_number}", size=14,
                            weight=ft.FontWeight.BOLD, color=t["fg_muted"]),
        )
        side = [
            self._badge("🔒 LOCKED", t["btn_bg"], t["fg_secondary"]),
            self._progress(0, 1),
            locked_btn,
        ]
        return ft.Container(
            bgcolor=t["section_bar_bg"],
            border=border_all(1, t["card_border"]),
            border_radius=12,
            padding=20,
            content=ft.Row(
                spacing=20,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(expand=True, content=ft.Column(spacing=8, controls=[
                        self._text(title, size=22, color=t["fg_muted"], bold=True),
                        self._text(details, size=14, color=t["fg_muted"]),
                        self._text(f"Complete Chapter {previous_number} to unlock.", size=13, color=t["fg_secondary"]),
                    ])),
                    ft.Container(width=CARD_SIDE_WIDTH, content=ft.Column(
                        spacing=10, horizontal_alignment=ft.CrossAxisAlignment.END, controls=side)),
                ],
            ),
        )

    def _coming_soon_card(self, title: str, error: str | None) -> ft.Container:
        t = self.theme
        left = [self._text(title, size=22, color=t["fg_muted"], bold=True)]
        if error:
            left.append(self._text(f"This chapter couldn't be loaded: {error}", size=12, color=t["danger"]))
        placeholder = [
            ft.Container(width=int(CARD_SIDE_WIDTH * share), height=6, border_radius=3, bgcolor=t["border"])
            for share in (1.0, 0.85, 0.7)
        ]
        side = [self._badge("Coming soon".upper(), t["btn_bg"], t["fg_secondary"])] + placeholder
        return ft.Container(
            bgcolor=t["section_bar_bg"],
            border=border_all(1, t["card_border"]),
            border_radius=12,
            padding=20,
            content=ft.Row(
                spacing=20,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(expand=True, content=ft.Column(spacing=8, controls=left)),
                    ft.Container(width=CARD_SIDE_WIDTH, content=ft.Column(
                        spacing=8, horizontal_alignment=ft.CrossAxisAlignment.END, controls=side)),
                ],
            ),
        )
