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
import random
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


# Default mistake rules (DESIGN.md section 3): first the hint, then the correct
# move; the review days are the position's plan after one or two mistakes.
DEFAULT_MISTAKE_RULES = (
    {"wrong_attempt": 1, "action": "show_hint", "review_days": [1, 7]},
    {"wrong_attempt": 2, "action": "show_correct_move", "review_days": [1, 3, 7]},
)


def classify_move(fen: str, book_uci: str, move_text: str) -> dict:
    """What a move would be, without counting anything: 'correct', 'illegal' or
    'off_book' (legal but not the lesson's move). The screen can ask the engine
    about an off-book move before it counts as a mistake."""
    board = chess.Board(fen)
    move = _parse_move(board, move_text)
    if move is None:
        return {"status": "illegal"}
    if move.uci() == book_uci:
        return {"status": "correct", "uci": move.uci()}
    dots = "." if board.turn == chess.WHITE else "..."
    return {
        "status": "off_book",
        "uci": move.uci(),
        "label": f"{board.fullmove_number}{dots} {board.san(move)}",
        "fen": fen,
        "book_uci": book_uci,
    }


def rule_for(rules, wrong_attempt: int) -> dict:
    """The mistake rule for this wrong attempt; later attempts repeat the last rule."""
    return rules[min(wrong_attempt, len(rules)) - 1]


def mistake_state(rules, wrong: int) -> str:
    """'shown' if the correct move was shown within `wrong` attempts, else 'hint'."""
    shown = any(rule_for(rules, n)["action"] == "show_correct_move" for n in range(1, wrong + 1))
    return "shown" if shown else "hint"


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
    allowed = meta.get("allowed_mistakes", 0)
    if not _is_int(allowed) or allowed < 0:
        raise ChapterFormatError(
            f"chapter_meta.allowed_mistakes must be a whole number of 0 or more, got {allowed!r}."
        )

    lines = data.get("lines")
    if not isinstance(lines, dict) or not lines:
        raise ChapterFormatError("The chapter needs at least one line in 'lines'.")
    _expand_branch_lines(lines)
    for line_id, moves in lines.items():
        _validate_line(line_id, moves)
    _share_texts(lines, meta["player_color"])
    _check_one_move_per_position(lines, meta["player_color"])

    levels = data.get("levels")
    if not isinstance(levels, list) or not levels:
        raise ChapterFormatError("The chapter needs at least one level in 'levels'.")
    for number, level in enumerate(levels, start=1):
        _validate_level(level, number, lines, meta["player_color"])
    return data


def _position_key(fen: str) -> str:
    """A position without its move counters: the same position reached by
    another move order (a transposition) gets the same key."""
    return " ".join(fen.split()[:4])


def _expand_branch_lines(lines: dict) -> None:
    """A line can be written as a branch of another line, so long shared
    starts are not copied by hand:

        "line_id": {"from_line": "main", "after_ply": 17, "moves": [{"ply": 18, ...}, ...]}

    It becomes a full line from move 1: the parent's first after_ply moves
    (copied, with their texts) followed by its own moves. A parent can be a
    branch too."""
    full: dict[str, list] = {}

    def resolve(line_id: str, chain: tuple) -> list:
        if line_id in full:
            return full[line_id]
        spec = lines[line_id]
        if isinstance(spec, list):
            full[line_id] = spec
            return spec
        if not isinstance(spec, dict):
            raise ChapterFormatError(f"Line '{line_id}' must be a list of moves or a branch object.")
        if line_id in chain:
            raise ChapterFormatError(f"Line '{line_id}' branches from itself ({' -> '.join(chain + (line_id,))}).")
        parent_id, after, moves = spec.get("from_line"), spec.get("after_ply"), spec.get("moves")
        if parent_id not in lines:
            raise ChapterFormatError(f"Line '{line_id}' branches from unknown line {parent_id!r}.")
        parent = resolve(parent_id, chain + (line_id,))
        if not (_is_int(after) and 1 <= after <= len(parent)):
            raise ChapterFormatError(
                f"Line '{line_id}': 'after_ply' must be between 1 and {len(parent)} (the length of '{parent_id}'), got {after!r}."
            )
        if not isinstance(moves, list) or not moves:
            raise ChapterFormatError(f"Line '{line_id}' has no moves of its own.")
        full[line_id] = [dict(step) for step in parent[:after]] + moves
        return full[line_id]

    for line_id in list(lines):
        lines[line_id] = resolve(line_id, ())


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
        if step.setdefault("purpose", None) is not None:
            _check_purpose(step["purpose"], where)
        step["fen_before"] = board.fen()
        step["uci"] = move.uci()
        board.push(move)
        step["fen_after"] = board.fen()


def _check_purpose(purpose, where: str) -> None:
    """The day-7 question of a move (DESIGN.md section 3):
    {"answer": "the move's idea", "wrong": ["a wrong idea", ...]}."""
    answer = purpose.get("answer") if isinstance(purpose, dict) else None
    wrong = purpose.get("wrong") if isinstance(purpose, dict) else None
    if (not isinstance(answer, str) or not answer.strip() or not isinstance(wrong, list) or not wrong
            or not all(isinstance(text, str) and text.strip() for text in wrong)):
        raise ChapterFormatError(f"{where}: 'purpose' needs an 'answer' text and a 'wrong' list of texts.")
    texts = [answer, *wrong]
    if len({text.strip().lower() for text in texts}) != len(texts):
        raise ChapterFormatError(f"{where}: the purpose answers must all be different.")


SHARED_FIELDS = TEXT_FIELDS + ("purpose",)


def _share_texts(lines: dict, player_color: str) -> None:
    """Texts belong to a position and its move. Lines that share their first
    moves, or reach the same position by another move order, write them once:
    every copy of that position and move gets the texts it leaves empty. A
    purpose question is only for the player's moves."""
    by_move: dict[tuple, dict] = {}
    for line_id, moves in lines.items():
        for step in moves:
            if step["purpose"] is not None and step["turn"] != player_color:
                raise ChapterFormatError(
                    f"Line '{line_id}', ply {step['ply']}: a 'purpose' question is only for {player_color}'s moves."
                )
            found = by_move.setdefault((_position_key(step["fen_before"]), step["uci"]), {})
            for field in SHARED_FIELDS:
                if step[field] is not None:
                    found.setdefault(field, step[field])
    for moves in lines.values():
        for step in moves:
            found = by_move[(_position_key(step["fen_before"]), step["uci"])]
            for field in SHARED_FIELDS:
                if step[field] is None and field in found:
                    step[field] = found[field]


def _check_one_move_per_position(lines: dict, player_color: str) -> None:
    """Wherever the player moves, every line must play the same move: a quiz
    accepts one move per position, and the Daily review asks a position once."""
    seen: dict[str, tuple] = {}
    for line_id, moves in lines.items():
        for step in moves:
            if step["turn"] != player_color:
                continue
            key = _position_key(step["fen_before"])
            uci, other_line, other_ply, other_san = seen.setdefault(key, (step["uci"], line_id, step["ply"], step["san"]))
            if uci != step["uci"]:
                raise ChapterFormatError(
                    f"Line '{line_id}', ply {step['ply']} plays {step['san']} where line '{other_line}', "
                    f"ply {other_ply} plays {other_san} in the same position: a position needs one move for you."
                )


def level_parts(level: dict) -> list[dict]:
    """The line ranges a level covers, in order. A level names one range with
    line_id / from_ply / to_ply, or several with "parts" (each with its own
    line_id, from_ply, to_ply and an optional intro and key_ideas)."""
    if "parts" in level:
        return level["parts"]
    return [{"line_id": level["line_id"], "from_ply": level["from_ply"], "to_ply": level["to_ply"]}]


def _check_ideas(ideas, where: str) -> None:
    if not isinstance(ideas, list) or not all(isinstance(idea, str) and idea.strip() for idea in ideas):
        raise ChapterFormatError(f"{where}: 'key_ideas' must be a list of short texts.")


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

    parts = level.get("parts")
    if parts is None:
        ranges = [(where, {"line_id": level.get("line_id"), "from_ply": level.get("from_ply"), "to_ply": level.get("to_ply")})]
    else:
        if any(key in level for key in ("line_id", "from_ply", "to_ply")):
            raise ChapterFormatError(f"{where}: use either 'parts' or line_id / from_ply / to_ply, not both.")
        if not isinstance(parts, list) or not parts or not all(isinstance(part, dict) for part in parts):
            raise ChapterFormatError(f"{where}: 'parts' must be a list of {{line_id, from_ply, to_ply}} objects.")
        ranges = [(f"{where}, part {n}", part) for n, part in enumerate(parts, start=1)]

    moves, used = [], {}
    for part_where, part in ranges:
        line = lines.get(part.get("line_id"))
        if line is None:
            raise ChapterFormatError(f"{part_where}: unknown line_id {part.get('line_id')!r}.")
        first, last = part.get("from_ply"), part.get("to_ply")
        if not (_is_int(first) and _is_int(last) and 1 <= first <= last <= len(line)):
            raise ChapterFormatError(
                f"{part_where}: need 1 <= from_ply <= to_ply <= {len(line)}, got from_ply={first!r}, to_ply={last!r}."
            )
        if parts is not None:
            if "intro" in part and not (isinstance(part["intro"], str) and part["intro"].strip()):
                raise ChapterFormatError(f"{part_where}: 'intro' must be a short text.")
            _check_ideas(part.get("key_ideas", []), part_where)
        plies = set(range(first, last + 1))
        if used.get(part["line_id"], set()) & plies:
            raise ChapterFormatError(f"{part_where}: overlaps an earlier part on line '{part['line_id']}'.")
        used.setdefault(part["line_id"], set()).update(plies)
        moves.extend(line[first - 1:last])

    _check_ideas(level.get("key_ideas", []), where)
    if level["type"] == "quiz":
        _validate_quiz(level, where, moves, player_color)


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

def question_count(chapter: dict, level: dict) -> int:
    """How many of the player's moves a level contains (the questions of a quiz)."""
    color = chapter["chapter_meta"]["player_color"]
    return sum(1 for part in level_parts(level)
               for step in chapter["lines"][part["line_id"]][part["from_ply"] - 1:part["to_ply"]]
               if step["turn"] == color)


def quiz_pass_mark(chapter: dict, level: dict) -> float:
    """First-try accuracy a quiz level needs to be passed.

    Normally chapter_meta.min_accuracy_to_pass. In a short quiz that mark can
    mean "no mistake at all" (3 questions: one mistake is 67%), so the mark is
    lowered until chapter_meta.allowed_mistakes first-try mistakes still pass.
    A quiz always needs at least one move right on the first try. The value is
    rounded like LevelSession.accuracy, so the two compare exactly.
    """
    meta = chapter["chapter_meta"]
    pass_mark = meta.get("min_accuracy_to_pass", 0)
    allowed = meta.get("allowed_mistakes", 0)
    count = question_count(chapter, level)
    if 0 < allowed < count:
        return min(pass_mark, round(100 * (count - allowed) / count, 1))
    return pass_mark


def summarize_levels(chapter: dict, line_rows: dict, extra_passed=frozenset()) -> list[dict]:
    """Status of every level of a chapter, for the levels page.

    line_rows    - ChessCoachDB.get_chapter_progress(chapter_id); each level is
                   saved under level_line_id(n).
    extra_passed - level numbers passed during this app session. A Guest saves
                   nothing, so this keeps a Guest moving forward until they leave.

    A learn level counts as passed once it is finished; a quiz level once its
    best accuracy reaches quiz_pass_mark(). Level 1 is always open; any other
    level opens when the level before it is passed.
    """
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
            passed = row["best_accuracy"] is not None and row["best_accuracy"] >= quiz_pass_mark(chapter, level)
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


def summarize_chapter(chapter: dict, line_rows: dict, extra_passed=frozenset()) -> dict:
    """Progress of a whole chapter, for its card on the opening hub.

    Returns levels_total, levels_passed, percent (of levels passed) and status:
    'not_started' (nothing played yet), 'in_progress' or 'completed'.
    """
    levels = summarize_levels(chapter, line_rows, extra_passed)
    passed = sum(1 for level in levels if level["passed"])
    played = passed > 0 or any(level_line_id(level["level"]) in line_rows for level in levels)
    if passed == len(levels):
        status = "completed"
    elif played:
        status = "in_progress"
    else:
        status = "not_started"
    return {
        "levels_total": len(levels),
        "levels_passed": passed,
        "percent": round(100 * passed / len(levels)),
        "status": status,
    }


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

    A level can hold several parts (line ranges, see level_parts). `moves` is
    all of them in order; the board jumps to each part's first position. In a
    learn level each part starts with its own "start" step (current_step is
    None, at_part_start is True), where the screen shows the part's intro.
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
        self.allowed_mistakes = meta.get("allowed_mistakes", 0)
        # The accuracy this level needs (lower than the chapter's mark in a short quiz).
        self.pass_mark = (quiz_pass_mark(chapter, self.level) if self.kind == "quiz"
                          else meta.get("min_accuracy_to_pass", 0))
        self.show_explanations = self.level.get("show_explanations", self.kind == "learn")
        self.retry_mistakes = self.kind == "quiz" and self.level.get("retry_mistakes", False)

        self.parts: list[dict] = []   # level_parts() with "start" / "end" indexes into moves
        self.moves: list[dict] = []
        self._line_ids: list[str] = []  # the line of each move (mistakes are saved per line)
        for part in level_parts(self.level):
            steps = chapter["lines"][part["line_id"]][part["from_ply"] - 1:part["to_ply"]]
            self.parts.append({**part, "start": len(self.moves), "end": len(self.moves) + len(steps)})
            self.moves.extend(steps)
            self._line_ids.extend([part["line_id"]] * len(steps))
        self._part_starts = {part["start"] for part in self.parts}
        self._question_indexes = [i for i, step in enumerate(self.moves) if step["turn"] == self.player_color]
        self.questions = [self.moves[i] for i in self._question_indexes]
        # Learn levels step through frames: (move index, part) after a move, (None, part) at a part's start.
        self._frames = [(index, number) for number, part in enumerate(self.parts)
                        for index in [None, *range(part["start"], part["end"])]]
        self.start_fen = self.moves[0]["fen_before"]
        self.restart()

    def restart(self) -> list[dict]:
        """Starts the level again from its first position.

        Returns the opponent moves played automatically before the first
        question (quiz levels that start with an opponent move), else [].
        """
        self.cursor = 0                   # quiz: self.moves[:cursor] are played; learn: index into _frames
        self._wrong: dict[int, int] = {}  # move index -> wrong attempts in this run (quiz)
        self.first_try_count = 0
        self.answered_count = 0
        self.retry_queue: list[int] = []      # move indexes asked again after the first pass
        self.retry_index = 0
        self._retry_wrong: dict[int, int] = {}
        self.retry_results: dict[int, bool] = {}  # move index -> solved on the first try of the second chance
        return self._play_opponent_moves() if self.kind == "quiz" else []

    # -----------------------------------------------------------------
    # Board state (both level types)
    # -----------------------------------------------------------------
    @property
    def _main_done(self) -> bool:
        if self.kind == "learn":
            return self.cursor >= len(self._frames) - 1
        return self.cursor >= len(self.moves)

    @property
    def in_retry(self) -> bool:
        """True during the second-chance round of a quiz."""
        return self._main_done and self.retry_index < len(self.retry_queue)

    @property
    def fen(self) -> str:
        if self.kind == "learn":
            index, number = self._frames[self.cursor]
            return self.moves[self.parts[number]["start"]]["fen_before"] if index is None else self.moves[index]["fen_after"]
        if self.in_retry:
            return self.current_question["fen_before"]
        if self.cursor < len(self.moves) and self.cursor in self._part_starts:
            return self.moves[self.cursor]["fen_before"]  # a part's first position
        return self.moves[self.cursor - 1]["fen_after"]

    @property
    def last_move(self) -> dict | None:
        """The last move on the board (for highlighting); None at the start of a part."""
        if self.kind == "learn":
            index = self._frames[self.cursor][0]
            return None if index is None else self.moves[index]
        index = self.retry_queue[self.retry_index] if self.in_retry else self.cursor
        if index in self._part_starts:
            return None
        return self.moves[index - 1]

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
        """Moves shown so far (learn levels)."""
        if self.kind == "learn":
            return sum(1 for index, _ in self._frames[1:self.cursor + 1] if index is not None)
        return self.cursor

    @property
    def step_count(self) -> int:
        return len(self.moves)

    def next_step(self) -> dict | None:
        """Plays the next move. Returns it; None at the start of the next part
        or when the level is finished."""
        self._require("learn")
        if self.is_complete:
            return None
        self.cursor += 1
        return self.last_move

    def previous_step(self) -> dict | None:
        """Takes the last move back. Returns the move now being explained (None at a part's start)."""
        self._require("learn")
        self.cursor = max(0, self.cursor - 1)
        return self.last_move

    # -----------------------------------------------------------------
    # Parts (levels with several lines)
    # -----------------------------------------------------------------
    @property
    def part_index(self) -> int:
        """The part on the board now (0 in a level with one line)."""
        if self.kind == "learn":
            return self._frames[self.cursor][1]
        index = self.retry_queue[self.retry_index] if self.in_retry else min(self.cursor, len(self.moves) - 1)
        return next(number for number, part in enumerate(self.parts) if part["start"] <= index < part["end"])

    @property
    def current_part(self) -> dict:
        """The part on the board now: line_id, from_ply, to_ply and its intro / key_ideas if any."""
        return self.parts[self.part_index]

    @property
    def at_part_start(self) -> bool:
        """Learn levels: True before a part's first move (the screen shows its intro)."""
        return self.kind == "learn" and self._frames[self.cursor][0] is None

    @property
    def at_part_end(self) -> bool:
        """Learn levels: True on a part's last move (the screen shows its key ideas)."""
        if self.kind != "learn":
            return False
        index, number = self._frames[self.cursor]
        return index is not None and index == self.parts[number]["end"] - 1

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
            return self.moves[self.retry_queue[self.retry_index]]
        return None if self._main_done else self.moves[self.cursor]

    @property
    def mistake_count(self) -> int:
        """Answered questions of the first pass that were not solved on the first try."""
        return self.answered_count - self.first_try_count

    @property
    def accuracy(self) -> float:
        """Answered questions solved on the first try, in % (100.0 before the first answer)."""
        if not self.answered_count:
            return 100.0
        return round(100 * self.first_try_count / self.answered_count, 1)

    def peek(self, move_text: str) -> dict:
        """classify_move() for the current question; nothing is counted."""
        self._require("quiz")
        question = self.current_question
        if question is None:
            return {"status": "complete"}
        return classify_move(question["fen_before"], question["uci"], move_text)

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
        index = self.retry_queue[self.retry_index] if retrying else self.cursor
        line_id = self._line_ids[index]
        if move.uci() != expected["uci"]:
            counter = self._retry_wrong if retrying else self._wrong
            wrong = counter.get(index, 0) + 1
            counter[index] = wrong
            rule = self._rule_for(wrong)
            reveal = rule["action"] == "show_correct_move"
            return {
                "status": "incorrect",
                "retry": retrying,
                "line_id": line_id,
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
            wrong = self._retry_wrong.get(index, 0)
            self.retry_results[index] = wrong == 0
            self.retry_index += 1
            opponent_moves = []
        else:
            wrong = self._wrong.get(index, 0)
            self.answered_count += 1
            if wrong == 0:
                self.first_try_count += 1
            self.cursor += 1
            opponent_moves = self._play_opponent_moves()
            if self._main_done and self.retry_mistakes:
                self.retry_queue = [i for i in self._question_indexes if self._wrong.get(i)]
        return {
            "status": "correct",
            "retry": retrying,
            "starts_retry": not retrying and self.in_retry,
            "line_id": line_id,
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
        current = None if self._main_done else self.cursor
        states = []
        for index in self._question_indexes:
            if current is None or index < current:
                wrong = self._wrong.get(index, 0)
                states.append("ok" if wrong == 0 else self._mistake_state(wrong))
            elif index == current:
                states.append("current")
            else:
                states.append("pending")
        return states

    def review_items(self) -> list[dict]:
        """Positions the player got wrong in this run, with their review days
        (taken from the on_mistake rule of the last wrong attempt)."""
        items = []
        for index in self._question_indexes:
            step = self.moves[index]
            wrong = self._wrong.get(index, 0)
            if wrong:
                items.append({
                    "line_id": self._line_ids[index],
                    "ply": step["ply"],
                    "move_number": step["move_number"],
                    "san": step["san"],
                    "fen": step["fen_before"],
                    "wrong_attempts": wrong,
                    "review_days": list(self._rule_for(wrong)["review_days"]),
                    # second chance: True = solved at once, False = not, None = no second chance (yet)
                    "fixed": self.retry_results.get(index),
                })
        return items

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    def _rule_for(self, wrong_attempt: int) -> dict:
        return rule_for(self.level["on_mistake"], wrong_attempt)

    def _mistake_state(self, wrong: int) -> str:
        return mistake_state(self.level["on_mistake"], wrong)

    def _play_opponent_moves(self) -> list[dict]:
        played = []
        while not self._main_done and self.moves[self.cursor]["turn"] != self.player_color:
            played.append(self.moves[self.cursor])
            self.cursor += 1
        return played

    def _require(self, kind: str) -> None:
        if self.kind != kind:
            raise RuntimeError(f"Level {self.level_number} is a {self.kind} level, not a {kind} level.")


# =====================================================================
# 4. Review sessions (Daily review)
# =====================================================================

def _is_last_review(row: dict) -> bool:
    """True when this review would master the position: the last day of its plan (day 7)."""
    days = row.get("review_days")
    return bool(days) and row.get("streak_correct", 0) + 1 >= len(str(days).split(","))


def asks_purpose(item: dict) -> bool:
    """True when a first-try move on this review question is followed by the
    purpose question: its last review, and the move has one written."""
    return bool(item.get("final_keys")) and item.get("purpose") is not None


def build_review_items(rows: list[dict], chapters: dict) -> list[dict]:
    """Turns due database rows (ChessCoachDB.get_due_mistakes) into review questions.

    chapters maps chapter_id -> a validated format-2 chapter. A row is skipped
    when its chapter, line or position no longer matches the chapter file (the
    lesson has changed) or when it is not the player's move. Rows for the same
    position (lines share their first moves) become one question; its "keys"
    list every (line_id, ply) so the screen can update all of them, and
    "final_keys" the rows for which this is the last review (see asks_purpose).
    """
    items, by_position = [], {}
    for row in rows:
        chapter = chapters.get(row["chapter_id"])
        if chapter is None:
            continue
        line = chapter["lines"].get(row["line_id"])
        ply = row["ply"]
        if not line or not 1 <= ply <= len(line):
            continue
        step = line[ply - 1]
        meta = chapter["chapter_meta"]
        if step["fen_before"] != row["fen"] or step["turn"] != meta["player_color"]:
            continue
        position = (row["chapter_id"], row["fen"])
        key = (row["line_id"], ply)
        final = [key] if _is_last_review(row) else []
        if position in by_position:
            by_position[position]["keys"].append(key)
            by_position[position]["final_keys"].extend(final)
            continue
        item = {
            "chapter_id": row["chapter_id"],
            "chapter_title": meta["chapter_title"],
            "player_color": meta["player_color"],
            "line_id": row["line_id"],
            "ply": ply,
            "step": step,
            "previous": line[ply - 2] if ply > 1 else None,
            "keys": [key],
            "final_keys": final,
            "purpose": step.get("purpose"),
        }
        by_position[position] = item
        items.append(item)
    return items


class ReviewSession:
    """Plays the positions due for review one after another (the Daily review).

    The rules are the quizzes': the hint first, then the correct move, which
    the player then plays. Each incorrect result carries the review_days that
    restart that position's plan.

    On a position's last review (day 7), a first-try move is followed by the
    purpose question ("Why do you play 9. e4?", owner's decision 2026-11-17):
    submit_move() then returns ask_purpose=True and the session waits for
    answer_purpose() before it moves on. The screen masters the position only
    when that answer is right too.
    """

    def __init__(self, items: list[dict], rules=DEFAULT_MISTAKE_RULES, rng: random.Random | None = None):
        self.items = items
        self.rules = list(rules)
        self.index = 0
        self._wrong: dict[int, int] = {}  # item index -> wrong attempts
        self.first_try_count = 0
        self.awaiting_purpose = False     # True between a first-try move and its purpose answer
        self._rng = rng or random.Random()
        self._choices: dict[int, list[tuple[str, bool]]] = {}  # item index -> answers in shown order
        self._purpose_right: dict[int, bool] = {}             # item index -> purpose answered right

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def is_complete(self) -> bool:
        return self.index >= len(self.items)

    @property
    def current(self) -> dict | None:
        return None if self.is_complete else self.items[self.index]

    @property
    def answered_count(self) -> int:
        """Positions whose move is found (one may still wait for its purpose answer)."""
        return self.index + (1 if self.awaiting_purpose else 0)

    @property
    def purpose_asked(self) -> int:
        return len(self._purpose_right)

    @property
    def purpose_right_count(self) -> int:
        return sum(self._purpose_right.values())

    @property
    def purpose_choices(self) -> list[str]:
        """The answers of the open purpose question, in a shuffled order that stays
        the same until it is answered; [] when no purpose question is open."""
        return [text for text, _ in self._shuffled()] if self.awaiting_purpose else []

    @property
    def fen(self) -> str:
        if self.current is not None:
            return self.current["step"]["fen_before"]
        return self.items[-1]["step"]["fen_after"] if self.items else chess.STARTING_FEN

    @property
    def last_move(self) -> dict | None:
        """The move before the question (to highlight), or the last answer once finished."""
        if self.current is not None:
            return self.current["previous"]
        return self.items[-1]["step"] if self.items else None

    @property
    def accuracy(self) -> float:
        if not self.answered_count:
            return 100.0
        return round(100 * self.first_try_count / self.answered_count, 1)

    def peek(self, move_text: str) -> dict:
        """classify_move() for the current position; nothing is counted."""
        item = self.current
        if item is None:
            return {"status": "complete"}
        if self.awaiting_purpose:
            return {"status": "purpose_pending"}
        return classify_move(item["step"]["fen_before"], item["step"]["uci"], move_text)

    def submit_move(self, move_text: str) -> dict:
        """Checks the player's move; the result looks like LevelSession.submit_move's."""
        item = self.current
        if item is None:
            return {"status": "complete", "fen": self.fen}
        if self.awaiting_purpose:
            return {"status": "purpose_pending", "fen": item["step"]["fen_after"]}
        step = item["step"]
        board = chess.Board(step["fen_before"])
        move = _parse_move(board, move_text)
        if move is None:
            return {"status": "illegal", "fen": step["fen_before"],
                    "message": f"{move_text!r} is not a legal move in this position."}

        if move.uci() != step["uci"]:
            wrong = self._wrong.get(self.index, 0) + 1
            self._wrong[self.index] = wrong
            rule = rule_for(self.rules, wrong)
            reveal = rule["action"] == "show_correct_move"
            return {
                "status": "incorrect",
                "item": item,
                "ply": step["ply"],
                "fen": step["fen_before"],
                "played_san": board.san(move),
                "played_uci": move.uci(),
                "wrong_attempt": wrong,
                "action": rule["action"],
                "hint": step["hint"] if rule["action"] == "show_hint" else None,
                "correct_san": step["san"] if reveal else None,
                "correct_uci": step["uci"] if reveal else None,
                "review_days": list(rule["review_days"]),
            }

        wrong = self._wrong.get(self.index, 0)
        if wrong == 0:
            self.first_try_count += 1
        ask = wrong == 0 and asks_purpose(item)
        if ask:
            self.awaiting_purpose = True  # the same position stays current until answer_purpose()
        else:
            self.index += 1
        return {
            "status": "correct",
            "item": item,
            "ply": step["ply"],
            "san": step["san"],
            "uci": step["uci"],
            "first_try": wrong == 0,
            "wrong_attempts": wrong,
            "ask_purpose": ask,
            "is_complete": self.is_complete,
        }

    def answer_purpose(self, choice: int) -> dict:
        """The player picks answer number `choice` (0-based, in purpose_choices order).

        Returns status 'right' or 'wrong' with the answers as shown ("choices"),
        "chosen", "answer_index" and the right "answer" text; then the next
        position is current.
        """
        if not self.awaiting_purpose:
            return {"status": "no_question"}
        choices = self._shuffled()
        if not (_is_int(choice) and 0 <= choice < len(choices)):
            return {"status": "invalid", "message": f"Pick an answer from 1 to {len(choices)}."}
        item = self.current
        right = choices[choice][1]
        self._purpose_right[self.index] = right
        self.awaiting_purpose = False
        self.index += 1
        return {
            "status": "right" if right else "wrong",
            "item": item,
            "choices": [text for text, _ in choices],
            "chosen": choice,
            "answer_index": next(number for number, (_, ok) in enumerate(choices) if ok),
            "answer": item["purpose"]["answer"],
            "is_complete": self.is_complete,
        }

    def _shuffled(self) -> list[tuple[str, bool]]:
        """(text, is_right) for the current position's purpose answers, shuffled once."""
        if self.index not in self._choices:
            purpose = self.current["purpose"]
            choices = [(purpose["answer"], True)] + [(text, False) for text in purpose["wrong"]]
            self._rng.shuffle(choices)
            self._choices[self.index] = choices
        return self._choices[self.index]

    def question_states(self) -> list[str]:
        """'ok', 'hint', 'shown', 'current' or 'pending' for each position.
        A wrong purpose answer after a right move shows as 'hint'."""
        states = []
        for number in range(len(self.items)):
            if number < self.index:
                wrong = self._wrong.get(number, 0)
                if wrong:
                    states.append(mistake_state(self.rules, wrong))
                else:
                    states.append("hint" if self._purpose_right.get(number) is False else "ok")
            else:
                states.append("current" if number == self.index else "pending")
        return states


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
        while not session.is_complete:
            step = session.next_step()
            if step is None:  # the next line of a level with several lines
                print(f"--- {session.current_part.get('intro') or 'next line'}")
                continue
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
