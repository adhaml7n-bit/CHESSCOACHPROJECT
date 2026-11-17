"""
ChessCoach - training screen for format-2 chapters (learn and quiz levels)
=========================================================================
Flet view of level_trainer.LevelSession, built from the design approved on
2026-11-17 (DESIGN.md section 8): the level bar on top, the board on the left
and the panel on the right.

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

from flet_compat import align_center, border_all, pad_only, pad_symmetric
from level_trainer import LevelSession, level_line_id, load_level_chapter, summarize_levels

PIECE_SYMBOLS = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}
SQUARE = 56
PIECE_SIZE = 34
PANEL_WIDTH = 360
OPPONENT_DELAY_SECONDS = 0.6  # pause before the opponent's reply in a quiz
LEVEL_ICONS = {"learn": "📖", "quiz": "✎"}


def move_label(step: dict) -> str:
    """'7. Qc2' for a White move, '7... Nbd7' for a Black move."""
    dots = "." if step["turn"] == "white" else "..."
    return f"{step['move_number']}{dots} {step['san']}"


def review_days_text(days: list[int]) -> str:
    """[1, 7] -> 'tomorrow and in 7 days'; [1, 3, 7] -> 'tomorrow, in 3 days and in 7 days'."""
    parts = ["tomorrow" if day == 1 else f"in {day} days" for day in days]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


class LevelTrainerView:
    """The training screen of one format-2 chapter. Put `root` into the page.

    theme        - UI_THEMES[ui_mode] of the app
    board_colors - a BOARD_THEMES preset with the user's light_sq / dark_sq and
                   the piece colours (piece_white, piece_black, piece_shadow)
    db           - the app's ChessCoachDB, or None to save nothing
    """

    def __init__(self, page, chapter_path, theme: dict, board_colors: dict, db=None, on_back=None,
                 opponent_delay: float = OPPONENT_DELAY_SECONDS):
        self.page = page
        self.theme = theme
        self.board_colors = board_colors
        self.db = db
        self.on_back = on_back
        self.opponent_delay = opponent_delay

        self.chapter = load_level_chapter(chapter_path)
        meta = self.chapter["chapter_meta"]
        self.chapter_id = meta["chapter_id"]
        self.player_color = meta["player_color"]
        self.pass_mark = meta.get("min_accuracy_to_pass", 0)
        self._passed_now: dict = {}  # user id (None = Guest) -> levels passed while the app is open

        self.root = ft.Container(expand=True, padding=20)
        self.session: LevelSession | None = None
        self._levels: list[dict] = []
        self._token = 0
        self.open_level(self._starting_level(), update=False)

    # -----------------------------------------------------------------
    # Public
    # -----------------------------------------------------------------
    def open_level(self, number: int, update: bool = True) -> None:
        """Starts (or restarts) a level from its first position."""
        self.session = LevelSession(self.chapter, number)
        self._token += 1          # a pending opponent reply of the old level is dropped
        self.selected = None      # square of the selected piece
        self.feedback = None      # {"kind": "correct" | "hint" | "shown", "question": ..., "result": ...}
        self.busy = False         # True while the opponent's reply waits
        self.display = None       # (fen, uci) shown during that wait
        self.show_done = False
        self.result_saved = False
        self.render(update)

    def set_theme(self, theme: dict, board_colors: dict, update: bool = True) -> None:
        """Called by the app after a theme, board colour or account change."""
        self.theme = theme
        self.board_colors = board_colors
        self.render(update)

    def render(self, update: bool = True) -> None:
        self._levels = self._load_levels()
        self.root.bgcolor = self.theme["bg_main"]
        self.root.content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=14,
            controls=[
                self._header(),
                self._level_bar(),
                ft.Row(
                    wrap=True,
                    spacing=20,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[self._board(), self._panel()],
                ),
            ],
        )
        if update:
            self.page.update()

    # -----------------------------------------------------------------
    # Progress
    # -----------------------------------------------------------------
    def _user_key(self):
        return getattr(self.db, "current_user_id", None)

    def _save(self, method_name: str, *args) -> None:
        """Calls a ChessCoachDB method; a database problem never stops the lesson."""
        if self.db is None:
            return
        try:
            getattr(self.db, method_name)(*args)
        except Exception as exc:  # e.g. the file is locked for longer than the timeout
            print(f"[ChessCoach] Could not save progress ({method_name}): {exc}")

    def _load_levels(self) -> list[dict]:
        rows = {}
        if self.db is not None:
            try:
                rows = self.db.get_chapter_progress(self.chapter_id)
            except Exception as exc:
                print(f"[ChessCoach] Could not read progress: {exc}")
        return summarize_levels(self.chapter, rows, self._passed_now.get(self._user_key(), set()))

    def _starting_level(self) -> int:
        """The first open level not passed yet; the last level when all are passed."""
        levels = self._load_levels()
        for level in levels:
            if level["unlocked"] and not level["passed"]:
                return level["level"]
        return levels[-1]["level"]

    def _complete_level(self) -> None:
        if self.result_saved:
            return
        self.result_saved = True
        session = self.session
        accuracy = session.accuracy if session.kind == "quiz" else None
        self._save("save_line_result", self.chapter_id, level_line_id(session.level_number), accuracy)
        if session.passed:
            self._passed_now.setdefault(self._user_key(), set()).add(session.level_number)
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
        board = chess.Board(session.fen)
        if self.selected is not None and square != self.selected:
            moves = [m for m in board.legal_moves if m.from_square == self.selected and m.to_square == square]
            if moves:
                move = next((m for m in moves if m.promotion in (None, chess.QUEEN)), moves[0])
                self.selected = None
                self._submit(move.uci())
                return
        piece = board.piece_at(square)
        if piece and piece.color == board.turn and square != self.selected:
            self.selected = square
        else:
            self.selected = None
        self.render()

    def _submit(self, uci: str) -> None:
        session = self.session
        question = session.current_question
        line_id = session.level["line_id"]
        result = session.submit_move(uci)

        if result["status"] == "incorrect":
            # fen = position before the move, played_san = the wrong move.
            self._save("record_mistake", self.chapter_id, line_id, result["ply"], result["fen"], result["played_san"])
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
    # Building blocks
    # -----------------------------------------------------------------
    def _text(self, value: str, size: int = 13, color: str | None = None, bold: bool = False) -> ft.Text:
        return ft.Text(
            value,
            size=size,
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
            padding=pad_symmetric(horizontal=14, vertical=8),
            on_click=on_click,
            ink=True,
            content=ft.Text(
                label,
                size=13,
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
        """Quiz progress: one bar per question, coloured by its result."""
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

    # -----------------------------------------------------------------
    # Header and level bar
    # -----------------------------------------------------------------
    def _header(self) -> ft.Row:
        meta = self.chapter["chapter_meta"]
        controls = []
        if self.on_back:
            controls.append(self._button(f"← {meta.get('opening_name') or 'Back'}", lambda e: self.on_back()))
        controls.append(self._text(meta["chapter_title"], size=18, bold=True))
        return ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=controls)

    def _level_bar(self) -> ft.Row:
        t = self.theme
        pills = []
        for level in self._levels:
            number = level["level"]
            current = number == self.session.level_number
            if level["passed"]:
                icon, icon_color = "✓", t["success"]
            elif not level["unlocked"]:
                icon, icon_color = "🔒", t["fg_muted"]
            else:
                icon, icon_color = LEVEL_ICONS[level["type"]], t["fg_secondary"]
            if current:
                color = t["accent"]
            else:
                color = t["fg_secondary"] if level["unlocked"] else t["fg_muted"]
            clickable = level["unlocked"] and not current
            pills.append(
                ft.Container(
                    bgcolor=t["bg_panel"],
                    border=border_all(2 if current else 1, t["accent"] if current else t["card_border"]),
                    border_radius=8,
                    padding=pad_symmetric(horizontal=10, vertical=5),
                    tooltip=level["title"],
                    ink=clickable,
                    on_click=(lambda e, n=number: self.open_level(n)) if clickable else None,
                    content=ft.Row(
                        tight=True,
                        spacing=6,
                        controls=[
                            ft.Text(icon, size=12, color=icon_color),
                            ft.Text(f"{number} {level['type'].capitalize()}", size=12,
                                    weight=ft.FontWeight.W_600, color=color),
                        ],
                    ),
                )
            )
        return ft.Row(wrap=True, spacing=8, controls=pills)

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
        board = chess.Board(fen)

        last_squares = set()
        if last_uci:
            move = chess.Move.from_uci(last_uci)
            last_squares = {move.from_square, move.to_square}

        marked = {}  # square -> border width of the hint highlight
        feedback = self.feedback
        if feedback and not self.busy:
            if feedback["kind"] == "shown":
                move = chess.Move.from_uci(feedback["result"]["correct_uci"])
                marked = {move.from_square: 3, move.to_square: 4}
            elif feedback["kind"] == "hint" and not feedback["result"]["hint"]:
                marked = {chess.parse_square(feedback["question"]["uci"][:2]): 4}  # automatic hint

        targets = {}  # square -> True for a capture
        if self.selected is not None:
            for move in board.legal_moves:
                if move.from_square == self.selected:
                    targets[move.to_square] = board.is_capture(move)

        white_bottom = self.player_color == "white"
        clickable = session.kind == "quiz" and not self.show_done
        rows = []
        for row in range(8):
            rank = 7 - row if white_bottom else row
            cells = []
            for col in range(8):
                file = col if white_bottom else 7 - col
                square = chess.square(file, rank)
                cells.append(self._square(board, square, row, col, last_squares, marked, targets, clickable))
            rows.append(ft.Row(spacing=0, tight=True, controls=cells))
        return ft.Container(
            border_radius=4,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(spacing=0, tight=True, controls=rows),
        )

    def _square(self, board, square, row, col, last_squares, marked, targets, clickable) -> ft.Container:
        c = self.board_colors
        file, rank = chess.square_file(square), chess.square_rank(square)
        is_light = (file + rank) % 2 == 1
        fill = c["light_sq"] if is_light else c["dark_sq"]
        if square == self.selected:
            fill = c["selected"]
        elif square in last_squares:
            fill = c["last_move"]
        coord_color = c["dark_sq"] if is_light else c["light_sq"]

        items = []
        if col == 0:
            items.append(ft.Container(left=3, top=1, content=ft.Text(
                str(rank + 1), size=10, weight=ft.FontWeight.BOLD, color=coord_color)))
        if row == 7:
            items.append(ft.Container(right=3, bottom=1, content=ft.Text(
                chess.FILE_NAMES[file], size=10, weight=ft.FontWeight.BOLD, color=coord_color)))
        if square in marked:
            items.append(ft.Container(width=SQUARE, height=SQUARE, border_radius=4,
                                      border=border_all(marked[square], c["hint_sq"])))

        piece = board.piece_at(square)
        if piece:
            symbol = PIECE_SYMBOLS[piece.symbol()]
            color = c["piece_white"] if piece.color == chess.WHITE else c["piece_black"]
            items.append(ft.Container(width=SQUARE, height=SQUARE, alignment=align_center(),
                                      padding=pad_only(left=2, top=3),
                                      content=ft.Text(symbol, size=PIECE_SIZE, color=c["piece_shadow"])))
            items.append(ft.Container(width=SQUARE, height=SQUARE, alignment=align_center(),
                                      content=ft.Text(symbol, size=PIECE_SIZE, color=color)))

        if square in targets:
            if targets[square]:  # ring for a capture
                ring = SQUARE - 8
                marker = ft.Container(width=ring, height=ring, border_radius=ring // 2,
                                      border=border_all(4, c["legal_capture"]))
            else:                # dot for an empty square
                marker = ft.Container(width=16, height=16, border_radius=8, bgcolor=c["legal_dot"])
            items.append(ft.Container(width=SQUARE, height=SQUARE, alignment=align_center(), content=marker))

        return ft.Container(
            width=SQUARE,
            height=SQUARE,
            bgcolor=fill,
            on_click=(lambda e, s=square: self._on_square(s)) if clickable else None,
            content=ft.Stack(width=SQUARE, height=SQUARE, controls=items),
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
            width=PANEL_WIDTH,
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
        if step is None:
            body.append(self._text(session.level["title"], size=18, bold=True))
            intro = session.level.get("intro")
            if not intro and session.level_number == 1:
                intro = self.chapter["chapter_meta"].get("description")
            if intro:
                body.append(self._text(intro, color=t["fg_secondary"]))
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
        body.append(ft.Row(spacing=8, controls=[
            self._button("← Back", lambda e: self._learn_back()),
            self._button("Finish level ✓" if session.is_complete else "Next →", lambda e: self._learn_next(),
                         primary=True),
        ]))
        return body

    def _move_list(self, upto_ply: int) -> ft.Row:
        """The line up to the current move: earlier levels muted, the current move highlighted."""
        session, t = self.session, self.theme
        line = self.chapter["lines"][session.level["line_id"]]
        first = session.level["from_ply"]
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
        feedback = self.feedback
        if feedback:
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
                self._metric("Target", f"{self.pass_mark}% {'✓' if passed else '✗'}",
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
                body.append(self._box("warning", "Not passed yet", [
                    f"You need {self.pass_mark}% of the moves right on the first try to open the next level."
                ]))
        else:
            body.append(self._text("You've seen every move of this level.", color=t["fg_secondary"]))

        buttons = []
        if next_level and next_level["unlocked"]:
            buttons.append(self._button(f"Next level: {next_level['level']} {next_level['type']} →",
                                        lambda e, n=next_level["level"]: self.open_level(n), primary=True))
        buttons.append(self._button("↻ Repeat level", lambda e: self.open_level(number), primary=not buttons))
        if next_level is None:
            body.append(self._text("You've reached the last level of this chapter.", color=t["fg_secondary"]))
        body.append(ft.Row(wrap=True, spacing=8, controls=buttons))
        return body


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
        ft.run(main)
    else:
        ft.app(target=main)
