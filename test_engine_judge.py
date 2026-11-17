#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for engine_judge.py. Run from the project folder:

    python -m unittest test_engine_judge -v

Most tests use a fake engine with fixed scores, so they are fast and need no
Stockfish. RealStockfishTests run only when a Stockfish binary is in the
project folder.
"""

import contextlib
import glob
import io
import os
import threading
import unittest

import chess
import chess.engine

from engine_judge import (MATE_SCORE, EngineAssistant, built_for_other_processor, engine_opinion,
                          judge_alternative, pawns)
from level_trainer import load_level_chapter

PROJECT = os.path.dirname(os.path.abspath(__file__))
AFTER_D4 = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1"


class FakeEngine:
    """analyse() answers from a table {uci: centipawns for White}, best move first."""

    def __init__(self, white_cp: dict, fail: bool = False):
        self.white_cp = white_cp
        self.fail = fail
        self.calls = []

    def analyse(self, board, limit, multipv=None, root_moves=None):
        self.calls.append({"time": limit.time, "multipv": multipv, "root_moves": root_moves})
        if self.fail:
            raise chess.engine.EngineTerminatedError("engine died")
        moves = root_moves or [chess.Move.from_uci(uci) for uci in self.white_cp]
        sign = 1 if board.turn == chess.WHITE else -1
        moves = sorted(moves, key=lambda m: -sign * self.white_cp[m.uci()])  # best for the side to move first
        infos = [{"pv": [m], "score": chess.engine.PovScore(chess.engine.Cp(self.white_cp[m.uci()]), chess.WHITE)}
                 for m in moves]
        return infos if multipv else infos[0]


class JudgeTests(unittest.TestCase):
    def test_small_loss_is_acceptable(self):
        engine = FakeEngine({"d2d4": 40, "g1f3": 0})
        verdict = judge_alternative(engine, chess.STARTING_FEN, "d2d4", "g1f3")
        self.assertEqual(verdict, {"acceptable": True, "loss_cp": 40, "book_cp": 40, "played_cp": 0})
        self.assertEqual(engine.calls[0]["multipv"], 2)  # one search for both moves
        self.assertEqual([m.uci() for m in engine.calls[0]["root_moves"]], ["d2d4", "g1f3"])

    def test_bigger_loss_is_a_mistake(self):
        verdict = judge_alternative(FakeEngine({"d2d4": 40, "g2g4": -20}), chess.STARTING_FEN, "d2d4", "g2g4")
        self.assertEqual((verdict["acceptable"], verdict["loss_cp"]), (False, 60))

    def test_a_better_move_is_acceptable(self):
        verdict = judge_alternative(FakeEngine({"d2d4": 10, "e2e4": 30}), chess.STARTING_FEN, "d2d4", "e2e4")
        self.assertEqual((verdict["acceptable"], verdict["loss_cp"]), (True, -20))

    def test_scores_are_seen_from_the_side_to_move(self):
        # Black to move: +0.20 for White after ...Nf6 is -0.20 for Black, +0.90 after ...h6 is -0.90.
        verdict = judge_alternative(FakeEngine({"g8f6": 20, "h7h6": 90}), AFTER_D4, "g8f6", "h7h6")
        self.assertEqual((verdict["book_cp"], verdict["played_cp"], verdict["acceptable"]), (-20, -90, False))

    def test_unscored_move_is_not_acceptable(self):
        class Silent(FakeEngine):
            def analyse(self, board, limit, multipv=None, root_moves=None):
                return [{"pv": [root_moves[0]], "score": chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE)}]
        verdict = judge_alternative(Silent({}), chess.STARTING_FEN, "d2d4", "g1f3")
        self.assertFalse(verdict["acceptable"])


class OpinionTests(unittest.TestCase):
    def test_engine_agrees_with_the_book(self):
        opinion = engine_opinion(FakeEngine({"d2d4": 30, "e2e4": 25}), chess.STARTING_FEN, "d2d4")
        self.assertEqual((opinion["best_san"], opinion["book_cp"], opinion["agrees"]), ("d4", 30, True))

    def test_engine_prefers_another_move(self):
        engine = FakeEngine({"e2e4": 90, "d2d4": 20})
        opinion = engine_opinion(engine, chess.STARTING_FEN, "d2d4")
        self.assertEqual((opinion["best_san"], opinion["best_cp"], opinion["book_cp"], opinion["agrees"]),
                         ("e4", 90, 20, False))
        self.assertEqual(opinion["line_san"], "1. e4")
        self.assertEqual([m.uci() for m in engine.calls[1]["root_moves"]], ["d2d4"])  # book move scored separately

    def test_pawns(self):
        self.assertEqual([pawns(35), pawns(-120), pawns(0), pawns(None)], ["+0.35", "-1.20", "+0.00", "?"])
        self.assertEqual((pawns(MATE_SCORE), pawns(-MATE_SCORE)), ("mate", "-mate"))


class AssistantTests(unittest.TestCase):
    def test_without_an_engine_nothing_is_judged(self):
        assistant = EngineAssistant(lambda: None, threading.Lock())
        self.assertFalse(assistant.available)
        self.assertIsNone(assistant.judge(chess.STARTING_FEN, "d2d4", "g1f3"))
        self.assertIsNone(assistant.opinion(chess.STARTING_FEN, "d2d4"))

    def test_uses_the_engine_with_a_clamped_time_limit(self):
        engine = FakeEngine({"d2d4": 40, "g1f3": 0})
        assistant = EngineAssistant(lambda: engine, threading.Lock(), lambda: 30)
        self.assertTrue(assistant.available)
        self.assertTrue(assistant.judge(chess.STARTING_FEN, "d2d4", "g1f3")["acceptable"])
        self.assertEqual(engine.calls[0]["time"], 2.0)  # 30 s would freeze a quiz: capped

    def test_a_failing_engine_returns_none_and_frees_the_lock(self):
        lock = threading.Lock()
        assistant = EngineAssistant(lambda: FakeEngine({}, fail=True), lock)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.assertIsNone(assistant.judge(chess.STARTING_FEN, "d2d4", "g1f3"))
        self.assertFalse(lock.locked())
        self.assertIn("Engine analysis failed", printed.getvalue())


class ProcessorTests(unittest.TestCase):
    """The app starts the first Stockfish file that works; other processors' builds are tried last."""

    def test_on_an_x86_64_pc_arm_builds_go_last(self):
        self.assertTrue(built_for_other_processor(r"stockfish\stockfish-windows-arm64-universal.exe", "AMD64"))
        self.assertFalse(built_for_other_processor("stockfish-windows-x86-64-universal.exe", "AMD64"))
        self.assertFalse(built_for_other_processor("stockfish.exe", "AMD64"))  # no tag: fine

    def test_on_an_arm_pc_x86_builds_go_last(self):
        self.assertTrue(built_for_other_processor("stockfish-windows-x86-64-avx2.exe", "ARM64"))
        self.assertFalse(built_for_other_processor("stockfish-windows-armv8.exe", "ARM64"))
        self.assertFalse(built_for_other_processor("stockfish-windows-arm64-universal.exe", "riscv64"))  # unknown PC


STOCKFISH = sorted(glob.glob(os.path.join(PROJECT, "stockfish*", "**", "*x86-64*.exe"), recursive=True))


@unittest.skipUnless(STOCKFISH, "no Stockfish binary in the project folder")
class RealStockfishTests(unittest.TestCase):
    """The real engine on chapter 1, level 5: before 13.Nd6 (book) the engine also likes 13.Qe4."""

    @classmethod
    def setUpClass(cls):
        cls.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH[0])
        main = load_level_chapter(os.path.join(PROJECT, "catalan_ch01_v2.json"))["lines"]["main"]
        cls.step = next(step for step in main if step["san"] == "Nd6")

    @classmethod
    def tearDownClass(cls):
        cls.engine.quit()

    def test_a_good_alternative_is_accepted(self):
        verdict = judge_alternative(self.engine, self.step["fen_before"], self.step["uci"], "c2e4", time_limit=0.5)
        self.assertTrue(verdict["acceptable"], verdict)

    def test_a_blunder_is_a_mistake(self):
        verdict = judge_alternative(self.engine, self.step["fen_before"], self.step["uci"], "c2h7", time_limit=0.5)
        self.assertFalse(verdict["acceptable"], verdict)  # 13.Qxh7+?? gives the queen away
        self.assertGreater(verdict["loss_cp"], 500)


if __name__ == "__main__":
    unittest.main()
