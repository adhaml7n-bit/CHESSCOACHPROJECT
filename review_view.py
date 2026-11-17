"""
ChessCoach - Daily review screen (ReviewView)
=============================================
The homepage's "Daily Revised" card opens this screen. It drills the positions
that are due today, from every chapter, one after another (DESIGN.md section 3):
first the hint, then the correct move, which the player then plays. A first-try
answer moves the position to the next day of its plan, or masters it after the
last day; a mistake restarts its plan. On the last day (day 7) a first-try move
is followed by "Why do you play 9. e4?" with three answers: a right answer
masters the position, a wrong one brings it back in 3 days with the same
questions (ChessCoachDB.postpone_review). The board and the sizing are the
training screen's (board_view.py, level_view.ScreenBase).
"""

import asyncio
from datetime import datetime, timezone

import chess
import flet as ft

from board_view import click_square, render_board
from flet_compat import border_all, pad_symmetric
from level_trainer import ReviewSession, build_review_items
from level_view import ScreenBase, compute_layout, feedback_marks, move_label, review_days_text

PAUSE_SECONDS = 0.6  # the answer stays on the board this long before the next position
MAX_POSITIONS = 50   # positions per review session


def when_text(due_utc: str, today=None, tz=None) -> str:
    """'today', 'tomorrow' or 'in 5 days (Saturday 22 November)' for a due date
    stored as UTC text, in local time (tz None = the computer's time zone)."""
    due = datetime.strptime(due_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(tz)
    today = today or datetime.now(due.tzinfo).date()
    days = (due.date() - today).days
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days ({due:%A} {due.day} {due:%B})"


class ReviewView(ScreenBase):
    """The Daily review. Put `root` into the page.

    chapters - {chapter_id: chapter} of the chapters the app can open
               (opening_hub.chapters_by_id); positions of other chapters are skipped
    """

    def __init__(self, page, chapters: dict, theme: dict, board_colors: dict, db=None, on_back=None,
                 area=None, pause: float = PAUSE_SECONDS, assistant=None):
        self.page = page
        self.assistant = assistant  # engine_judge.EngineAssistant, or None (no second opinion)
        self.chapters = chapters
        self.theme = theme
        self.board_colors = board_colors
        self.db = db
        self.on_back = on_back
        self.area = area
        self.pause = pause
        self.layout = compute_layout(*self._area_size())
        self.root = ft.Container(expand=True, padding=20)
        self._token = 0
        self.start(update=False)

    # -----------------------------------------------------------------
    # Public
    # -----------------------------------------------------------------
    def start(self, update: bool = True) -> None:
        """(Re)loads the positions due now and starts with the first one."""
        rows = []
        if self.db is not None:
            try:
                rows = self.db.get_due_mistakes(limit=MAX_POSITIONS, chapter_ids=list(self.chapters))
            except Exception as exc:  # a locked database must not hide the screen
                print(f"[ChessCoach] Could not read the reviews: {exc}")
        self.session = ReviewSession(build_review_items(rows, self.chapters))
        self._token += 1      # a pending pause of the old session is dropped
        self.selected = None  # square of the selected piece
        # {"kind": "correct" | "hint" | "shown" | "purpose" | "purpose_done", "question": step, "result": ..., ...}
        self.feedback = None
        self.busy = False     # True while the answer stays on the board
        self.display = None   # (fen, uci) shown during that pause
        self.mastered = 0
        self.render(update)

    def render(self, update: bool = True) -> None:
        self.layout = compute_layout(*self._area_size())
        self.root.bgcolor = self.theme["bg_main"]
        header = [self._text("Daily review", size=18, bold=True)]
        if self.on_back:
            header.insert(0, self._button("← Home", lambda e: self.on_back()))
        controls = [ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=header)]
        if self.session.count == 0:
            controls.append(self._empty_card())
        else:
            controls.append(ft.Row(wrap=True, spacing=20, vertical_alignment=ft.CrossAxisAlignment.START,
                                   controls=[self._board(), self._panel()]))
        self.root.content = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=14, controls=controls)
        if update:
            self.page.update()

    # -----------------------------------------------------------------
    # Moves
    # -----------------------------------------------------------------
    def _on_square(self, square: int) -> None:
        if self.busy or self._holding() or self.session.is_complete:
            return
        uci, self.selected = click_square(chess.Board(self.session.fen), self.selected, square)
        if uci:
            self._submit(uci)
        else:
            self.render()

    def _answer(self, uci: str) -> None:
        """Counts a move (ScreenBase._submit asks the engine first about off-book moves)."""
        session = self.session
        item = session.current
        step = item["step"]
        result = session.submit_move(uci)

        if result["status"] == "incorrect":
            for line_id, ply in item["keys"]:  # a mistake restarts the position's plan
                self._save("record_mistake", item["chapter_id"], line_id, ply, result["fen"],
                           result["played_san"], result["review_days"])
            kind = "hint" if result["action"] == "show_hint" else "shown"
            self.feedback = {"kind": kind, "question": step, "result": result}
            self.render()
            return
        if result["status"] != "correct":
            self.render()
            return
        if result["ask_purpose"]:  # the last review: the purpose answer decides (_choose_purpose)
            self.feedback = {"kind": "purpose", "question": step, "item": item, "result": result}
            self.display = (step["fen_after"], step["uci"])
            self.render()
            return

        status = None
        if result["first_try"]:  # the review counts: next day of the plan, or mastered
            for line_id, ply in item["keys"]:
                self._save("record_correct", item["chapter_id"], line_id, ply)
            status = self._status(item)
            if status == "mastered":
                self.mastered += 1
        self.feedback = {"kind": "correct", "question": step, "result": result, "status": status}
        if self.pause > 0 and hasattr(self.page, "run_task"):
            # Show the answer and its "next review" first; then the next position (or the done card).
            self.busy = True
            self.display = (step["fen_after"], step["uci"])
            self.render()
            self.page.run_task(self._next_later, self._token)
        else:
            self.render()

    async def _next_later(self, token: int) -> None:
        await asyncio.sleep(self.pause)
        if token != self._token:  # the review was restarted in the meantime
            return
        self.busy = False
        self.display = None
        self.render()

    def _choose_purpose(self, choice: int) -> None:
        """The player picked answer `choice` of the purpose question."""
        feedback = self.feedback
        if not feedback or feedback["kind"] != "purpose":
            return
        answer = self.session.answer_purpose(choice)
        if answer["status"] not in ("right", "wrong"):
            return
        item = answer["item"]
        for key in item["keys"]:
            line_id, ply = key
            if answer["status"] == "wrong" and key in item["final_keys"]:
                self._save("postpone_review", item["chapter_id"], line_id, ply)  # back in 3 days
            else:
                self._save("record_correct", item["chapter_id"], line_id, ply)
        status = self._status(item)
        if status == "mastered":
            self.mastered += 1
        self.feedback = {**feedback, "kind": "purpose_done", "answer": answer, "status": status}
        self.render()

    def _continue(self) -> None:
        """'Next position' after the purpose answer has been read."""
        if self.feedback and self.feedback["kind"] == "purpose_done":
            self.feedback = None
            self.display = None
            self.render()

    def _holding(self) -> bool:
        """True while the purpose question or its answer is on screen (the board waits)."""
        return bool(self.feedback) and self.feedback["kind"] in ("purpose", "purpose_done")

    def _shown_item(self) -> dict:
        """The position on screen: the one just answered while its purpose result is shown."""
        if self._holding():
            return self.feedback["item"]
        return self.session.current or self.session.items[-1]  # the last one during the final pause

    def _status(self, item: dict) -> str | None:
        """'mastered', or when the position comes back ('in 6 days (...)'); None if unknown."""
        if self.db is None:
            return None
        try:
            line_id, ply = item["keys"][0]
            row = self.db.get_mistake(item["chapter_id"], line_id, ply)
        except Exception:
            return None
        if row is None:
            return None
        return "mastered" if row["mastered_at"] else when_text(row["next_due_at"])

    def _next_review(self) -> str | None:
        if self.db is None:
            return None
        try:
            return self.db.get_next_review_at(list(self.chapters))
        except Exception:
            return None

    # -----------------------------------------------------------------
    # Board and panel
    # -----------------------------------------------------------------
    def _board(self) -> ft.Container:
        session = self.session
        if self.display is not None:
            fen, last_uci = self.display
        else:
            fen = session.fen
            last_uci = session.last_move["uci"] if session.last_move else None
        item = self._shown_item()
        clickable = not session.is_complete and not self.busy and not self._holding()
        return render_board(
            chess.Board(fen),
            self.board_colors,
            self.layout["square"],
            piece_size=self.layout["piece"],
            coord_size=self._size(10),
            dot_size=self._size(16),
            white_bottom=item["player_color"] == "white",
            selected=self.selected,
            last_move_uci=last_uci,
            marked=feedback_marks(self.feedback, self.busy),
            on_square=self._on_square if clickable else None,
        )

    def _card(self, controls: list, width: int) -> ft.Container:
        t = self.theme
        return ft.Container(
            width=width,
            bgcolor=t["bg_panel"],
            border=border_all(1, t["card_border"]),
            border_radius=12,
            padding=16,
            content=ft.Column(spacing=10, controls=controls),
        )

    def _panel(self) -> ft.Container:
        # The last answer (and a purpose result) is shown before the done card.
        finished = self.session.is_complete and not self.busy and not self._holding()
        body = self._done_panel() if finished else self._question_panel()
        return self._card(body, self.layout["panel"])

    def _question_panel(self) -> list:
        session, t = self.session, self.theme
        item = self._shown_item()
        number = next(n for n, other in enumerate(session.items, start=1) if other is item)
        holding = self._holding()
        body = [
            self._label(f"Daily review · position {number} of {session.count}"),
            self._segments(session.question_states()),
            self._text(f"{item['chapter_title']} · move {item['step']['move_number']}", size=12, color=t["fg_muted"]),
            self._text("Why this move?" if holding else "Your move", size=16, bold=True),
            self._text("Last review of this position: show that you know its idea." if holding
                       else "You missed this position before. Find the move.", color=t["fg_secondary"]),
        ]
        feedback = self.feedback
        if holding:
            body.extend(self._purpose_panel(feedback))
        elif feedback and feedback["kind"] in ("checking", "alternative"):
            body.extend(self._engine_feedback(feedback))
        elif feedback:
            question, result = feedback["question"], feedback["result"]
            if feedback["kind"] == "hint":
                tried = move_label({**question, "san": result["played_san"]})
                hint = result["hint"] or "move the highlighted piece."
                body.append(self._box("warning", f"Not quite: {tried} isn't the move here.", [f"Hint: {hint}"]))
                body.append(self._label(f"We'll review this position {review_days_text(result['review_days'])}."))
            elif feedback["kind"] == "shown":
                body.append(self._box("danger", f"The move here is {move_label(question)}.",
                                      ["Play it yourself to continue."]))
                body.append(self._label(f"We'll review this position {review_days_text(result['review_days'])}."))
            else:
                status = feedback.get("status")
                lines = []
                if status == "mastered":
                    lines.append("Mastered! This position won't come back.")
                elif status:
                    lines.append(f"Next review: {status}.")
                body.append(self._box("success", f"Well done! {move_label(question)}", lines))
        return body

    def _purpose_panel(self, feedback: dict) -> list:
        """The day-7 question "Why do you play 9. e4?" and, once answered, its result."""
        step = feedback["question"]
        label = move_label(step)
        answer = feedback.get("answer")  # None while the question is open
        body = [
            self._box("success", f"Well done! {label}", ["One more question before this position is mastered."]),
            self._text(f"Why do you play {label}?", size=15, bold=True),
        ]
        choices = answer["choices"] if answer else self.session.purpose_choices
        body.extend(self._choice(number, text, answer) for number, text in enumerate(choices))
        if answer is None:
            return body

        lines = [step["explanation"]] if step.get("explanation") else []
        status = feedback.get("status")
        if answer["status"] == "right":
            if status == "mastered":
                lines.append("Mastered! This position won't come back.")
            elif status:
                lines.append(f"Next review: {status}.")
            body.append(self._box("success", "Right! That's the idea of the move.", lines))
        else:
            if status:
                lines.append(f"We'll ask you again {status}.")
            body.append(self._box("warning", f"Not quite: that isn't why you play {label}.", lines))
        body.append(self._button("See your results →" if answer["is_complete"] else "Next position →",
                                 lambda e: self._continue(), primary=True))
        return body

    def _choice(self, number: int, text: str, answer: dict | None) -> ft.Container:
        """One answer of the purpose question: clickable while open, then marked ✓ / ✗."""
        t = self.theme
        mark, color, border = "ABCDEFGH"[number], t["fg_primary"], t["card_border"]
        if answer is not None:
            if number == answer["answer_index"]:
                mark, color, border = "✓", t["success"], t["success"]
            elif number == answer["chosen"]:
                mark, color, border = "✗", t["danger"], t["danger"]
            else:
                color = t["fg_muted"]
        words = self._text(text, color=color)
        words.expand = True  # long answers wrap inside the panel
        return ft.Container(
            border=border_all(1, border),
            border_radius=8,
            padding=pad_symmetric(horizontal=self._size(12), vertical=self._size(8)),
            ink=answer is None,
            on_click=(lambda e, n=number: self._choose_purpose(n)) if answer is None else None,
            content=ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.START,
                           controls=[self._text(mark, color=color, bold=True), words]),
        )

    def _done_panel(self) -> list:
        session, t = self.session, self.theme
        metrics = [
            self._metric("First try", f"{session.first_try_count} of {session.count}", t["fg_primary"]),
            self._metric("Mastered today", str(self.mastered), t["success"]),
        ]
        if session.purpose_asked:
            metrics.append(self._metric("Why questions", f"{session.purpose_right_count} of {session.purpose_asked}",
                                        t["fg_primary"]))
        body = [
            self._text("You finished today's review!", size=18, bold=True),
            self._segments(session.question_states()),
            ft.Row(spacing=8, controls=metrics),
        ]
        next_due = self._next_review()
        if next_due:
            body.append(self._text(f"Your next review is {when_text(next_due)}.", color=t["fg_secondary"]))
        if self.on_back:
            body.append(self._button("← Back to home", lambda e: self.on_back(), primary=True))
        return body

    def _empty_card(self) -> ft.Container:
        t = self.theme
        if self.db is None or getattr(self.db, "is_guest", False):
            lines = ["As a Guest nothing is saved, so there is nothing to review.",
                     "Create a profile with the account button at the top to keep a review schedule."]
        else:
            next_due = self._next_review()
            lines = [f"Your next review is {when_text(next_due)}." if next_due
                     else "When you miss a move in a quiz, it comes back here on its review days."]
        controls = [self._text("Nothing to review right now", size=18, bold=True)]
        controls += [self._text(line, color=t["fg_secondary"]) for line in lines]
        if self.on_back:
            controls.append(self._button("← Back to home", lambda e: self.on_back(), primary=True))
        return self._card(controls, round(self.layout["panel"] * 1.4))
