#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for level_trainer.py. Run from the project folder:

    python -m unittest test_level_trainer -v

Most tests build small chapters in memory; some load the real
catalan_ch01_v2.json so the shipped chapter is checked too. The database test
uses a throw-away database in a temporary folder, never chesscoach.db.
"""

import copy
import os
import tempfile
import unittest

import chess

from database import ChessCoachDB
from level_trainer import (
    ChapterFormatError,
    LevelSession,
    level_line_id,
    load_level_chapter,
    summarize_chapter,
    summarize_levels,
    validate_level_chapter,
)

REAL_CHAPTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalan_ch01_v2.json")

QUIZ_RULES = [
    {"wrong_attempt": 1, "action": "show_hint", "review_days": [1, 7]},
    {"wrong_attempt": 2, "action": "show_correct_move", "review_days": [1, 3, 7]},
]

# 1.d4 Nf6 2.c4 e6 3.g3 d5 -> a quiz over this line asks 3 White questions.
SANS = ("d4", "Nf6", "c4", "e6", "g3", "d5")


def make_moves(sans=SANS):
    board = chess.Board()
    moves = []
    for ply, san in enumerate(sans, start=1):
        white = board.turn == chess.WHITE
        moves.append({
            "ply": ply,
            "move_number": board.fullmove_number,
            "turn": "white" if white else "black",
            "san": san,
            "strategic_idea": f"idea {ply}",
            "explanation": f"explanation {ply}",
            "hint": f"hint {ply}" if white else None,
        })
        board.push_san(san)
    return moves


def quiz_level(number, from_ply, to_ply):
    return {
        "level": number, "type": "quiz", "title": f"Quiz {number}", "line_id": "main",
        "from_ply": from_ply, "to_ply": to_ply, "question_type": "play_move",
        "show_explanations": False, "on_mistake": copy.deepcopy(QUIZ_RULES),
    }


def learn_level(number, from_ply, to_ply):
    return {"level": number, "type": "learn", "title": f"Learn {number}", "line_id": "main",
            "from_ply": from_ply, "to_ply": to_ply}


def make_chapter(levels=None, sans=SANS):
    """A small valid format-2 chapter (not validated yet)."""
    if levels is None:
        levels = [learn_level(1, 1, len(sans)), quiz_level(2, 1, len(sans)), learn_level(3, 1, len(sans))]
    return {
        "format_version": 2,
        "chapter_meta": {"chapter_id": "test_ch", "chapter_title": "Test chapter",
                         "player_color": "white", "min_accuracy_to_pass": 85},
        "lines": {"main": make_moves(sans)},
        "levels": levels,
    }


def answer(session, wrong_moves=()):
    """Plays the given wrong moves (UCI) at the current question, then the right one."""
    for uci in wrong_moves:
        result = session.submit_move(uci)
        assert result["status"] == "incorrect", result
    return session.submit_move(session.current_question["uci"])


class ValidationTests(unittest.TestCase):
    def test_real_chapter_is_valid(self):
        chapter = load_level_chapter(REAL_CHAPTER_PATH)
        main = chapter["lines"]["main"]
        for step in main:
            self.assertIn("uci", step)
            self.assertIn("fen_after", step)
        # Level 1 ends with 9.e4 (ply 17) in the 6...c6 / 8.Nbd2 setup.
        self.assertEqual(main[16]["san"], "e4")
        self.assertEqual(main[16]["fen_after"].split()[0],
                         "r1bq1rk1/p2nbppp/1pp1pn2/3p4/2PPP3/5NP1/PPQN1PBP/R1B2RK1")
        for level in chapter["levels"]:  # every level must start without errors
            LevelSession(chapter, level["level"])

    def test_adds_fen_and_uci(self):
        chapter = validate_level_chapter(make_chapter())
        first, last = chapter["lines"]["main"][0], chapter["lines"]["main"][-1]
        self.assertEqual(first["uci"], "d2d4")
        self.assertEqual(first["fen_before"], chess.STARTING_FEN)
        board = chess.Board()
        for san in SANS:
            board.push_san(san)
        self.assertEqual(last["fen_after"], board.fen())

    def test_missing_text_fields_become_none(self):
        data = make_chapter()
        del data["lines"]["main"][0]["hint"]
        del data["lines"]["main"][0]["explanation"]
        step = validate_level_chapter(data)["lines"]["main"][0]
        self.assertIsNone(step["hint"])
        self.assertIsNone(step["explanation"])

    def test_rejects_illegal_move(self):
        data = make_chapter()
        data["lines"]["main"][2]["san"] = "Nf6"  # no White knight can reach f6
        with self.assertRaisesRegex(ChapterFormatError, "ply 3"):
            validate_level_chapter(data)

    def test_rejects_broken_move_fields(self):
        cases = {
            "wrong ply": lambda d: d["lines"]["main"][1].update(ply=5),
            "wrong turn": lambda d: d["lines"]["main"][1].update(turn="white"),
            "wrong move number": lambda d: d["lines"]["main"][2].update(move_number=3),
            "missing san": lambda d: d["lines"]["main"][0].pop("san"),
            "empty line": lambda d: d["lines"].update(main=[]),
            "old format": lambda d: d.update(format_version=1),
            "bad colour": lambda d: d["chapter_meta"].update(player_color="red"),
            "bad pass mark": lambda d: d["chapter_meta"].update(min_accuracy_to_pass=120),
            "negative allowed mistakes": lambda d: d["chapter_meta"].update(allowed_mistakes=-1),
            "allowed mistakes as text": lambda d: d["chapter_meta"].update(allowed_mistakes="1"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                data = make_chapter()
                mutate(data)
                with self.assertRaises(ChapterFormatError):
                    validate_level_chapter(data)

    def test_rejects_broken_levels(self):
        def set_level(index, **fields):
            return lambda d: d["levels"][index].update(**fields)

        def set_rule(index, **fields):
            return lambda d: d["levels"][1]["on_mistake"][index].update(**fields)

        cases = {
            "numbering gap": set_level(1, level=3),
            "unknown type": set_level(0, type="exam"),
            "missing title": set_level(0, title=""),
            "unknown line": set_level(0, line_id="side"),
            "to_ply too far": set_level(0, to_ply=99),
            "from_ply zero": set_level(0, from_ply=0),
            "from after to": set_level(0, from_ply=4, to_ply=2),
            "unknown question type": set_level(1, question_type="multiple_choice"),
            "quiz without rules": set_level(1, on_mistake=[]),
            "quiz without White move": set_level(1, from_ply=2, to_ply=2),
            "rule out of order": set_rule(0, wrong_attempt=2),
            "unknown action": set_rule(0, action="explain_again"),
            "days not increasing": set_rule(1, review_days=[7, 1]),
            "day zero": set_rule(0, review_days=[0, 7]),
            "no days": set_rule(0, review_days=[]),
            "no levels": lambda d: d.update(levels=[]),
            "key ideas not a list": set_level(0, key_ideas="Play e4."),
            "empty key idea": set_level(0, key_ideas=["Play e4.", " "]),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                data = make_chapter()
                mutate(data)
                with self.assertRaises(ChapterFormatError):
                    validate_level_chapter(data)


class LearnTests(unittest.TestCase):
    def setUp(self):
        self.chapter = validate_level_chapter(make_chapter())
        self.session = LevelSession(self.chapter, 1)

    def test_starts_before_the_first_move(self):
        self.assertEqual(self.session.fen, chess.STARTING_FEN)
        self.assertIsNone(self.session.current_step)
        self.assertEqual((self.session.step_index, self.session.step_count), (0, 6))
        self.assertFalse(self.session.is_complete)
        self.assertTrue(self.session.show_explanations)

    def test_next_and_back(self):
        step = self.session.next_step()
        self.assertEqual(step["san"], "d4")
        self.assertEqual(self.session.fen, step["fen_after"])
        self.assertIsNone(self.session.previous_step())
        self.assertEqual(self.session.fen, chess.STARTING_FEN)
        self.assertIsNone(self.session.previous_step())  # stays at the start
        self.assertEqual(self.session.step_index, 0)

    def test_finishing_passes_the_level(self):
        while self.session.next_step() is not None:
            pass
        self.assertTrue(self.session.is_complete)
        self.assertTrue(self.session.passed)
        self.assertEqual(self.session.current_step["san"], "d5")
        self.assertIsNone(self.session.next_step())

    def test_level_can_start_in_the_middle_of_a_line(self):
        chapter = validate_level_chapter(make_chapter(levels=[learn_level(1, 3, 6)]))
        session = LevelSession(chapter, 1)
        self.assertEqual(session.fen, chapter["lines"]["main"][1]["fen_after"])
        self.assertEqual(session.next_step()["san"], "c4")

    def test_quiz_methods_are_refused(self):
        with self.assertRaises(RuntimeError):
            self.session.submit_move("d2d4")

    def test_unknown_level_number(self):
        with self.assertRaises(ValueError):
            LevelSession(self.chapter, 4)


class QuizTests(unittest.TestCase):
    def setUp(self):
        self.chapter = validate_level_chapter(make_chapter())
        self.session = LevelSession(self.chapter, 2)

    def test_first_question(self):
        self.assertEqual(self.session.question_count, 3)
        self.assertEqual(self.session.current_question["san"], "d4")
        self.assertEqual(self.session.question_states(), ["current", "pending", "pending"])
        self.assertFalse(self.session.show_explanations)

    def test_correct_answer_plays_the_reply(self):
        result = self.session.submit_move("d2d4")
        self.assertEqual(result["status"], "correct")
        self.assertTrue(result["first_try"])
        self.assertEqual([m["san"] for m in result["opponent_moves"]], ["Nf6"])
        self.assertEqual(self.session.fen, self.chapter["lines"]["main"][1]["fen_after"])
        self.assertEqual(self.session.current_question["san"], "c4")

    def test_san_input_is_accepted(self):
        self.assertEqual(self.session.submit_move("d4")["status"], "correct")

    def test_input_with_bom_and_spaces_is_accepted(self):
        self.assertEqual(self.session.submit_move("﻿ d2d4 ")["status"], "correct")

    def test_first_mistake_shows_the_hint(self):
        result = self.session.submit_move("e2e4")
        self.assertEqual(result["status"], "incorrect")
        self.assertEqual((result["action"], result["hint"]), ("show_hint", "hint 1"))
        self.assertEqual(result["played_san"], "e4")
        self.assertEqual(result["review_days"], [1, 7])
        self.assertIsNone(result["correct_san"])
        self.assertEqual(self.session.fen, chess.STARTING_FEN)  # the board does not change

    def test_second_mistake_shows_the_correct_move(self):
        self.session.submit_move("e2e4")
        result = self.session.submit_move("c2c4")
        self.assertEqual(result["action"], "show_correct_move")
        self.assertEqual((result["correct_san"], result["correct_uci"]), ("d4", "d2d4"))
        self.assertEqual(result["review_days"], [1, 3, 7])
        self.assertIsNone(result["hint"])

    def test_later_mistakes_repeat_the_last_rule(self):
        for uci in ("e2e4", "c2c4", "g1f3"):
            result = self.session.submit_move(uci)
        self.assertEqual((result["wrong_attempt"], result["action"]), (3, "show_correct_move"))

    def test_illegal_move_is_not_a_mistake(self):
        self.assertEqual(self.session.submit_move("a1a5")["status"], "illegal")
        self.assertEqual(self.session.submit_move("nonsense")["status"], "illegal")
        self.assertTrue(self.session.submit_move("d2d4")["first_try"])

    def test_perfect_run(self):
        while not self.session.is_complete:
            answer(self.session)
        self.assertEqual(self.session.accuracy, 100.0)
        self.assertTrue(self.session.passed)
        self.assertEqual(self.session.review_items(), [])
        self.assertEqual(self.session.question_states(), ["ok", "ok", "ok"])
        self.assertEqual(self.session.submit_move("d2d4")["status"], "complete")

    def test_scores_states_and_review_list(self):
        answer(self.session)                          # 1.d4 first try
        answer(self.session, ["b1c3"])                # 2.c4 after the hint
        self.assertEqual(self.session.question_states(), ["ok", "hint", "current"])
        result = answer(self.session, ["b1c3", "g1f3"])  # 3.g3 after the correct move was shown
        self.assertFalse(result["first_try"])
        self.assertTrue(self.session.is_complete)
        self.assertEqual(self.session.question_states(), ["ok", "hint", "shown"])
        self.assertEqual(self.session.accuracy, 33.3)
        self.assertFalse(self.session.passed)
        review = [(item["san"], item["wrong_attempts"], item["review_days"]) for item in self.session.review_items()]
        self.assertEqual(review, [("c4", 1, [1, 7]), ("g3", 2, [1, 3, 7])])

    def test_restart(self):
        answer(self.session, ["e2e4"])
        self.session.restart()
        self.assertEqual(self.session.fen, chess.STARTING_FEN)
        self.assertEqual(self.session.accuracy, 100.0)
        self.assertEqual(self.session.review_items(), [])
        self.assertEqual(self.session.question_states(), ["current", "pending", "pending"])

    def test_quiz_starting_with_an_opponent_move(self):
        chapter = validate_level_chapter(make_chapter(levels=[quiz_level(1, 2, 6)]))
        session = LevelSession(chapter, 1)
        self.assertEqual(session.current_question["san"], "c4")  # 1...Nf6 was played automatically
        self.assertEqual([m["san"] for m in session.restart()], ["Nf6"])
        self.assertEqual(session.question_count, 2)

    def test_learn_methods_are_refused(self):
        with self.assertRaises(RuntimeError):
            self.session.next_step()


class RetryTests(unittest.TestCase):
    """Quiz levels with "retry_mistakes": missed positions come back at the end."""

    def setUp(self):
        level = quiz_level(1, 1, len(SANS))
        level["retry_mistakes"] = True
        self.chapter = validate_level_chapter(make_chapter(levels=[level]))
        self.session = LevelSession(self.chapter, 1)
        self.main_line = self.chapter["lines"]["main"]

    def test_no_mistakes_means_no_second_chance(self):
        while not self.session.is_complete:
            answer(self.session)
        self.assertFalse(self.session.in_retry)
        self.assertEqual(self.session.retry_queue, [])

    def test_missed_position_comes_back_at_the_end(self):
        answer(self.session)                    # 1.d4
        answer(self.session, ["b1c3"])          # 2.c4 after the hint
        result = answer(self.session)           # 3.g3 ends the first pass
        self.assertTrue(result["starts_retry"])
        self.assertTrue(self.session.in_retry)
        self.assertFalse(self.session.is_complete)
        self.assertEqual(self.session.current_question["san"], "c4")
        self.assertEqual(self.session.fen, self.main_line[2]["fen_before"])
        self.assertEqual(self.session.last_move["san"], "Nf6")
        result = self.session.submit_move("c2c4")
        self.assertTrue(result["retry"] and result["first_try"])
        self.assertEqual(result["opponent_moves"], [])
        self.assertTrue(self.session.is_complete)
        self.assertEqual(self.session.accuracy, 66.7)  # only the first pass counts
        self.assertEqual([(i["san"], i["fixed"]) for i in self.session.review_items()], [("c4", True)])

    def test_mistake_in_the_second_chance(self):
        answer(self.session, ["e2e4"])          # 1.d4 after the hint
        answer(self.session)
        answer(self.session)
        result = self.session.submit_move("e2e4")
        self.assertTrue(result["retry"])
        self.assertEqual((result["status"], result["action"]), ("incorrect", "show_hint"))
        self.assertTrue(self.session.in_retry)
        self.session.submit_move("d2d4")
        self.assertTrue(self.session.is_complete)
        self.assertEqual(self.session.review_items()[0]["fixed"], False)
        self.assertEqual(self.session.review_items()[0]["review_days"], [1, 7])  # from the first pass

    def test_question_states_during_the_second_chance(self):
        answer(self.session, ["e2e4"])
        answer(self.session)
        answer(self.session)
        self.assertEqual(self.session.question_states(), ["hint", "ok", "ok"])

    def test_restart_clears_the_second_chance(self):
        answer(self.session, ["e2e4"])
        answer(self.session)
        answer(self.session)
        self.session.restart()
        self.assertFalse(self.session.in_retry)
        self.assertEqual(self.session.current_question["san"], "d4")

    def test_retry_flag_must_be_true_or_false(self):
        data = make_chapter()
        data["levels"][1]["retry_mistakes"] = "yes"
        with self.assertRaises(ChapterFormatError):
            validate_level_chapter(data)


class ShortQuizTests(unittest.TestCase):
    """chapter_meta.allowed_mistakes = 1: one first-try mistake always passes a quiz."""

    def setUp(self):
        data = make_chapter()
        data["chapter_meta"]["allowed_mistakes"] = 1
        self.chapter = validate_level_chapter(data)

    def test_one_mistake_passes_a_short_quiz(self):
        session = LevelSession(self.chapter, 2)  # 3 questions
        self.assertEqual(session.pass_mark, 66.7)
        answer(session, ["e2e4"])
        answer(session)
        answer(session)
        self.assertEqual((session.accuracy, session.mistake_count), (66.7, 1))
        self.assertTrue(session.passed)

    def test_two_mistakes_still_fail(self):
        session = LevelSession(self.chapter, 2)
        answer(session, ["e2e4"])
        answer(session, ["b1c3"])
        answer(session)
        self.assertFalse(session.passed)

    def test_a_one_question_quiz_still_needs_the_right_move(self):
        data = make_chapter(levels=[quiz_level(1, 1, 2)])
        data["chapter_meta"]["allowed_mistakes"] = 1
        session = LevelSession(validate_level_chapter(data), 1)
        self.assertEqual(session.pass_mark, 85)
        answer(session, ["e2e4"])
        self.assertFalse(session.passed)

    def test_level_summary_uses_the_same_rule(self):
        def row(accuracy=None):
            return {"times_completed": 1, "best_accuracy": accuracy, "last_played_at": "2026-11-17T12:00:00Z"}

        summary = summarize_levels(self.chapter, {"level_1": row(), "level_2": row(66.7)})
        self.assertTrue(summary[1]["passed"] and summary[2]["unlocked"])
        summary = summarize_levels(self.chapter, {"level_1": row(), "level_2": row(33.3)})
        self.assertFalse(summary[1]["passed"] or summary[2]["unlocked"])


class RealChapterQuizTests(unittest.TestCase):
    """Level 2 of catalan_ch01_v2.json: 9 questions, pass mark 85%."""

    def setUp(self):
        self.chapter = load_level_chapter(REAL_CHAPTER_PATH)
        self.session = LevelSession(self.chapter, 2)

    def play(self, mistakes):
        """mistakes: {ply: [wrong UCI moves]}; every other question is answered at once."""
        while not self.session.is_complete:
            answer(self.session, mistakes.get(self.session.current_question["ply"], []))

    def test_one_mistake_still_passes(self):
        self.assertEqual(self.session.question_count, 9)
        self.assertEqual(self.session.pass_mark, 85)  # a long quiz keeps the chapter's mark
        self.play({15: ["f1d1"]})  # 8.Rd1 instead of 8.Nbd2
        self.assertEqual(self.session.accuracy, 88.9)
        self.assertTrue(self.session.passed)

    def test_two_mistakes_fail(self):
        self.play({13: ["d1d3"], 15: ["f1d1", "b1c3"]})
        self.assertEqual(self.session.accuracy, 77.8)
        self.assertFalse(self.session.passed)
        days = {item["san"]: item["review_days"] for item in self.session.review_items()}
        self.assertEqual(days, {"Qc2": [1, 7], "Nbd2": [1, 3, 7]})

    def test_level_6_allows_one_mistake(self):
        session = LevelSession(self.chapter, 6)
        self.assertEqual(session.question_count, 3)
        while not session.is_complete:
            question = session.current_question
            first_pass_nd6 = question["san"] == "Nd6" and not session.in_retry
            answer(session, ["d4c5"] if first_pass_nd6 else [])
        self.assertEqual(session.accuracy, 66.7)
        self.assertTrue(session.passed)

    def test_level_8_quizzes_the_second_line(self):
        session = LevelSession(self.chapter, 8)
        self.assertEqual(session.level["line_id"], "line_2")
        self.assertEqual(session.last_move["san"], "b6")  # 7...b6 is played for the player
        self.assertEqual((session.question_count, session.pass_mark), (6, 83.3))
        while not session.is_complete:
            question = session.current_question
            answer(session, ["f1d1"] if question["san"] == "Nbd2" and not session.in_retry else [])
        self.assertEqual(session.accuracy, 83.3)  # 5 of 6: one mistake still passes
        self.assertTrue(session.passed)

    def test_hint_comes_from_the_chapter(self):
        while self.session.current_question["ply"] != 15:
            answer(self.session)
        result = self.session.submit_move("f1d1")
        self.assertEqual(result["hint"], self.chapter["lines"]["main"][14]["hint"])


class LevelSummaryTests(unittest.TestCase):
    def setUp(self):
        self.chapter = validate_level_chapter(make_chapter())

    @staticmethod
    def row(times_completed=1, best_accuracy=None):
        return {"times_completed": times_completed, "best_accuracy": best_accuracy,
                "last_played_at": "2026-11-17T12:00:00Z"}

    def unlocked(self, rows, extra_passed=frozenset()):
        return [lvl["unlocked"] for lvl in summarize_levels(self.chapter, rows, extra_passed)]

    def test_new_player_sees_only_level_1(self):
        self.assertEqual(self.unlocked({}), [True, False, False])

    def test_finished_learn_level_opens_the_quiz(self):
        self.assertEqual(self.unlocked({"level_1": self.row()}), [True, True, False])

    def test_quiz_below_the_pass_mark_keeps_the_next_level_locked(self):
        rows = {"level_1": self.row(), "level_2": self.row(best_accuracy=80.0)}
        self.assertEqual(self.unlocked(rows), [True, True, False])

    def test_passed_quiz_opens_the_next_level(self):
        rows = {"level_1": self.row(), "level_2": self.row(best_accuracy=88.9)}
        summary = summarize_levels(self.chapter, rows)
        self.assertEqual([lvl["unlocked"] for lvl in summary], [True, True, True])
        self.assertEqual(summary[1]["best_accuracy"], 88.9)

    def test_guest_progress_in_this_session(self):
        self.assertEqual(self.unlocked({}, extra_passed={1}), [True, True, False])

    def test_level_line_id(self):
        self.assertEqual(level_line_id(2), "level_2")

    def test_chapter_summary_for_the_hub(self):
        def status(rows, extra=frozenset()):
            summary = summarize_chapter(self.chapter, rows, extra)
            return summary["status"], summary["percent"], summary["levels_passed"]

        self.assertEqual(status({}), ("not_started", 0, 0))
        self.assertEqual(status({"level_1": self.row()}), ("in_progress", 33, 1))
        self.assertEqual(status({"level_1": self.row(), "level_2": self.row(best_accuracy=50.0)}),
                         ("in_progress", 33, 1))  # a failed quiz is still "in progress"
        everything = {"level_1": self.row(), "level_2": self.row(best_accuracy=100.0), "level_3": self.row()}
        self.assertEqual(status(everything), ("completed", 100, 3))
        self.assertEqual(status({}, extra={1}), ("in_progress", 33, 1))  # a Guest in this session


class DatabaseIntegrationTest(unittest.TestCase):
    """Level results fit the existing line_progress table without a schema change."""

    def test_saved_quiz_result_opens_the_next_level(self):
        with tempfile.TemporaryDirectory() as folder:
            db = ChessCoachDB(os.path.join(folder, "chesscoach.db"))
            db.create_user("tester")
            chapter = validate_level_chapter(make_chapter())
            chapter_id = chapter["chapter_meta"]["chapter_id"]
            self.assertTrue(db.save_line_result(chapter_id, level_line_id(1)))
            self.assertTrue(db.save_line_result(chapter_id, level_line_id(2), 88.9))
            summary = summarize_levels(chapter, db.get_chapter_progress(chapter_id))
            self.assertEqual([lvl["passed"] for lvl in summary], [True, True, False])
            self.assertTrue(summary[2]["unlocked"])


if __name__ == "__main__":
    unittest.main()
