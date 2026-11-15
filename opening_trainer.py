import json
from pathlib import Path
import chess


class OpeningValidationError(Exception):
    """Raised when a chapter JSON contains illegal chess moves or broken ply links."""


def load_and_validate_chapter(json_path: str | Path) -> dict:
    """Loads chapter JSON, verifies every move with python-chess, and injects FEN/UCI data."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    board = chess.Board()
    board_snapshots = {0: board.copy()}

    for i, step in enumerate(data.get("core_trunk", [])):
        expected_ply = i + 1
        if step.get("ply") != expected_ply:
            raise OpeningValidationError(
                f"Core trunk ply mismatch at index {i}: got {step.get('ply')}, expected {expected_ply}"
            )
        try:
            move = board.parse_san(step["san"])
        except ValueError as exc:
            raise OpeningValidationError(
                f"Illegal move in core_trunk at ply {expected_ply} ('{step.get('san')}'): {exc}"
            ) from exc

        step["fen_before"] = board.fen()
        step["uci"] = move.uci()
        board.push(move)
        step["fen_after"] = board.fen()
        board_snapshots[expected_ply] = board.copy()

    for branch in data.get("branches", []):
        b_id = branch.get("branch_id", "unknown")
        dev_ply = branch.get("deviation_after_ply")
        if dev_ply not in board_snapshots:
            raise OpeningValidationError(f"Branch '{b_id}' has invalid deviation_after_ply: {dev_ply}")

        b_board = board_snapshots[dev_ply].copy()
        trig = branch["trigger_move"]
        try:
            move = b_board.parse_san(trig["san"])
        except ValueError as exc:
            raise OpeningValidationError(
                f"Illegal trigger_move in '{b_id}' ('{trig.get('san')}'): {exc}"
            ) from exc

        trig["fen_before"] = b_board.fen()
        trig["uci"] = move.uci()
        b_board.push(move)
        trig["fen_after"] = b_board.fen()

        for c_step in branch.get("continuation", []):
            try:
                move = b_board.parse_san(c_step["san"])
            except ValueError as exc:
                raise OpeningValidationError(
                    f"Illegal move in '{b_id}' at ply {c_step.get('ply')} ('{c_step.get('san')}'): {exc}"
                ) from exc

            c_step["fen_before"] = b_board.fen()
            c_step["uci"] = move.uci()
            b_board.push(move)
            c_step["fen_after"] = b_board.fen()

    return data


class OpeningSession:
    """State-machine controller for Core Trunk, Branches, and Review Phase."""

    def __init__(self, chapter_data: dict):
        self.data = chapter_data
        self.player_color = chapter_data["chapter_meta"]["player_color"]
        self.mode = "core"  # "core" | "branch" | "review"
        self.active_branch_id: str | None = None
        self.sequence: list[dict] = []
        self.cursor = 0
        self.attempts = 0
        self.correct_first_try = 0
        self._had_error_on_current_step = False
        self.start_core()

    def _reset_accuracy(self) -> None:
        """Every run (core, branch or review) is scored on its own, from zero."""
        self.attempts = 0
        self.correct_first_try = 0
        self._had_error_on_current_step = False

    def start_core(self) -> dict:
        self.mode = "core"
        self.active_branch_id = None
        self.sequence = list(self.data["core_trunk"])
        self.cursor = 0
        self._reset_accuracy()
        return self._auto_advance_opponent()

    def start_branch(self, branch_id: str) -> dict:
        branch = next((b for b in self.data["branches"] if b["branch_id"] == branch_id), None)
        if not branch:
            raise ValueError(f"Branch '{branch_id}' not found.")

        dev_ply = branch["deviation_after_ply"]
        prefix = [step for step in self.data["core_trunk"] if step["ply"] <= dev_ply]
        self.mode = "branch"
        self.active_branch_id = branch_id
        self.sequence = prefix + [branch["trigger_move"]] + list(branch["continuation"])
        # Jump directly to the deviation point so the user doesn't replay already-learned trunk moves
        self.cursor = len(prefix)
        self._reset_accuracy()
        return self._auto_advance_opponent()

    def start_review(self) -> dict:
        self.mode = "review"
        self.active_branch_id = None
        self.sequence = list(self.data["core_trunk"])
        self.cursor = 0
        self._reset_accuracy()
        return self._auto_advance_opponent()

    @property
    def current_fen(self) -> str:
        if self.cursor == 0:
            return chess.STARTING_FEN
        if self.cursor <= len(self.sequence):
            return self.sequence[self.cursor - 1]["fen_after"]
        return self.sequence[-1]["fen_after"]

    @property
    def is_complete(self) -> bool:
        return self.cursor >= len(self.sequence)

    def _auto_advance_opponent(self) -> dict:
        """Plays opponent moves automatically until it is the player's turn or the line ends."""
        opponent_moves = []
        while not self.is_complete and self.sequence[self.cursor]["turn"] != self.player_color:
            opponent_moves.append(self.sequence[self.cursor])
            self.cursor += 1

        return {
            "mode": self.mode,
            "branch_id": self.active_branch_id,
            "fen": self.current_fen,
            "opponent_moves": opponent_moves,
            "is_complete": self.is_complete,
            "next_expected_ply": None if self.is_complete else self.sequence[self.cursor]["ply"],
        }

    def submit_move(self, user_input: str) -> dict:
        """Validates user move (SAN or UCI). Advances on match; returns hint on mistake."""
        if self.is_complete:
            return {"status": "already_complete", "fen": self.current_fen}

        expected = self.sequence[self.cursor]
        board = chess.Board(expected["fen_before"])

        # Normalize user input (supports both SAN like 'Nf3' and UCI like 'g1f3')
        try:
            try:
                parsed_move = board.parse_san(user_input.strip())
            except ValueError:
                parsed_move = board.parse_uci(user_input.strip().lower())
        except ValueError:
            return {
                "status": "illegal_syntax_or_move",
                "message": f"'{user_input}' is not a legal chess move in this position.",
                "fen": expected["fen_before"],
            }

        if parsed_move.uci() != expected["uci"]:
            self._had_error_on_current_step = True
            return {
                "status": "incorrect",
                "ply": expected["ply"],
                "played_san": board.san(parsed_move),
                "hint": expected["hint"],
                "fen": expected["fen_before"],
            }

        # Correct move
        first_try = not self._had_error_on_current_step
        if first_try:
            self.correct_first_try += 1
        self.attempts += 1
        self._had_error_on_current_step = False
        self.cursor += 1

        follow_up = self._auto_advance_opponent()
        accuracy = round((self.correct_first_try / self.attempts) * 100, 1) if self.attempts else 100.0

        return {
            "status": "correct",
            "ply": expected["ply"],
            "first_try": first_try,
            "played_san": expected["san"],
            "strategic_idea": expected["strategic_idea"],
            "explanation": expected["explanation"],
            "accuracy": accuracy,
            **follow_up,
        }


if __name__ == "__main__":
    # Quick terminal test runner before hooking up Flet UI
    chapter = load_and_validate_chapter("catalan_ch01.json")
    session = OpeningSession(chapter)
    print(f"Loaded: {chapter['chapter_meta']['chapter_title']}")

    while not session.is_complete:
        move_str = input(f"\n[Ply {session.sequence[session.cursor]['ply']}] Your move (White): ")
        res = session.submit_move(move_str)
        if res["status"] == "correct":
            print(f"✔ {res['played_san']} — {res['strategic_idea']}")
            for opp in res["opponent_moves"]:
                print(f"  Opponent plays: {opp['san']} ({opp['strategic_idea']})")
        elif res["status"] == "incorrect":
            print(f"✘ Not quite ({res['played_san']}). Hint: {res['hint']}")
        else:
            print(f"! {res['message']}")

    print("\nCore Trunk complete! Ready for branches or Flet UI integration.")
