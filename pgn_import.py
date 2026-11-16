r"""
ChessCoach - Lichess study importer
===================================
Turns the PGN export of a Lichess study into a chapter file in format 2 (the
format level_trainer.py reads), so chapter files are no longer typed by hand.

How a study becomes a chapter (DESIGN.md section 0):
    the whole study          -> one chapter (one branch of the opening)
    each study chapter       -> a learn level followed by a quiz level
    a study chapter's line   -> written in full from move 1; its levels teach
                                and test only the moves that are new compared
                                with the study chapters before it
    comment after a move     -> that move's idea; a second line becomes its
                                explanation; text after "Hint:" its hint
    comment before move 1    -> the learn level's intro

Left out on purpose: every PGN header except the study and chapter names and
the board orientation (so no player names, ECO codes, links or the author's
account reach the app), Lichess commands such as [%cal ...] and [%eval ...],
move symbols (!, ?), side variations (give each sub-branch its own study
chapter instead) and every move after move 14.

Usage, from the project folder:
    .venv\Scripts\python.exe pgn_import.py my_study.pgn catalan_ch02.json
The output file's name becomes the chapter_id. An existing file is never
replaced unless --force is given.
"""

import argparse
import copy
import io
import json
import re
import sys
from pathlib import Path

import chess
import chess.pgn

from level_trainer import FORMAT_VERSION, ChapterFormatError, validate_level_chapter

MAX_MOVE_NUMBER = 14  # owner's rule: a branch ends by move 14 at the latest
DEFAULT_PASS_MARK = 85
DEFAULT_OPENING_NAME = "Catalan Opening"
DEFAULT_MISTAKE_RULES = (
    {"wrong_attempt": 1, "action": "show_hint", "review_days": [1, 7]},
    {"wrong_attempt": 2, "action": "show_correct_move", "review_days": [1, 3, 7]},
)

_COMMAND = re.compile(r"\[%[^\]]*\]")  # [%cal Gb1d2], [%csl Ge4], [%eval 0.3], [%clk 0:05:00]
_HINT_MARKER = re.compile(r"(?:\bhint|تلميح)\s*:\s*", re.IGNORECASE)
_NUMBER_LIST = re.compile(r"\[\s*((?:\d+,\s*)*\d+)\s*\]")


class PgnImportError(ValueError):
    """Raised when a study PGN cannot become a chapter (illegal move, nothing new to teach, ...)."""


# =====================================================================
# 1. Comments and headers
# =====================================================================

def _clean_comment(text: str | None) -> str:
    """Removes Lichess commands such as [%cal Gb1d2] and extra spaces; keeps line breaks."""
    text = _COMMAND.sub(" ", text or "")
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _one_paragraph(text: str | None) -> str:
    return " ".join(_clean_comment(text).split())


def _split_comment(text: str | None) -> tuple[str | None, str | None, str | None]:
    """'idea' [newline 'explanation'] ['Hint: hint'] -> (idea, explanation, hint); missing parts are None."""
    text = _clean_comment(text)
    hint = None
    parts = _HINT_MARKER.split(text, maxsplit=1)
    if len(parts) == 2:
        text, hint = parts[0], " ".join(parts[1].split()) or None
    idea, _, explanation = text.strip().partition("\n")
    return idea.strip() or None, " ".join(explanation.split()) or None, hint


def _move_label(step: dict) -> str:
    dots = "." if step["turn"] == "white" else "..."
    return f"{step['move_number']}{dots}{step['san']}"


def _split_event(game: chess.pgn.Game) -> tuple[str, str]:
    """Lichess writes Event as 'Study name: Chapter name'. Study names often contain
    ': ' themselves, so the last ': ' is the separator. Only used when the
    StudyName / ChapterName headers are missing."""
    study, separator, chapter = game.headers.get("Event", "").rpartition(": ")
    return (study, chapter) if separator else ("", "")


def _chapter_name(game: chess.pgn.Game, number: int) -> str:
    name = game.headers.get("ChapterName") or _split_event(game)[1]
    return name.strip() or f"Chapter {number}"


def _study_name(game: chess.pgn.Game) -> str:
    name = game.headers.get("StudyName") or _split_event(game)[0]
    return name.strip()


# =====================================================================
# 2. Reading the study
# =====================================================================

class _QuietGameBuilder(chess.pgn.GameBuilder):
    """Collects PGN errors in game.errors without printing a traceback."""

    def handle_error(self, error: Exception) -> None:
        self.game.errors.append(error)


def _read_games(pgn_text: str) -> list[chess.pgn.Game]:
    stream = io.StringIO(pgn_text)
    games = []
    while (game := chess.pgn.read_game(stream, Visitor=_QuietGameBuilder)) is not None:
        games.append(game)
    return games


def _game_moves(game: chess.pgn.Game, name: str, player_color: str, warnings: list[str]) -> list[dict]:
    """The main line of one study chapter as chapter-file moves, checked by python-chess."""
    if game.errors:
        raise PgnImportError(f"Chapter {name!r}: {game.errors[0]}")
    board = game.board()
    if type(board) is not chess.Board or board.fen() != chess.STARTING_FEN:
        raise PgnImportError(f"Chapter {name!r} must start from the normal starting position (standard chess).")

    moves, has_side_lines, node = [], False, game
    while node.variations:
        has_side_lines = has_side_lines or len(node.variations) > 1
        node = node.variations[0]
        idea, explanation, hint = _split_comment(node.comment)
        step = {
            "ply": len(moves) + 1,
            "move_number": board.fullmove_number,
            "turn": "white" if board.turn == chess.WHITE else "black",
            "san": board.san(node.move),
            "strategic_idea": idea,
            "explanation": explanation,
            "hint": hint,
        }
        if hint and step["turn"] != player_color:
            warnings.append(
                f"Chapter {name!r}: the hint on {_move_label(step)} was left out "
                f"(hints are only for {player_color}'s moves)."
            )
            step["hint"] = None
        moves.append(step)
        board.push(node.move)

    if not moves:
        raise PgnImportError(f"Chapter {name!r} has no moves.")
    if has_side_lines:
        warnings.append(f"Chapter {name!r}: side variations were left out. Give each sub-branch its own study chapter.")
    limit = 2 * MAX_MOVE_NUMBER
    if len(moves) > limit:
        warnings.append(
            f"Chapter {name!r}: {len(moves) - limit} move(s) after move {MAX_MOVE_NUMBER} were left out, "
            f"starting with {_move_label(moves[limit])}."
        )
        moves = moves[:limit]
    return moves


def _place_line(lines: dict, moves: list[dict], name: str) -> tuple[str, int]:
    """Stores a study chapter's moves in `lines`; returns (line_id, first new ply).

    A chapter that continues an existing line extends that line; a chapter that
    leaves it gets a new line. Only the moves after the shared start are new.
    """
    best_id, shared = None, 0
    for line_id, line in lines.items():
        common = 0
        for old, new in zip(line, moves):
            if old["san"] != new["san"]:
                break
            common += 1
        if best_id is None or common > shared:
            best_id, shared = line_id, common

    if shared == len(moves):
        raise PgnImportError(f"Chapter {name!r} has no new moves: an earlier chapter already covers its whole line.")
    if best_id is not None and shared == len(lines[best_id]):
        lines[best_id].extend(moves[shared:])
        return best_id, shared + 1
    line_id = "main" if not lines else f"line_{len(lines) + 1}"
    lines[line_id] = moves
    return line_id, shared + 1


# =====================================================================
# 3. Building and writing the chapter
# =====================================================================

def pgn_to_chapter(
    pgn_text: str,
    chapter_id: str,
    player_color: str | None = None,
    opening_name: str = DEFAULT_OPENING_NAME,
    pass_mark: int = DEFAULT_PASS_MARK,
) -> tuple[dict, list[str]]:
    """Builds a format-2 chapter from a study PGN. Returns (chapter, warnings).

    player_color None means: use the study's board orientation, else white.
    The result is checked with level_trainer.validate_level_chapter().
    """
    if player_color not in (None, "white", "black"):
        raise PgnImportError(f"player_color must be 'white' or 'black', got {player_color!r}.")
    games = _read_games(pgn_text)
    if not games:
        raise PgnImportError("The PGN has no chapters.")
    if player_color is None:
        orientation = games[0].headers.get("Orientation", "").lower()
        player_color = orientation if orientation in ("white", "black") else "white"

    warnings: list[str] = []
    lines: dict[str, list[dict]] = {}
    levels: list[dict] = []
    for number, game in enumerate(games, start=1):
        name = _chapter_name(game, number)
        moves = _game_moves(game, name, player_color, warnings)
        line_id, first_new = _place_line(lines, moves, name)
        last = len(moves)
        if not any(step["turn"] == player_color for step in lines[line_id][first_new - 1:last]):
            raise PgnImportError(
                f"Chapter {name!r}: its new moves have no {player_color} move, so the quiz would have "
                f"no question. Add at least one {player_color} move."
            )

        learn = {"level": len(levels) + 1, "type": "learn", "title": name, "line_id": line_id,
                 "from_ply": first_new, "to_ply": last}
        intro = _one_paragraph(game.comment)
        if intro:
            learn["intro"] = intro
        levels.append(learn)
        levels.append({
            "level": len(levels) + 1, "type": "quiz", "title": f"Test: {name}", "line_id": line_id,
            "from_ply": first_new, "to_ply": last, "question_type": "play_move",
            "show_explanations": False, "on_mistake": copy.deepcopy(list(DEFAULT_MISTAKE_RULES)),
        })

    chapter = {
        "format_version": FORMAT_VERSION,
        "chapter_meta": {
            "chapter_id": chapter_id,
            "opening_name": opening_name,
            "chapter_title": _study_name(games[0]) or chapter_id,
            "player_color": player_color,
            "description": _one_paragraph(games[0].comment),
            "min_accuracy_to_pass": pass_mark,
        },
        "lines": lines,
        "levels": levels,
    }
    try:
        validate_level_chapter(copy.deepcopy(chapter))  # the copy keeps fen/uci fields out of the file
    except ChapterFormatError as exc:
        raise PgnImportError(f"The imported chapter is not valid: {exc}") from exc
    return chapter, warnings


def chapter_to_json(chapter: dict) -> str:
    """JSON text in the project's style: 4-space indent, short number lists on one line."""
    text = json.dumps(chapter, indent=4, ensure_ascii=False)
    text = _NUMBER_LIST.sub(lambda m: "[" + ", ".join(n.strip() for n in m.group(1).split(",")) + "]", text)
    return text + "\n"


def import_pgn_file(
    pgn_path: str | Path,
    json_path: str | Path,
    player_color: str | None = None,
    opening_name: str = DEFAULT_OPENING_NAME,
    pass_mark: int = DEFAULT_PASS_MARK,
    force: bool = False,
) -> tuple[dict, list[str]]:
    """Reads a study PGN file and writes the chapter file. Returns (chapter, warnings).

    The JSON file's name (without .json) becomes the chapter_id. An existing
    file is only replaced when force is True.
    """
    json_path = Path(json_path)
    if json_path.suffix.lower() != ".json":
        raise PgnImportError(f"The output file must end in .json, got {json_path.name!r}.")
    if json_path.exists() and not force:
        raise PgnImportError(f"{json_path} already exists. Choose another name, or add --force to replace it.")
    pgn_text = Path(pgn_path).read_text(encoding="utf-8-sig")
    chapter, warnings = pgn_to_chapter(pgn_text, json_path.stem, player_color, opening_name, pass_mark)
    with open(json_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(chapter_to_json(chapter))
    return chapter, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Turn a Lichess study PGN into a ChessCoach chapter file (format 2).")
    parser.add_argument("pgn", help="PGN file downloaded from a Lichess study")
    parser.add_argument("output", help="chapter file to write, e.g. catalan_ch02.json (its name becomes the chapter_id)")
    parser.add_argument("--color", choices=("white", "black"),
                        help="side the player trains (default: the study's board orientation, else white)")
    parser.add_argument("--opening", default=DEFAULT_OPENING_NAME,
                        help=f"opening name shown in the app (default: {DEFAULT_OPENING_NAME})")
    parser.add_argument("--pass-mark", type=int, default=DEFAULT_PASS_MARK,
                        help=f"quiz accuracy needed to pass, in %% (default: {DEFAULT_PASS_MARK})")
    parser.add_argument("--force", action="store_true", help="replace the output file if it already exists")
    args = parser.parse_args(argv)

    try:
        chapter, warnings = import_pgn_file(args.pgn, args.output, args.color, args.opening, args.pass_mark, args.force)
    except (PgnImportError, OSError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"Warning: {warning}")
    meta = chapter["chapter_meta"]
    print(f"Wrote {args.output}: {meta['chapter_title']} ({meta['player_color']}), "
          f"{len(chapter['lines'])} line(s), {len(chapter['levels'])} levels")
    for level in chapter["levels"]:
        print(f"  level {level['level']:>2}  {level['type']:<5}  {level['line_id']} plies "
              f"{level['from_ply']}-{level['to_ply']}  {level['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
