"""
ChessCoach - level trainer (chapter format 2)
=============================================
Pure python-chess logic for chapters built from levels (DESIGN.md section 2):

    learn  the app shows a line move by move; the player presses Next / Back.
    quiz   the player plays their own moves from memory; the opponent's moves
           are played automatically. A wrong move triggers the level's
           "on_mistake" rule (first show the hint, then show the correct move).

No UI and no database in this file: the screen reads the result dicts and
saves progress through ChessCoachDB itself. Format-1 chapters such as
catalan_ch01.json still use opening_trainer.py.
"""

import json
import re
from pathlib import Path

import chess

FORMAT_VERSION = 2
LEVEL_TYPES = ("learn", "quiz")
QUESTION_TYPES = ("play_move",)
MISTAKE_ACTIONS = ("show_hint", "show_correct_move")
TEXT_FIELDS = ("strategic_idea", "explanation", "hint")

_UCI_PATTERN = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")


class ChapterFormatError(ValueError):
    """Raised when a format-2 chapter is broken: illegal move, wrong ply, bad level, ..."""


def level_line_id(level_number: int) -> str:
    """The line_progress id that stores a level's results, e.g. 'level_2'."""
    return f"level_{level_number}"


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _color_name(board: chess.Board) -> str:
    return "white" if board.turn == chess.WHITE else "black"


def _parse_move(board: chess.Board, text: str) -> chess.Move | None:
    """Reads a UCI ('g1f3') or SAN ('Nf3') move. A pawn reaching the last rank
    without a piece letter becomes a queen. Returns None when it is not legal."""
    text = (text or "").replace("﻿", "").strip()  # PowerShell pipes can add a BOM
    if _UCI_PATTERN.match(text.lower()):
        move = chess.Move.from_uci(text.lower())
        if move not in board.legal_moves and move.promotion is None:
            move = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
        return move if move in board.legal_moves else None
    try:
        return board.parse_san(text)
    except ValueError:
        return None


# =====================================================================
# 1. Loading & validation
# =====================================================================

def load_level_chapter(json_path: str | Path) -> dict:
    """Reads a format-2 chapter file and validates it (see validate_level_chapter)."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return validate_level_chapter(data)


def validate_level_chapter(data: dict) -> dict:
    """Checks a format-2 chapter and adds fen_before, uci and fen_after to every move.

    Every line starts from the initial position and every move is checked with
    python-chess, so a typo in the JSON stops the app at once with a clear
    message instead of teaching a wrong move. Returns the same dict.
    """
    if data.get("format_version") != FORMAT_VERSION:
        raise ChapterFormatError(
            f"format_version must be {FORMAT_VERSION}, got {data.get('format_version')!r}."
        )

    meta = data.get("chapter_meta")
    if not isinstance(meta, dict):
        raise ChapterFormatError("chapter_meta is missing.")
    for key in ("chapter_id", "chapter_title", "player_color"):
        if not meta.get(key):
            raise ChapterFormatError(f"chapter_meta.{key} is missing.")
    if meta["player_color"] not in ("white", "black"):
        raise ChapterFormatError(
            f"chapter_meta.player_color must be 'white' or 'black', got {meta['player_color']!r}."
        )
    pass_mark = meta.get("min_accuracy_to_pass", 0)
    if isinstance(pass_mark, bool) or not isinstance(pass_mark, (int, float)) or not 0 <= pass_mark <= 100:
        raise ChapterFormatError(
            f"chapter_meta.min_accuracy_to_pass must be between 0 and 100, got {pass_mark!r}."
        )

    lines = data.get("lines")
    if not isinstance(lines, dict) or not lines:
        raise ChapterFormatError("The chapter needs at least one line in 'lines'.")
    for line_id, moves in lines.items():
        _validate_line(line_id, moves)

    levels = data.get("levels")
    if not isinstance(levels, list) or not levels:
        raise ChapterFormatError("The chapter needs at least one level in 'levels'.")
    for number, level in enumerate(levels, start=1):
        _validate_level(level, number, lines, meta["player_color"])
    return data


def _validate_line(line_id: str, moves) -> None:
    if not isinstance(moves, list) or not moves:
        raise ChapterFormatError(f"Line '{line_id}' has no moves.")

    board = chess.Board()
    for ply, step in enumerate(moves, start=1):
        where = f"Line '{line_id}', ply {ply}"
        if not isinstance(step, dict):
            raise ChapterFormatError(f"{where}: a move must be an object.")
        if step.get("ply") != ply:
            raise ChapterFormatError(f"{where}: 'ply' is {step.get('ply')!r}, expected {ply}.")
        if step.get("turn") != _color_name(board):
            raise ChapterFormatError(
                f"{where}: 'turn' is {step.get('turn')!r}, expected {_color_name(board)!r}."
            )
        if step.get("move_number") != board.fullmove_number:
            raise ChapterFormatError(
                f"{where}: 'move_number' is {step.get('move_number')!r}, expected {board.fullmove_number}."
            )
        san = step.get("san")
        if not isinstance(san, str) or not san.strip():
            raise ChapterFormatError(f"{where}: 'san' is missing.")
        try:
            move = board.parse_san(san)
        except ValueError as exc:
            raise ChapterFormatError(f"{where}: {san!r} is not a legal move here.") from exc

        for key in TEXT_FIELDS:  # moves without explanations (e.g. level 3) are allowed
            step.setdefault(key, None)
        step["fen_before"] = board.fen()
        step["uci"] = move.uci()
        board.push(move)
        step["fen_after"] = board.fen()


def _validate_level(level, number: int, lines: dict, player_color: str) -> None:
    where = f"Level {number}"
    if not isinstance(level, dict):
        raise ChapterFormatError(f"{where}: a level must be an object.")
    if level.get("level") != number:
        raise ChapterFormatError(
            f"{where}: 'level' is {level.get('level')!r}, expected {number} (levels are numbered 1, 2, 3, ...)."
        )
    if level.get("type") not in LEVEL_TYPES:
        raise ChapterFormatError(f"{where}: 'type' must be one of {LEVEL_TYPES}, got {level.get('type')!r}.")
    if not level.get("title"):
        raise ChapterFormatError(f"{where}: 'title' is missing.")

    line = lines.get(level.get("line_id"))
    if line is None:
        raise ChapterFormatError(f"{where}: unknown line_id {level.get('line_id')!r}.")
    first, last = level.get("from_ply"), level.get("to_ply")
    if not (_is_int(first) and _is_int(last) and 1 <= first <= last <= len(line)):
        raise ChapterFormatError(
            f"{where}: need 1 <= from_ply <= to_ply <= {len(line)}, got from_ply={first!r}, to_ply={last!r}."
        )

    ideas = level.get("key_ideas", [])
    if not isinstance(ideas, list) or not all(isinstance(idea, str) and idea.strip() for idea in ideas):
        raise ChapterFormatError(f"{where}: 'key_ideas' must be a list of short texts.")

    if level["type"] == "quiz":
        _validate_quiz(level, where, line[first - 1:last], player_color)


def _validate_quiz(level: dict, where: str, moves: list, player_color: str) -> None:
    if level.get("question_type", "play_move") not in QUESTION_TYPES:
        raise ChapterFormatError(
            f"{where}: 'question_type' must be one of {QUESTION_TYPES}, got {level.get('question_type')!r}."
        )
    if not any(step["turn"] == player_color for step in moves):
        raise ChapterFormatError(f"{where}: the quiz range has no {player_color} move to ask about.")
    if not isinstance(level.get("retry_mistakes", False), bool):
        raise ChapterFormatError(f"{where}: 'retry_mistakes' must be true or false.")

    rules = level.get("on_mistake")
    if not isinstance(rules, list) or not rules:
        raise ChapterFormatError(f"{where}: a quiz level needs an 'on_mistake' list.")
    for attempt, rule in enumerate(rules, start=1):
        rule_where = f"{where}, on_mistake[{attempt - 1}]"
        if not isinstance(rule, dict) or rule.get("wrong_attempt") != attempt:
            raise ChapterFormatError(f"{rule_where}: 'wrong_attempt' must be {attempt}.")
        if rule.get("action") not in MISTAKE_ACTIONS:
            raise ChapterFormatError(
                f"{rule_where}: 'action' must be one of {MISTAKE_ACTIONS}, got {rule.get('action')!r}."
            )
        days = rule.get("review_days")
        if (
            not isinstance(days, list)
            or not days
            or not all(_is_int(day) and day > 0 for day in days)
            or any(a >= b for a, b in zip(days, days[1:]))
        ):
            raise ChapterFormatError(
                f"{rule_where}: 'review_days' must be increasing whole days above 0, e.g. [1, 7]."
            )


# =====================================================================
# 2. Level progress (which levels are open)
# =====================================================================

def summarize_levels(chapter: dict, line_rows: dict, extra_passed=frozenset()) -> list[dict]:
    """Status of every level of a chapter, for the level bar.

    line_rows    - ChessCoachDB.get_chapter_progress(chapter_id); each level is
                   saved under level_line_id(n).
    extra_passed - level numbers passed during this app session. A Guest saves
                   nothing, so this keeps a Guest moving forward until they leave.

    A learn level counts as passed once it is finished; a quiz level once its
    best accuracy reaches min_accuracy_to_pass. Level 1 is always open; any
    other level opens when the level before it is passed.
    """
    pass_mark = chapter["chapter_meta"].get("min_accuracy_to_pass", 0)
    summary = []
    previous_passed = True
    for level in chapter["levels"]:
        number = level["level"]
        row = line_rows.get(level_line_id(number))
        if number in extra_passed:
            passed = True
        elif row is None:
            passed = False
        elif level["type"] == "learn":
            passed = row["times_completed"] >= 1
        else:
            passed = row["best_accuracy"] is not None and row["best_accuracy"] >= pass_mark
        summary.append({
            "level": number,
            "type": level["type"],
            "title": level["title"],
            "unlocked": previous_passed,
            "passed": passed,
            "best_accuracy": row["best_accuracy"] if row else None,
        })
        previous_passed = passed
    return summary


# =====================================================================
# 3. LevelSession
# =====================================================================

class LevelSession:
    """Plays one level of a validated format-2 chapter.

    The board always shows `fen`. Learn levels move with next_step() /
    previous_step(); quiz levels move with submit_move(). restart() plays the
    level again from its first position.

    A quiz level with "retry_mistakes": true ends with a second-chance round:
    every position the player got wrong is asked once more (in_retry is True
    meanwhile). The level's accuracy still counts only the first pass.
    """

    def __init__(self, chapter: dict, level_number: int):
        levels = chapter["levels"]
        if not (_is_int(level_number) and 1 <= level_number <= len(levels)):
            raise ValueError(f"Level {level_number!r} does not exist (the chapter has {len(levels)}).")

        meta = chapter["chapter_meta"]
        self.chapter = chapter
        self.level = levels[level_number - 1]
        self.level_number = level_number
        self.kind = self.level["type"]
        self.player_color = meta["player_color"]
        self.pass_mark = meta.get("min_accuracy_to_pass", 0)
        self.show_explanations = self.level.get("show_explanations", self.kind == "learn")
        self.retry_mistakes = self.kind == "quiz" and self.level.get("retry_mistakes", False)

        line = chapter["lines"][self.level["line_id"]]
        self.moves = line[self.level["from_ply"] - 1:self.level["to_ply"]]
        self.questions = [step for step in self.moves if step["turn"] == self.player_color]
        self.start_fen = self.moves[0]["fen_before"]
        self.restart()

    def restart(self) -> list[dict]:
        """Starts the level again from its first position.

        Returns the opponent moves played automatically before the first
        question (quiz levels that start with an opponent move), else [].
        """
        self.cursor = 0                   # self.moves[:cursor] are on the board
        self._wrong: dict[int, int] = {}  # ply -> wrong attempts in this run (quiz)
        self.first_try_count = 0
        self.answered_count = 0
        self.retry_queue: list[dict] = []     # positions asked again after the first pass
        self.retry_index = 0
        self._retry_wrong: dict[int, int] = {}
        self.retry_results: dict[int, bool] = {}  # ply -> solved on the first try of the second chance
        return self._play_opponent_moves() if self.kind == "quiz" else []

    # -----------------------------------------------------------------
    # Board state (both level types)
    # -----------------------------------------------------------------
    @property
    def _main_done(self) -> bool:
        return self.cursor >= len(self.moves)

    @property
    def in_retry(self) -> bool:
        """True during the second-chance round of a quiz."""
        return self._main_done and self.retry_index < len(self.retry_queue)

    @property
    def fen(self) -> str:
        if self.in_retry:
            return self.current_question["fen_before"]
        return self.moves[self.cursor - 1]["fen_after"] if self.cursor else self.start_fen

    @property
    def last_move(self) -> dict | None:
        """The last move on the board (for highlighting); None at the start."""
        if self.in_retry:
            index = self.moves.index(self.current_question)
            return self.moves[index - 1] if index else None
        return self.moves[self.cursor - 1] if self.cursor else None

    @property
    def is_complete(self) -> bool:
        return self._main_done and not self.in_retry

    @property
    def passed(self) -> bool:
        """True once the level is finished well enough to open the next one."""
        if not self.is_complete:
            return False
        return self.kind == "learn" or self.accuracy >= self.pass_mark

    # -----------------------------------------------------------------
    # Learn levels
    # -----------------------------------------------------------------
    @property
    def current_step(self) -> dict | None:
        """The move being explained (the last move played); None before the first one."""
        return self.last_move

    @property
    def step_index(self) -> int:
        return self.cursor

    @property
    def step_count(self) -> int:
        return len(self.moves)

    def next_step(self) -> dict | None:
        """Plays the next move of the line. Returns it, or None when the line is finished."""
        self._require("learn")
        if self.is_complete:
            return None
        self.cursor += 1
        return self.last_move

    def previous_step(self) -> dict | None:
        """Takes the last move back. Returns the move now being explained (None at the start)."""
        self._require("learn")
        self.cursor = max(0, self.cursor - 1)
        return self.last_move

    # -----------------------------------------------------------------
    # Quiz levels
    # -----------------------------------------------------------------
    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def current_question(self) -> dict | None:
        """The move the player must find now; None when the quiz is finished."""
        if self.in_retry:
            return self.retry_queue[self.retry_index]
        return None if self._main_done else self.moves[self.cursor]

    @property
    def accuracy(self) -> float:
        """Answered questions solved on the first try, in % (100.0 before the first answer)."""
        if not self.answered_count:
            return 100.0
        return round(100 * self.first_try_count / self.answered_count, 1)

    def submit_move(self, move_text: str) -> dict:
        """Checks the player's move (UCI like 'g1f3' or SAN like 'Nf3').

        The result's 'status' is one of:
          correct    the move was right; the opponent's reply (if any) is played too
          incorrect  wrong move; 'action' tells the screen what to show
                     ('show_hint' or 'show_correct_move') and 'review_days'
                     when the position comes back for review
          illegal    not a legal move here; it does not count as a mistake
          complete   the quiz is already finished
        """
        self._require("quiz")
        expected = self.current_question
        if expected is None:
            return {"status": "complete", "fen": self.fen}

        board = chess.Board(expected["fen_before"])
        move = _parse_move(board, move_text)
        if move is None:
            return {
                "status": "illegal",
                "fen": expected["fen_before"],
                "message": f"{move_text!r} is not a legal move in this position.",
            }

        ply = expected["ply"]
        retrying = self.in_retry
        if move.uci() != expected["uci"]:
            counter = self._retry_wrong if retrying else self._wrong
            wrong = counter.get(ply, 0) + 1
            counter[ply] = wrong
            rule = self._rule_for(wrong)
            reveal = rule["action"] == "show_correct_move"
            return {
                "status": "incorrect",
                "retry": retrying,
                "ply": ply,
                "fen": expected["fen_before"],
                "played_san": board.san(move),
                "played_uci": move.uci(),
                "wrong_attempt": wrong,
                "action": rule["action"],
                "hint": expected["hint"] if rule["action"] == "show_hint" else None,
                "correct_san": expected["san"] if reveal else None,
                "correct_uci": expected["uci"] if reveal else None,
                "review_days": list(rule["review_days"]),
            }

        if retrying:
            wrong = self._retry_wrong.get(ply, 0)
            self.retry_results[ply] = wrong == 0
            self.retry_index += 1
            opponent_moves = []
        else:
            wrong = self._wrong.get(ply, 0)
            self.answered_count += 1
            if wrong == 0:
                self.first_try_count += 1
            self.cursor += 1
            opponent_moves = self._play_opponent_moves()
            if self._main_done and self.retry_mistakes:
                self.retry_queue = [step for step in self.questions if self._wrong.get(step["ply"])]
        return {
            "status": "correct",
            "retry": retrying,
            "starts_retry": not retrying and self.in_retry,
            "ply": ply,
            "san": expected["san"],
            "uci": expected["uci"],
            "first_try": wrong == 0,
            "wrong_attempts": wrong,
            "strategic_idea": expected["strategic_idea"],
            "explanation": expected["explanation"],
            "opponent_moves": opponent_moves,
            "fen": self.fen,
            "is_complete": self.is_complete,
            "accuracy": self.accuracy,
        }

    def question_states(self) -> list[str]:
        """One entry per question, for the progress bar: 'ok' (first try),
        'hint' (solved after the hint), 'shown' (the correct move was shown),
        'current' (being asked now) or 'pending'."""
        current_ply = None if self._main_done else self.moves[self.cursor]["ply"]
        states = []
        for step in self.questions:
            ply = step["ply"]
            answered = current_ply is None or ply < current_ply
            if answered:
                wrong = self._wrong.get(ply, 0)
                states.append("ok" if wrong == 0 else self._mistake_state(wrong))
            elif ply == current_ply:
                states.append("current")
            else:
                states.append("pending")
        return states

    def review_items(self) -> list[dict]:
        """Positions the player got wrong in this run, with their review days
        (taken from the on_mistake rule of the last wrong attempt)."""
        items = []
        for step in self.questions:
            wrong = self._wrong.get(step["ply"], 0)
            if wrong:
                items.append({
                    "ply": step["ply"],
                    "move_number": step["move_number"],
                    "san": step["san"],
                    "fen": step["fen_before"],
                    "wrong_attempts": wrong,
                    "review_days": list(self._rule_for(wrong)["review_days"]),
                    # second chance: True = solved at once, False = not, None = no second chance (yet)
                    "fixed": self.retry_results.get(step["ply"]),
                })
        return items

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    def _rule_for(self, wrong_attempt: int) -> dict:
        """The on_mistake rule for this attempt; later attempts repeat the last rule."""
        rules = self.level["on_mistake"]
        return rules[min(wrong_attempt, len(rules)) - 1]

    def _mistake_state(self, wrong: int) -> str:
        shown = any(self._rule_for(n)["action"] == "show_correct_move" for n in range(1, wrong + 1))
        return "shown" if shown else "hint"

    def _play_opponent_moves(self) -> list[dict]:
        played = []
        while not self._main_done and self.moves[self.cursor]["turn"] != self.player_color:
            played.append(self.moves[self.cursor])
            self.cursor += 1
        return played

    def _require(self, kind: str) -> None:
        if self.kind != kind:
            raise RuntimeError(f"Level {self.level_number} is a {self.kind} level, not a {kind} level.")


if __name__ == "__main__":
    # Quick terminal check before the Flet screen exists, for example:
    #   .venv\Scripts\python.exe level_trainer.py catalan_ch01_v2.json 2
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "catalan_ch01_v2.json"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    chapter = load_level_chapter(path)
    session = LevelSession(chapter, number)
    print(f"{chapter['chapter_meta']['chapter_title']} - level {number} ({session.kind}): {session.level['title']}")

    if session.kind == "learn":
        while session.next_step() is not None:
            step = session.current_step
            dots = "." if step["turn"] == "white" else "..."
            print(f"{step['move_number']}{dots}{step['san']}  {step['strategic_idea'] or ''}")
    else:
        while not session.is_complete:
            question = session.current_question
            try:
                typed = input(f"Move {question['move_number']} ({session.player_color}): ")
            except EOFError:
                print("\nStopped before the end of the quiz.")
                break
            result = session.submit_move(typed)
            if result["status"] == "correct":
                note = "" if result["first_try"] else " (not first try)"
                replies = "".join(f"  | {m['san']}" for m in result["opponent_moves"])
                print(f"  correct{note}{replies}")
            elif result["status"] == "incorrect":
                if result["action"] == "show_hint":
                    print(f"  wrong. Hint: {result['hint'] or '(no hint)'}")
                else:
                    print(f"  wrong. The move is {result['correct_san']}; play it to continue.")
            else:
                print(f"  {result['message']}")
        print(f"Accuracy {session.accuracy}% - {'passed' if session.passed else 'not passed yet'}")
        for item in session.review_items():
            print(f"  review {item['move_number']}.{item['san']}: days {item['review_days']}")
