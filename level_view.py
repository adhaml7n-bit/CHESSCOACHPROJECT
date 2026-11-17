"""
ChessCoach - training screen for format-2 chapters (learn and quiz levels)
=========================================================================
Flet view of level_trainer.LevelSession, built from the design approved on
2026-11-17 (DESIGN.md section 8). A chapter opens on its levels page: every
level as a tile, with a Continue button for the next level to play (owner's
request 2026-11-17: the level bar above the board took too much room). A level
then fills the screen: a one-line header, the board on the left and the panel
on the right; "All levels" goes back to the levels page.

    learn  the moves are shown one by one with their ideas (Back / Next)
    quiz   the player plays their own moves with no explanations; the 1st
           mistake shows the hint (or highlights the piece to move when the
           move has no written hint), the 2nd shows the correct move, which
           the player must then play. The opponent's moves play by themselves.
    done   the level's result; the next level opens once this one is passed

Colours come from the dictionaries the app passes in (UI_THEMES and the board
colours), so the screen follows Light / Dark mode and the board settings.
Progress is saved through ChessCoachDB; a database problem never stops a lesson.
"""

import asyncio
import os

import chess
import flet as ft

from board_pieces import ASSETS_DIR
from board_view import click_square, render_board
from engine_judge import pawns
from flet_compat import border_all, pad_symmetric
from level_trainer import LevelSession, level_line_id, load_level_chapter, summarize_levels

OPPONENT_DELAY_SECONDS = 0.6  # pause before the opponent's reply in a quiz
LEVEL_ICONS = {"learn": "📖", "quiz": "✎"}

# Layout: the board fills the height left by the header, and the panel and the
# text grow with it, so a big window is not wasted.
BASE_SQUARE = 56            # square size the screen was designed at (scale 1.0)
MIN_SQUARE, MAX_SQUARE = 48, 96
MAX_SCALE = 1.35            # text and panel grow at most this much
PANEL_BASE_WIDTH = 360
CHROME_HEIGHT = 110         # page padding, the one-line header and the space under it
SIDE_PADDING, GAP = 40, 20  # page padding (left + right); gap between board and panel
DEFAULT_AREA = (925, 722)   # the app's start window (1180 x 780) minus the sidebar and the top bar

# Levels page: tiles in rows that fill the width (sizes at scale 1.0).
TILE_MIN_WIDTH, TILE_HEIGHT, TILE_GAP = 160, 84, 12
GRID_MARGIN = 8             # kept free at the right so rounding never wraps a row early


def _clamp(value, low, high):
    return max(low, min(high, value))


def grid_columns(width: float, scale: float = 1.0) -> tuple[int, int]:
    """Columns and tile width of the levels page for a content area `width`
    pixels wide: as many tiles of at least TILE_MIN_WIDTH (scaled) as fit,
    stretched to fill the row."""
    usable = max(0, int(width) - SIDE_PADDING - GRID_MARGIN)
    columns = max(1, (usable + TILE_GAP) // (round(TILE_MIN_WIDTH * scale) + TILE_GAP))
    return columns, (usable - TILE_GAP * (columns - 1)) // columns


def level_to_continue(levels: list[dict]) -> int | None:
    """The level a player goes on with: the first one not passed yet (it is
    always open, since every level before it is passed). None when every level
    is passed. levels is level_trainer.summarize_levels()."""
    return next((level["level"] for level in levels if level["unlocked"] and not level["passed"]), None)


def compute_layout(width: float, height: float) -> dict:
    """Board and panel sizes for a content area of width x height pixels.

    The board gets the biggest square size (a multiple of 4 between MIN_SQUARE
    and MAX_SQUARE) that fits the height and still leaves room for the panel
    beside it; the panel and the text grow with the board. When the area is too
    narrow for both side by side, the panel goes under the board (the row wraps).
    Returns square, piece (font size), panel (width) and scale (for text).
    """
    def panel_for(square: int) -> int:
        return round(PANEL_BASE_WIDTH * _clamp(square / BASE_SQUARE, 1.0, MAX_SCALE))

    tallest = int(_clamp((height - CHROME_HEIGHT) / 8, MIN_SQUARE, MAX_SQUARE)) // 4 * 4
    square = next((size for size in range(tallest, MIN_SQUARE - 1, -4)
                   if 8 * size + GAP + panel_for(size) <= width - SIDE_PADDING), None)
    if square is None:  # too narrow for side by side: only height and width limit the board
        widest = int(_clamp((width - SIDE_PADDING) / 8, MIN_SQUARE, MAX_SQUARE)) // 4 * 4
        square = min(tallest, widest)
    return {
        "square": square,
        "piece": round(square * 0.6),
        "panel": panel_for(square),
        "scale": round(_clamp(square / BASE_SQUARE, 1.0, MAX_SCALE), 2),
    }


def move_label(step: dict) -> str:
    """'7. Qc2' for a White move, '7... Nbd7' for a Black move."""
    dots = "." if step["turn"] == "white" else "..."
    return f"{step['move_number']}{dots} {step['san']}"


def feedback_marks(feedback: dict | None, busy: bool = False) -> dict:
    """Squares to outline after a mistake: the correct move's squares once it is
    shown, or the piece to move as an automatic hint when the move has no
    written hint. feedback holds the submit result ("result") and the expected
    move ("question" with its uci)."""
    if not feedback or busy:
        return {}
    if feedback["kind"] == "shown":
        move = chess.Move.from_uci(feedback["result"]["correct_uci"])
        return {move.from_square: 3, move.to_square: 4}
    if feedback["kind"] == "hint" and not feedback["result"]["hint"]:
        return {chess.parse_square(feedback["question"]["uci"][:2]): 4}
    return {}


def review_days_text(days: list[int]) -> str:
    """[1, 7] -> 'tomorrow and in 7 days'; [1, 3, 7] -> 'tomorrow, in 3 days and in 7 days'."""
    parts = ["tomorrow" if day == 1 else f"in {day} days" for day in days]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


class ScreenBase:
    """What the training screen and the review screen share: sizing from the
    window, theme changes and the panel's building blocks. A subclass sets
    page, theme, board_colors, area and layout, and implements render()."""

    def set_theme(self, theme: dict, board_colors: dict, update: bool = True) -> None:
        """Called by the app after a theme, board colour or account change."""
        self.theme = theme
        self.board_colors = board_colors
        self.render(update)

    def relayout(self, update: bool = True) -> None:
        """Called by the app when the window or the sidebar changes size; redraws
        only when the board or panel size actually changes."""
        if compute_layout(*self._area_size()) != self.layout:
            self.render(update)

    def _area_size(self) -> tuple[float, float]:
        if self.area is None:
            return DEFAULT_AREA
        try:
            width, height = self.area()
            return float(width), float(height)
        except Exception:  # an unknown window size must never break the screen
            return DEFAULT_AREA

    def _size(self, value: int) -> int:
        """A size from the design (fonts, dots) scaled to the current layout."""
        return round(value * self.layout["scale"])

    def _text(self, value: str, size: int = 13, color: str | None = None, bold: bool = False) -> ft.Text:
        return ft.Text(
            value,
            size=self._size(size),
            color=color or self.theme["fg_primary"],
            weight=ft.FontWeight.BOLD if bold else None,
        )

    def _label(self, value: str) -> ft.Text:
        return self._text(value, size=12, color=self.theme["fg_secondary"])

    def _button(self, label: str, on_click, primary: bool = False) -> ft.Container:
        t = self.theme
        return ft.Container(
            bgcolor=t["accent"] if primary else t["btn_bg"],
            border_radius=8,
            padding=pad_symmetric(horizontal=self._size(14), vertical=self._size(8)),
            on_click=on_click,
            ink=True,
            content=ft.Text(
                label,
                size=self._size(13),
                weight=ft.FontWeight.W_600,
                color=t["fg_on_accent"] if primary else t["btn_fg"],
            ),
        )

    def _box(self, kind: str, title: str, lines: list[str]) -> ft.Container:
        """A coloured message box; kind is 'success', 'warning' or 'danger'."""
        t = self.theme
        return ft.Container(
            bgcolor=t[f"{kind}_bg"],
            border=border_all(1, t[kind]),
            border_radius=8,
            padding=12,
            content=ft.Column(
                spacing=4,
                controls=[self._text(title, color=t[kind], bold=True)] + [self._text(line) for line in lines],
            ),
        )

    def _segments(self, states: list[str]) -> ft.Row:
        """Progress of a quiz or review: one bar per question, coloured by its result."""
        t = self.theme
        colors = {"ok": t["success"], "hint": t["warning"], "shown": t["danger"],
                  "current": t["accent"], "pending": t["border"]}
        return ft.Row(
            spacing=3,
            controls=[ft.Container(expand=1, height=6, border_radius=3, bgcolor=colors[s]) for s in states],
        )

    def _progress(self, done: int, total: int) -> ft.Row:
        t = self.theme
        if done <= 0:
            parts = [(1, t["border"])]
        elif done >= total:
            parts = [(1, t["accent"])]
        else:
            parts = [(done, t["accent"]), (total - done, t["border"])]
        return ft.Row(spacing=0, controls=[ft.Container(expand=w, height=4, bgcolor=c) for w, c in parts])

    def _metric(self, label: str, value: str, color: str) -> ft.Container:
        return ft.Container(
            expand=1,
            bgcolor=self.theme["section_bar_bg"],
            border_radius=8,
            padding=10,
            content=ft.Column(spacing=2, controls=[self._label(label), self._text(value, size=22, color=color, bold=True)]),
        )

    def _save(self, method_name: str, *args) -> None:
        """Calls a ChessCoachDB method; a database problem never stops the lesson."""
        if self.db is None:
            return
        try:
            getattr(self.db, method_name)(*args)
        except Exception as exc:  # e.g. the file is locked for longer than the timeout
            print(f"[ChessCoach] Could not save progress ({method_name}): {exc}")

    # -----------------------------------------------------------------
    # Engine second opinion (DESIGN.md section 5). A subclass has
    # assistant, busy, feedback, _token and _answer(uci).
    # -----------------------------------------------------------------
    def _engine_ready(self) -> bool:
        assistant = getattr(self, "assistant", None)
        return assistant is not None and assistant.available

    def _submit(self, uci: str) -> None:
        """A move from the board. With an engine, a move that is not the lesson's
        move is checked first: a good alternative is not a mistake."""
        if self._engine_ready():
            check = self.session.peek(uci)
            if check["status"] == "off_book":
                self._ask_engine(check)
                return
        self._answer(uci)

    def _ask_engine(self, check: dict) -> None:
        """Asks the engine about an off-book move, in the background."""
        self.busy = True
        self.feedback = {"kind": "checking", "check": check}
        self.render()
        token = self._token
        if hasattr(self.page, "run_task"):
            self.page.run_task(self._judge_later, token, check)
        else:  # no async support: decide at once
            self._apply_verdict(token, check, self.assistant.judge(check["fen"], check["book_uci"], check["uci"]))

    async def _judge_later(self, token: int, check: dict) -> None:
        verdict = await asyncio.to_thread(self.assistant.judge, check["fen"], check["book_uci"], check["uci"])
        self._apply_verdict(token, check, verdict)

    def _apply_verdict(self, token: int, check: dict, verdict: dict | None) -> None:
        if token != self._token:  # the level or the review was restarted meanwhile
            return
        self.busy = False
        if verdict and verdict["acceptable"]:
            self.feedback = {"kind": "alternative", "check": check, "verdict": verdict}
            self.render()
        else:
            self._answer(check["uci"])  # a real mistake (or no verdict): the usual rules

    def _engine_feedback(self, feedback: dict) -> list:
        """Panel lines while the engine checks a move, or after it accepted it."""
        t = self.theme
        if feedback["kind"] == "checking":
            return [self._text("Checking your move with the engine…", color=t["fg_secondary"])]
        check, verdict = feedback["check"], feedback["verdict"]
        opinion = ("The engine likes it at least as much as the lesson's move."
                   if verdict["loss_cp"] <= 0 else "The engine rates it almost as strong as the lesson's move.")
        return [
            self._box("success", f"Good move: {check['label']}",
                      [opinion, "It isn't the move this lesson teaches, though. Find the lesson's move: no penalty."]),
            self._label(f"Engine opinion: the lesson's move {pawns(verdict['book_cp'])}, "
                        f"yours {pawns(verdict['played_cp'])}."),
        ]


class LevelTrainerView(ScreenBase):
    """The training screen of one format-2 chapter. Put `root` into the page.
    It opens on the levels page (show_levels); open_level(n) plays a level.

    theme        - UI_THEMES[ui_mode] of the app
    board_colors - a BOARD_THEMES preset with the user's light_sq / dark_sq and
                   the piece colours (piece_white, piece_black, piece_shadow)
    db           - the app's ChessCoachDB, or None to save nothing
    on_back      - called by the levels page's back button (the opening hub)
    area         - a function returning the (width, height) the screen may use;
                   the board, the panel and the level tiles are sized from it
                   (DEFAULT_AREA if None)
    """

    def __init__(self, page, chapter_path, theme: dict, board_colors: dict, db=None, on_back=None,
                 opponent_delay: float = OPPONENT_DELAY_SECONDS, passed_now: dict | None = None,
                 area=None, assistant=None):
        self.page = page
        self.theme = theme
        self.board_colors = board_colors
        self.db = db
        self.on_back = on_back
        self.opponent_delay = opponent_delay
        self.area = area
        self.assistant = assistant  # engine_judge.EngineAssistant, or None (no second opinion)
        self.layout = compute_layout(*self._area_size())

        self.chapter = load_level_chapter(chapter_path)
        meta = self.chapter["chapter_meta"]
        self.chapter_id = meta["chapter_id"]
        self.player_color = meta["player_color"]
        self.pass_mark = meta.get("min_accuracy_to_pass", 0)
        # (user id or None for a Guest, chapter id) -> levels passed while the app is open.
        # The app shares one dict between screens, so the opening hub sees it too.
        self._passed_now = passed_now if passed_now is not None else {}

        self.root = ft.Container(expand=True, padding=20)
        self.session: LevelSession | None = None  # the level on the board; None until one is opened
        self.showing_levels = True
        self.grid = None          # (columns, tile width) of the levels page
        self._levels: list[dict] = []
        self._token = 0
        self.show_levels(update=False)

    # -----------------------------------------------------------------
    # Public
    # -----------------------------------------------------------------
    def show_levels(self, update: bool = True) -> None:
        """Shows the levels page, with the progress read again."""
        self._token += 1          # a pending opponent reply or engine check of the level is dropped
        self._reset_level_state()
        self.showing_levels = True
        self.render(update)

    def open_level(self, number: int, update: bool = True) -> None:
        """Starts (or restarts) a level from its first position."""
        self.session = LevelSession(self.chapter, number)
        self._token += 1          # a pending opponent reply of the old level is dropped
        self._reset_level_state()
        self.showing_levels = False
        self.render(update)

    def render(self, update: bool = True) -> None:
        self.layout = compute_layout(*self._area_size())
        self._levels = self._load_levels()
        self.root.bgcolor = self.theme["bg_main"]
        if self.showing_levels:
            controls = self._levels_page()
        else:
            controls = [
                self._header(),
                ft.Row(
                    wrap=True,
                    spacing=20,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[self._board(), self._panel()],
                ),
            ]
        self.root.content = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=14, controls=controls)
        if update:
            self.page.update()

    def relayout(self, update: bool = True) -> None:
        """Called by the app when the window or the sidebar changes size: the
        board, or on the levels page the number of tiles per row, may change."""
        width, height = self._area_size()
        layout = compute_layout(width, height)
        if layout != self.layout or (self.showing_levels and grid_columns(width, layout["scale"]) != self.grid):
            self.render(update)

    def _reset_level_state(self) -> None:
        self.selected = None      # square of the selected piece
        self.feedback = None      # {"kind": "correct" | "hint" | "shown", "question": ..., "result": ...}
        self.busy = False         # True while the opponent's reply waits
        self.display = None       # (fen, uci) shown during that wait
        self.show_done = False
        self.result_saved = False
        self.engine_rows = None   # [(step, opinion)] of the "Use engine" card, None = not asked
        self.engine_running = False

    # -----------------------------------------------------------------
    # Progress
    # -----------------------------------------------------------------
    def _user_key(self):
        return getattr(self.db, "current_user_id", None)

    def _load_levels(self) -> list[dict]:
        rows = {}
        if self.db is not None:
            try:
                rows = self.db.get_chapter_progress(self.chapter_id)
            except Exception as exc:
                print(f"[ChessCoach] Could not read progress: {exc}")
        return summarize_levels(self.chapter, rows, self._passed_now.get((self._user_key(), self.chapter_id), set()))

    def _complete_level(self) -> None:
        if self.result_saved:
            return
        self.result_saved = True
        session = self.session
        accuracy = session.accuracy if session.kind == "quiz" else None
        self._save("save_line_result", self.chapter_id, level_line_id(session.level_number), accuracy)
        if session.passed:
            self._passed_now.setdefault((self._user_key(), self.chapter_id), set()).add(session.level_number)
        self.show_done = True

    # -----------------------------------------------------------------
    # Learn levels
    # -----------------------------------------------------------------
    def _learn_next(self) -> None:
        if self.session.is_complete:
            self._complete_level()
        else:
            self.session.next_step()
        self.render()

    def _learn_back(self) -> None:
        self.session.previous_step()
        self.render()

    # -----------------------------------------------------------------
    # Quiz levels
    # -----------------------------------------------------------------
    def _on_square(self, square: int) -> None:
        session = self.session
        if self.busy or self.show_done or session.kind != "quiz" or session.is_complete:
            return
        uci, self.selected = click_square(chess.Board(session.fen), self.selected, square)
        if uci:
            self._submit(uci)
        else:
            self.render()

    def _answer(self, uci: str) -> None:
        """Counts a move: correct, or a mistake with the level's on_mistake rules."""
        session = self.session
        question = session.current_question
        result = session.submit_move(uci)
        line_id = result.get("line_id")  # each question's own line (a level can hold several)

        if result["status"] == "incorrect":
            # fen = position before the move, played_san = the wrong move; review_days restart its plan.
            self._save("record_mistake", self.chapter_id, line_id, result["ply"], result["fen"],
                       result["played_san"], result["review_days"])
            kind = "hint" if result["action"] == "show_hint" else "shown"
            self.feedback = {"kind": kind, "question": question, "result": result}
            self.render()
            return
        if result["status"] != "correct":
            self.render()
            return

        if result["first_try"] and not result["retry"]:  # a second chance in the same run is not a review
            self._save("record_correct", self.chapter_id, line_id, result["ply"])
        self.feedback = {"kind": "correct", "question": question, "result": result}
        if result["opponent_moves"] and self.opponent_delay > 0 and hasattr(self.page, "run_task"):
            # Show the player's move first; the reply follows a moment later.
            self.busy = True
            self.display = (question["fen_after"], question["uci"])
            self.render()
            token = self._token
            self.page.run_task(self._play_reply_later, token)
        else:
            self._after_correct()

    async def _play_reply_later(self, token: int) -> None:
        await asyncio.sleep(self.opponent_delay)
        if token != self._token:  # another level was opened in the meantime
            return
        self.busy = False
        self.display = None
        self._after_correct()

    def _after_correct(self) -> None:
        if self.session.is_complete:
            self._complete_level()
        self.render()

    # -----------------------------------------------------------------
    # Training screen header (one line, so the board keeps the room)
    # -----------------------------------------------------------------
    def _header(self) -> ft.Row:
        session, t = self.session, self.theme
        level = session.level
        return ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            self._button("← All levels", lambda e: self.show_levels()),
            self._text(f"Level {session.level_number} of {len(self.chapter['levels'])}", size=18, bold=True),
            self._chip(f"{LEVEL_ICONS[level['type']]} {level['type'].capitalize()}"),
            ft.Container(expand=True, content=ft.Text(
                level["title"], size=self._size(14), color=t["fg_secondary"],
                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=level["title"],
            )),
        ])

    def _chip(self, label: str) -> ft.Container:
        return ft.Container(
            bgcolor=self.theme["section_bar_bg"],
            border_radius=6,
            padding=pad_symmetric(horizontal=self._size(8), vertical=self._size(3)),
            content=ft.Text(label, size=self._size(12), weight=ft.FontWeight.W_600, color=self.theme["fg_secondary"]),
        )

    # -----------------------------------------------------------------
    # Levels page: every level of the chapter as a tile
    # -----------------------------------------------------------------
    def _levels_page(self) -> list:
        t, levels = self.theme, self._levels
        meta = self.chapter["chapter_meta"]
        header = []
        if self.on_back:
            header.append(self._button(f"← {meta.get('opening_name') or 'Back'}", lambda e: self.on_back()))
        header.append(self._text(meta["chapter_title"], size=22, bold=True))

        passed = sum(1 for level in levels if level["passed"])
        percent = round(100 * passed / len(levels))
        next_number = level_to_continue(levels)
        if next_number is None:
            go_on = self._text(f"You've passed all {len(levels)} levels. Pick any level to practise it again.",
                               color=t["success"], bold=True)
        else:
            verb = "Start" if passed == 0 else "Continue"
            go_on = ft.Row(wrap=True, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                self._button(f"{verb}: level {next_number} →", lambda e, n=next_number: self.open_level(n), primary=True),
                self._text(levels[next_number - 1]["title"], color=t["fg_secondary"]),
            ])

        self.grid = grid_columns(self._area_size()[0], self.layout["scale"])
        tiles = [self._level_tile(level, self.grid[1], level["level"] == next_number) for level in levels]
        return [
            ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=header),
            ft.Column(spacing=6, controls=[
                self._label(f"{len(levels)} levels · {passed} passed · {percent}% complete"),
                self._progress(passed, len(levels)),
            ]),
            go_on,
            self._label(f"{LEVEL_ICONS['learn']} Learn: see the moves and their ideas · "
                        f"{LEVEL_ICONS['quiz']} Quiz: play them from memory · 🔒 Pass a level to open the next one"),
            ft.Row(wrap=True, spacing=TILE_GAP, run_spacing=TILE_GAP, controls=tiles),
        ]

    def _level_tile(self, level: dict, width: int, is_next: bool) -> ft.Container:
        t = self.theme
        number, kind = level["level"], level["type"]
        locked = not (level["unlocked"] or level["passed"])  # a passed level can always be practised
        if level["passed"]:
            accuracy = level["best_accuracy"]
            status = f"✓ {round(accuracy)}%" if kind == "quiz" and accuracy is not None else "✓"
            status_color, edge = t["success"], border_all(1, t["success"])
        elif locked:
            status, status_color, edge = "🔒", t["fg_muted"], border_all(1, t["card_border"])
        elif is_next:
            status, status_color, edge = "Next", t["accent"], border_all(2, t["accent"])
        else:  # open but not the next one (only after a level's pass mark was raised)
            status, status_color, edge = "", t["fg_secondary"], border_all(1, t["card_border"])
        text_color = t["fg_muted"] if locked else t["fg_primary"]
        return ft.Container(
            width=width,
            height=self._size(TILE_HEIGHT),
            bgcolor=t["section_bar_bg"] if locked else t["bg_panel"],
            border=edge,
            border_radius=10,
            padding=self._size(10),
            tooltip=level["title"],
            ink=not locked,
            on_click=None if locked else (lambda e, n=number: self.open_level(n)),
            content=ft.Column(spacing=self._size(4), controls=[
                ft.Row(spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Text(str(number), size=self._size(16), weight=ft.FontWeight.BOLD,
                            color=t["accent"] if is_next else text_color),
                    ft.Text(f"{LEVEL_ICONS[kind]} {kind.capitalize()}", size=self._size(11),
                            color=t["fg_muted"] if locked else t["fg_secondary"]),
                    ft.Container(expand=True),
                    ft.Text(status, size=self._size(11), weight=ft.FontWeight.BOLD, color=status_color),
                ]),
                ft.Text(level["title"], size=self._size(12), color=text_color,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ]),
        )

    # -----------------------------------------------------------------
    # Board
    # -----------------------------------------------------------------
    def _board(self) -> ft.Container:
        session = self.session
        if self.display is not None:
            fen, last_uci = self.display
        else:
            fen = session.fen
            last_uci = session.last_move["uci"] if session.last_move else None
        clickable = session.kind == "quiz" and not self.show_done
        return render_board(
            chess.Board(fen),
            self.board_colors,
            self.layout["square"],
            piece_size=self.layout["piece"],
            coord_size=self._size(10),
            dot_size=self._size(16),
            white_bottom=self.player_color == "white",
            selected=self.selected,
            last_move_uci=last_uci,
            marked=feedback_marks(self.feedback, self.busy),
            on_square=self._on_square if clickable else None,
        )

    # -----------------------------------------------------------------
    # Panel
    # -----------------------------------------------------------------
    def _panel(self) -> ft.Container:
        if self.show_done:
            body = self._done_panel()
        elif self.session.kind == "learn":
            body = self._learn_panel()
        else:
            body = self._quiz_panel()
        t = self.theme
        return ft.Container(
            width=self.layout["panel"],
            bgcolor=t["bg_panel"],
            border=border_all(1, t["card_border"]),
            border_radius=12,
            padding=16,
            content=ft.Column(spacing=10, controls=body),
        )

    def _learn_panel(self) -> list:
        session, t = self.session, self.theme
        step = session.current_step
        body = [
            self._label(f"Learn · step {session.step_index} of {session.step_count}"),
            self._progress(session.step_index, session.step_count),
        ]
        part, parts = session.current_part, len(session.parts)
        if step is None:  # the start of the level, or of its next line
            if session.part_index == 0:
                body.append(self._text(session.level["title"], size=18, bold=True))
                intro = session.level.get("intro")
                if not intro and session.level_number == 1:
                    intro = self.chapter["chapter_meta"].get("description")
                if intro:
                    body.append(self._text(intro, color=t["fg_secondary"]))
            else:
                body.append(self._text(f"Next line · {session.part_index + 1} of {parts}", size=18, bold=True))
            if part.get("intro"):
                body.append(self._text(part["intro"], color=t["fg_secondary"]))
            body.append(self._text("Press Next to see the first move.", size=12, color=t["fg_muted"]))
        else:
            side = "White" if step["turn"] == "white" else "Black"
            body.append(ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.END, controls=[
                self._text(move_label(step), size=24, bold=True),
                self._text(side, size=12, color=t["fg_muted"]),
            ]))
            if step["strategic_idea"]:
                body.append(self._text(step["strategic_idea"], size=14, bold=True))
            if step["explanation"]:
                body.append(self._text(step["explanation"], color=t["fg_secondary"]))
            body.append(self._move_list(step["ply"]))
            if session.at_part_end and part.get("key_ideas"):  # the end of one line of the level
                body.extend(self._key_ideas(part["key_ideas"]))
            if session.is_complete:  # the end of the level: how to play on
                body.extend(self._key_ideas())
        body.append(ft.Row(spacing=8, controls=[
            self._button("← Back", lambda e: self._learn_back()),
            self._button("Finish level ✓" if session.is_complete else "Next →", lambda e: self._learn_next(),
                         primary=True),
        ]))
        return body

    def _key_ideas(self, ideas=None) -> list:
        """Short 'how to play on' messages: the level's key_ideas, or the given ones (a part's)."""
        ideas = (self.session.level.get("key_ideas") or []) if ideas is None else ideas
        if not ideas:
            return []
        t = self.theme
        return [self._text("Your plan from here", size=14, color=t["accent"], bold=True)] + [
            self._text(f"• {idea}", color=t["fg_primary"]) for idea in ideas
        ]

    def _move_list(self, upto_ply: int) -> ft.Row:
        """The line up to the current move: earlier levels muted, the current move highlighted."""
        session, t = self.session, self.theme
        part = session.current_part
        line = self.chapter["lines"][part["line_id"]]
        first = part["from_ply"]
        tokens = []
        for step in line[:upto_ply]:
            text = (f"{step['move_number']}." if step["turn"] == "white" else "") + step["san"]
            if step["ply"] == upto_ply:
                tokens.append(self._text(text, size=12, color=t["accent"], bold=True))
            else:
                tokens.append(self._text(text, size=12, color=t["fg_muted"] if step["ply"] < first else t["fg_secondary"]))
        return ft.Row(wrap=True, spacing=6, controls=tokens)

    def _quiz_panel(self) -> list:
        session, t = self.session, self.theme
        if session.in_retry:
            body = [
                self._label(f"Second chance · position {session.retry_index + 1} of {len(session.retry_queue)}"),
                self._segments(session.question_states()),
                self._text("Your move", size=16, bold=True),
                self._text("You missed this position earlier. Show that you've got it now.", color=t["fg_secondary"]),
            ]
        else:
            number = min(session.answered_count + 1, session.question_count)
            body = [
                self._label(f"Quiz · question {number} of {session.question_count}"),
                self._segments(session.question_states()),
                self._text("Your move", size=16, bold=True),
                self._text("Play your move on the board. Your opponent will answer.", color=t["fg_secondary"]),
            ]
        if len(session.parts) > 1:  # a level with several lines: which one is on the board
            part = session.current_part
            body.insert(2, self._label(f"Line {session.part_index + 1} of {len(session.parts)}"
                                       + (f" · {part['intro']}" if part.get("intro") else "")))
        feedback = self.feedback
        if feedback and feedback["kind"] in ("checking", "alternative"):
            body.extend(self._engine_feedback(feedback))
        elif feedback:
            question, result = feedback["question"], feedback["result"]
            when = review_days_text(result.get("review_days", []))  # empty after a correct answer
            if feedback["kind"] == "hint":
                tried = move_label({**question, "san": result["played_san"]})
                hint = result["hint"] or "move the highlighted piece."
                body.append(self._box("warning", f"Not quite: {tried} isn't the move here.", [f"Hint: {hint}"]))
                body.append(self._label(f"We'll review this position {when}."))
            elif feedback["kind"] == "shown":
                body.append(self._box("danger", f"The move here is {move_label(question)}.", ["Play it yourself to continue."]))
                body.append(self._label(f"We'll review this position {when}."))
            else:
                idea = result["strategic_idea"] if session.show_explanations else None
                lines = [idea] if idea else []
                if result.get("starts_retry"):
                    lines.append("Now let's go back to the positions you missed.")
                title = f"You fixed it! {move_label(question)}" if result.get("retry") else f"Well done! {move_label(question)}"
                body.append(self._box("success", title, lines))
        if session.answered_count:  # nothing to count before the first answer
            body.append(self._label(f"You got {session.first_try_count} of {session.answered_count} right on the first try."))
        return body

    def _done_panel(self) -> list:
        session, t = self.session, self.theme
        number = session.level_number
        next_level = self._levels[number] if number < len(self._levels) else None
        body = [self._text(f"You finished level {number}!", size=18, bold=True)]

        if session.kind == "quiz":
            passed = session.passed
            body.append(self._segments(session.question_states()))
            body.append(ft.Row(spacing=8, controls=[
                self._metric("First-try accuracy", f"{round(session.accuracy)}%", t["fg_primary"]),
                self._metric("Target", f"{round(session.pass_mark)}% {'✓' if passed else '✗'}",
                             t["success"] if passed else t["danger"]),
            ]))
            items = session.review_items()
            if items:
                body.append(self._label("We'll review these positions with you:"))
                for item in items:
                    label = move_label({**item, "turn": self.player_color})
                    if item["fixed"] is True:
                        label += " · fixed on your second chance"
                    elif item["fixed"] is False:
                        label += " · still tricky"
                    body.append(self._text(f"{label} · {review_days_text(item['review_days'])}",
                                           color=t["fg_secondary"]))
                if session.retry_mistakes:
                    fixed = sum(1 for item in items if item["fixed"])
                    body.append(self._text(f"You fixed {fixed} of {len(items)} on your second chance.",
                                           color=t["success"] if fixed == len(items) else t["warning"]))
            if not passed:
                if session.pass_mark < self.pass_mark:  # a short quiz: the mistake allowance decides
                    allowed = session.allowed_mistakes
                    rule = f"In this short test you can make at most {allowed} mistake{'s' if allowed != 1 else ''}."
                else:
                    rule = f"You need {self.pass_mark}% of the moves right on the first try to open the next level."
                body.append(self._box("warning", "Not passed yet", [rule]))
        else:
            body.append(self._text("You've seen every move of this level.", color=t["fg_secondary"]))
            body.extend(self._key_ideas())

        buttons = []
        if next_level and next_level["unlocked"]:
            buttons.append(self._button(f"Next level: {next_level['level']} {next_level['type']} →",
                                        lambda e, n=next_level["level"]: self.open_level(n), primary=True))
        buttons.append(self._button("↻ Repeat level", lambda e: self.open_level(number), primary=not buttons))
        if next_level is None:
            body.append(self._text("You've reached the last level of this chapter.", color=t["fg_secondary"]))
        body.append(ft.Row(wrap=True, spacing=8, controls=buttons))
        if self._engine_ready():
            body.append(self._engine_card())
        return body

    # -----------------------------------------------------------------
    # "Use engine" card (optional, after a level; DESIGN.md section 5)
    # -----------------------------------------------------------------
    def _engine_positions(self) -> list:
        """The player's moves in this level: the positions the engine looks at."""
        return [step for step in self.session.moves if step["turn"] == self.player_color]

    def _start_engine_analysis(self) -> None:
        self.engine_rows, self.engine_running = [], True
        self.render()
        token, positions = self._token, self._engine_positions()
        if hasattr(self.page, "run_task"):
            self.page.run_task(self._analyse_later, token, positions)
        else:
            for step in positions:
                self.engine_rows.append((step, self.assistant.opinion(step["fen_before"], step["uci"])))
            self.engine_running = False
            self.render()

    async def _analyse_later(self, token: int, positions: list) -> None:
        for step in positions:
            opinion = await asyncio.to_thread(self.assistant.opinion, step["fen_before"], step["uci"])
            if token != self._token:  # another level was opened
                return
            self.engine_rows.append((step, opinion))
            self.render()
        self.engine_running = False
        self.render()

    def _engine_card(self) -> ft.Container:
        t = self.theme
        controls = [
            self._text("Use engine (optional)", size=14, bold=True),
            self._text("Stockfish's opinion on this level's positions. The lesson's moves come from human "
                       "theory; the engine is a second opinion.", size=12, color=t["fg_secondary"]),
        ]
        if self.engine_rows is None:
            controls.append(self._button("Analyse with Stockfish", lambda e: self._start_engine_analysis()))
        else:
            for step, opinion in self.engine_rows:
                controls.extend(self._engine_row(step, opinion))
            if self.engine_running:
                total = len(self._engine_positions())
                controls.append(self._label(f"Analysing position {len(self.engine_rows) + 1} of {total}…"))
        return ft.Container(
            border=border_all(1, t["card_border"]),
            border_radius=8,
            padding=12,
            content=ft.Column(spacing=6, controls=controls),
        )

    def _engine_row(self, step: dict, opinion: dict | None) -> list:
        t = self.theme
        label = move_label(step)
        if opinion is None:
            return [self._text(f"{label}: the engine could not analyse this position.", size=12, color=t["fg_muted"])]
        if opinion["agrees"]:
            return [self._text(f"✓ {label}: the engine agrees ({pawns(opinion['book_cp'])}).",
                               size=12, color=t["fg_secondary"])]
        return [
            self._text(f"{label}: the engine prefers {opinion['best_san']} "
                       f"({pawns(opinion['best_cp'])} against {pawns(opinion['book_cp'])}).",
                       size=12, color=t["warning"], bold=True),
            self._text(f"Engine line: {opinion['line_san']}", size=12, color=t["fg_muted"]),
        ]


if __name__ == "__main__":
    # Try the screen on its own (dark theme, classic board, nothing saved):
    #   .venv\Scripts\python.exe level_view.py
    from chesscoach_flet import BOARD_THEMES, PIECE_COLORS, UI_THEMES

    def main(page: ft.Page):
        page.title = "ChessCoach - Training levels"
        page.padding = 0
        page.bgcolor = UI_THEMES["dark"]["bg_main"]
        chapter = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalan_ch01_v2.json")
        view = LevelTrainerView(page, chapter, UI_THEMES["dark"], {**BOARD_THEMES["classic"], **PIECE_COLORS})
        page.add(view.root)

    if hasattr(ft, "run"):
        ft.run(main, assets_dir=ASSETS_DIR)
    else:
        ft.app(target=main, assets_dir=ASSETS_DIR)
