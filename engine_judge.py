"""
ChessCoach - Stockfish as a second opinion (DESIGN.md section 5)
================================================================
The lesson's moves come from human theory and stay the truth. The engine only
answers two questions, and only after the player has moved:

    judge_alternative()  is a move that differs from the lesson's move
                         "off-book but acceptable"? It is when the engine rates
                         it at most MAX_LOSS_CP centipawns worse than the book
                         move (or better). Such a move is not a mistake: no
                         hint, no review.
    engine_opinion()     what the engine thinks of a lesson position: its best
                         move and line, and how the book move compares (for the
                         optional "Use engine" card after a level).

EngineAssistant gives the screens thread-safe access to the app's Stockfish
(the app's engine lock and time limit). Everything here blocks, so the screens
call it from a background thread.

built_for_other_processor() helps the app choose which Stockfish file to start.
"""

import os
import platform

import chess
import chess.engine

MAX_LOSS_CP = 50       # owner-approved: at most half a pawn worse than the book move
MATE_SCORE = 100_000   # a mate counts as this many centipawns
MIN_TIME, MAX_TIME = 0.1, 2.0  # seconds per analysis: a quiz never waits long

# Processor tags in Stockfish file names (stockfish-windows-x86-64-avx2.exe, ...-arm64-universal.exe)
_PROCESSOR_TAGS = {
    "x86-64": ("x86-64", "x86_64", "amd64", "x64"),
    "arm64": ("arm64", "aarch64", "armv8"),
}
_MACHINES = {"amd64": "x86-64", "x86_64": "x86-64", "arm64": "arm64", "aarch64": "arm64"}


def built_for_other_processor(path: str, machine: str = "") -> bool:
    """True when the file name names another processor than this PC's (platform.machine()).

    Such a download cannot start here (an ARM64 build on an x86-64 PC fails with
    WinError 216), so the app tries those files last. A name without a processor
    tag counts as fine.
    """
    family = _MACHINES.get((machine or platform.machine()).lower())
    name = os.path.basename(path).lower()
    return family is not None and any(
        tag in name for other, tags in _PROCESSOR_TAGS.items() if other != family for tag in tags)


def _cp(score: chess.engine.PovScore, color: chess.Color) -> int:
    return score.pov(color).score(mate_score=MATE_SCORE)


def judge_alternative(engine, fen: str, book_uci: str, played_uci: str,
                      time_limit: float = 0.5, max_loss_cp: int = MAX_LOSS_CP) -> dict:
    """Compares the book move and the played move in one search (both as root moves).

    Returns acceptable, loss_cp (book minus played, for the player to move),
    book_cp and played_cp. A move the engine did not score is not acceptable.
    """
    board = chess.Board(fen)
    book, played = chess.Move.from_uci(book_uci), chess.Move.from_uci(played_uci)
    infos = engine.analyse(board, chess.engine.Limit(time=time_limit), multipv=2, root_moves=[book, played])
    scores = {}
    for info in infos:
        pv = info.get("pv")
        if pv and "score" in info:
            scores[pv[0]] = _cp(info["score"], board.turn)
    if book not in scores or played not in scores:
        return {"acceptable": False, "loss_cp": None, "book_cp": scores.get(book), "played_cp": scores.get(played)}
    loss = scores[book] - scores[played]
    return {"acceptable": loss <= max_loss_cp, "loss_cp": loss, "book_cp": scores[book], "played_cp": scores[played]}


def engine_opinion(engine, fen: str, book_uci: str, time_limit: float = 0.5,
                   max_loss_cp: int = MAX_LOSS_CP) -> dict:
    """The engine's view of one lesson position: best move, best line (SAN) and both
    scores. agrees is True when the best move is the book move or close enough."""
    board = chess.Board(fen)
    book = chess.Move.from_uci(book_uci)
    limit = chess.engine.Limit(time=time_limit)
    best_info = engine.analyse(board, limit)
    pv = best_info.get("pv") or [book]
    best = pv[0]
    best_cp = _cp(best_info["score"], board.turn)
    if best == book:
        book_cp = best_cp
    else:
        book_cp = _cp(engine.analyse(board, limit, root_moves=[book])["score"], board.turn)
    return {
        "best_uci": best.uci(),
        "best_san": board.san(best),
        "line_san": board.variation_san(pv[:6]),
        "best_cp": best_cp,
        "book_cp": book_cp,
        "agrees": best == book or best_cp - book_cp <= max_loss_cp,
    }


def pawns(cp: int | None) -> str:
    """Centipawns as pawns for the player: 35 -> '+0.35', a mate -> 'mate' / '-mate'."""
    if cp is None:
        return "?"
    if abs(cp) >= MATE_SCORE - 1000:
        return "mate" if cp > 0 else "-mate"
    return f"{cp / 100:+.2f}"


class EngineAssistant:
    """Thread-safe access to the app's Stockfish for the lesson screens.

    get_engine     - returns the app's chess.engine.SimpleEngine, or None
    lock           - the app's engine lock (the Engine & Board screen uses it too)
    get_time_limit - seconds per analysis (the user's engine_time_limit; clamped)
    """

    def __init__(self, get_engine, lock, get_time_limit=lambda: 0.5):
        self.get_engine = get_engine
        self.lock = lock
        self.get_time_limit = get_time_limit

    @property
    def available(self) -> bool:
        return self.get_engine() is not None

    def judge(self, fen: str, book_uci: str, played_uci: str) -> dict | None:
        """judge_alternative() with the app's engine; None without an engine or if it fails."""
        return self._run(judge_alternative, fen, book_uci, played_uci)

    def opinion(self, fen: str, book_uci: str) -> dict | None:
        """engine_opinion() with the app's engine; None without an engine or if it fails."""
        return self._run(engine_opinion, fen, book_uci)

    def _run(self, function, *args):
        with self.lock:
            engine = self.get_engine()
            if engine is None:
                return None
            try:
                return function(engine, *args, time_limit=self._time_limit())
            except Exception as exc:  # a crashed engine must never stop a lesson
                print(f"[ChessCoach] Engine analysis failed: {exc}")
                return None

    def _time_limit(self) -> float:
        try:
            return min(max(float(self.get_time_limit()), MIN_TIME), MAX_TIME)
        except (TypeError, ValueError):
            return 0.5
