"""
ChessCoach - opening hub data (e.g. catalan_opening.json)
=========================================================
An opening's start page: the introduction, the ideal setup shown on a board,
and the list of chapters. A chapter without a file is shown as "Coming soon";
adding it later only means filling in its "file". Pure data and python-chess
(no UI, no database); the screen is opening_hub_view.py.
"""

import json
from pathlib import Path

import chess

from level_trainer import load_level_chapter


class OpeningFormatError(ValueError):
    """Raised when an opening file is broken: missing text, illegal setup move, bad chapter list, ..."""


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_opening(json_path: str | Path) -> dict:
    """Reads an opening file and validates it (see validate_opening)."""
    path = Path(json_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return validate_opening(data, path.parent)


def validate_opening(data: dict, folder: str | Path) -> dict:
    """Checks an opening and fills in two computed fields: setup["fen"] (the
    setup position) and each chapter's "path" (its file inside `folder`, or
    None for a chapter that is coming soon). Returns the same dict."""
    for key in ("title", "intro"):
        if not _text(data.get(key)):
            raise OpeningFormatError(f"'{key}' is missing.")
    for key in ("subtitle", "release_note"):
        if key in data and not _text(data[key]):
            raise OpeningFormatError(f"'{key}' must be a text.")
    if data.get("player_color", "white") not in ("white", "black"):
        raise OpeningFormatError(f"'player_color' must be 'white' or 'black', got {data.get('player_color')!r}.")
    focus = data.get("strategic_focus", [])
    if not isinstance(focus, list) or not all(_text(item) for item in focus):
        raise OpeningFormatError("'strategic_focus' must be a list of short texts.")

    if "setup" in data:
        _validate_setup(data["setup"])

    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise OpeningFormatError("The opening needs at least one chapter in 'chapters'.")
    for number, chapter in enumerate(chapters, start=1):
        where = f"Chapter {number}"
        if not isinstance(chapter, dict) or chapter.get("number") != number:
            raise OpeningFormatError(f"{where}: 'number' must be {number} (chapters are numbered 1, 2, 3, ...).")
        if not _text(chapter.get("title")):
            raise OpeningFormatError(f"{where}: 'title' is missing.")
        file = chapter.get("file")
        if file is not None and not (_text(file) and file.lower().endswith(".json")):
            raise OpeningFormatError(f"{where}: 'file' must be a .json file name or null, got {file!r}.")
        chapter["path"] = str(Path(folder) / file) if file else None
    return data


def _validate_setup(setup) -> None:
    if not isinstance(setup, dict):
        raise OpeningFormatError("'setup' must be an object.")
    moves = setup.get("moves", [])
    if not isinstance(moves, list):
        raise OpeningFormatError("setup 'moves' must be a list of moves.")
    board = chess.Board()
    for number, san in enumerate(moves, start=1):
        try:
            board.push_san(san)
        except (TypeError, ValueError) as exc:
            raise OpeningFormatError(f"setup move {number} ({san!r}) is not a legal move here.") from exc
    setup["fen"] = board.fen()

    squares = ([setup["focus_square"]] if "focus_square" in setup else []) + list(setup.get("path", []))
    for name in squares:
        try:
            chess.parse_square(name)
        except (TypeError, ValueError) as exc:
            raise OpeningFormatError(f"setup square {name!r} is not a square like 'g2'.") from exc


def load_hub_chapters(opening: dict) -> list[dict]:
    """Each chapter of a validated opening with its content loaded.

    Returns dicts with number, title, path, chapter (the loaded chapter, or
    None when it is coming soon or broken) and error (why it could not be
    loaded, else None). A broken chapter file never stops the hub.
    """
    items = []
    for entry in opening["chapters"]:
        item = {"number": entry["number"], "title": entry["title"], "path": entry["path"],
                "chapter": None, "error": None}
        if entry["path"]:
            try:
                item["chapter"] = load_level_chapter(entry["path"])
            except (OSError, ValueError) as exc:  # missing file, broken JSON, illegal move, ...
                item["error"] = str(exc)
        items.append(item)
    return items
