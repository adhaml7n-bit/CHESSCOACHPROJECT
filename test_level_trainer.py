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
import random
import tempfile
import unittest

import chess

from database import ChessCoachDB
from level_trainer import (
    ChapterFormatError,
    LevelSession,
    ReviewSession,
    asks_purpose,
    build_review_items,
    question_count,
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

    def test_purpose_questions_are_optional(self):
        data = make_chapter()
        data["lines"]["main"][2]["purpose"] = {"answer": "right idea", "wrong": ["wrong idea 1", "wrong idea 2"]}
        main = validate_level_chapter(data)["lines"]["main"]
        self.assertEqual((main[2]["purpose"]["answer"], main[0]["purpose"]), ("right idea", None))

    def test_rejects_broken_purpose_questions(self):
        cases = {
            "not an object": "right idea",
            "no answer": {"wrong": ["a", "b"]},
            "empty answer": {"answer": " ", "wrong": ["a"]},
            "no wrong answers": {"answer": "right", "wrong": []},
            "wrong answers as text": {"answer": "right", "wrong": "a"},
            "the same answer twice": {"answer": "Right", "wrong": ["right "]},
        }
        for name, purpose in cases.items():
            with self.subTest(name):
                data = make_chapter()
                data["lines"]["main"][0]["purpose"] = purpose
                with self.assertRaisesRegex(ChapterFormatError, "ply 1"):
                    validate_level_chapter(data)
        data = make_chapter()
        data["lines"]["main"][1]["purpose"] = {"answer": "right", "wrong": ["a"]}  # a Black move
        with self.assertRaisesRegex(ChapterFormatError, "only for white"):
            validate_level_chapter(data)

    def test_lines_share_the_purpose_question_of_a_position(self):
        chapter = load_level_chapter(REAL_CHAPTER_PATH)
        main, line_2 = chapter["lines"]["main"], chapter["lines"]["line_2"]
        self.assertIs(line_2[4]["purpose"], main[4]["purpose"])          # 3.g3: written once, on main
        self.assertNotEqual(line_2[14]["purpose"], main[14]["purpose"])  # 8.Nbd2 in two different positions
        steps = [step for line in chapter["lines"].values() for step in line]  # all 28 lines
        missing = [f"{step['move_number']}.{step['san']}" for step in steps if step["turn"] == "white" and not step["purpose"]]
        self.assertEqual(missing, [])  # every White move has its day-7 question
        self.assertTrue(all(step["purpose"] is None for step in steps if step["turn"] == "black"))

    def test_every_level_of_the_real_chapter_can_be_finished(self):
        chapter = load_level_chapter(REAL_CHAPTER_PATH)
        for level in chapter["levels"]:
            with self.subTest(level=level["level"]):
                session = LevelSession(chapter, level["level"])
                for _ in range(200):
                    if session.is_complete:
                        break
                    if session.kind == "learn":
                        session.next_step()
                    else:
                        self.assertEqual(session.submit_move(session.current_question["uci"])["status"], "correct")
                self.assertTrue(session.is_complete and session.passed)
                if session.kind == "learn":  # every move of a learn level is explained
                    self.assertTrue(all(step["strategic_idea"] for step in session.moves), level["title"])
                else:
                    self.assertEqual(session.accuracy, 100.0)

    def test_a_transposition_in_the_real_chapter_is_explained_once(self):
        lines = load_level_chapter(REAL_CHAPTER_PATH)["lines"]
        # 7...Nbd7 8.Nbd2 b6 9.e4 Bb7 and 7...b6 8.Nbd2 Bb7 9.e4 Nbd7: the same position, so the same texts for 10.e5
        self.assertEqual(lines["nbd7_bb7"][18]["fen_before"].split()[:4], lines["b6_nbd7"][18]["fen_before"].split()[:4])
        self.assertEqual(lines["nbd7_bb7"][18]["explanation"], lines["b6_nbd7"][18]["explanation"])
        self.assertEqual(lines["nbd7_bb7"][18]["hint"], "Push your e-pawn and attack the f6-knight.")
        self.assertIs(lines["nbd7_bb7"][18]["purpose"], lines["b6_nbd7"][18]["purpose"])  # and the same day-7 question

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


def branch(after_ply, sans, parent=SANS):
    """A branch of the main line: its own moves after `after_ply` plies of the parent."""
    own = make_moves(tuple(parent[:after_ply]) + tuple(sans))[after_ply:]
    for step in own:
        step["strategic_idea"] = f"branch idea {step['ply']}"
    return {"from_line": "main", "after_ply": after_ply, "moves": own}


class BranchLineTests(unittest.TestCase):
    """Lines written as branches, texts shared by position, one move per position."""

    def test_a_branch_becomes_a_full_line(self):
        data = make_chapter()
        data["lines"]["g6"] = branch(3, ("g6", "Nc3"))  # 1.d4 Nf6 2.c4 g6 3.Nc3
        lines = validate_level_chapter(data)["lines"]
        self.assertEqual([step["san"] for step in lines["g6"]], ["d4", "Nf6", "c4", "g6", "Nc3"])
        self.assertEqual(lines["g6"][2]["strategic_idea"], "idea 3")       # copied with the parent's texts
        self.assertIsNot(lines["g6"][0], lines["main"][0])                  # copies, not the same objects
        self.assertEqual(lines["g6"][4]["fen_before"].split()[0], "rnbqkb1r/pppppp1p/5np1/8/2PP4/8/PP2PPPP/RNBQKBNR")

    def test_a_branch_of_a_branch(self):
        data = make_chapter()
        data["lines"]["g6"] = branch(3, ("g6", "Nc3"))
        data["lines"]["g6_bg7"] = {"from_line": "g6", "after_ply": 5,
                                   "moves": make_moves(("d4", "Nf6", "c4", "g6", "Nc3", "Bg7"))[5:]}
        lines = validate_level_chapter(data)["lines"]
        self.assertEqual([step["san"] for step in lines["g6_bg7"]][3:], ["g6", "Nc3", "Bg7"])

    def test_rejects_broken_branches(self):
        cases = {
            "unknown parent": {"from_line": "nowhere", "after_ply": 2, "moves": make_moves()[2:3]},
            "after_ply too far": {"from_line": "main", "after_ply": 7, "moves": make_moves()[2:3]},
            "no moves": {"from_line": "main", "after_ply": 2, "moves": []},
            "not an object": "main",
            "wrong ply in its moves": {"from_line": "main", "after_ply": 3, "moves": make_moves()[2:3]},
        }
        for name, spec in cases.items():
            with self.subTest(name):
                data = make_chapter()
                data["lines"]["side"] = spec
                with self.assertRaisesRegex(ChapterFormatError, "side"):
                    validate_level_chapter(data)
        data = make_chapter()
        data["lines"]["a"] = {"from_line": "b", "after_ply": 1, "moves": make_moves()[1:2]}
        data["lines"]["b"] = {"from_line": "a", "after_ply": 1, "moves": make_moves()[1:2]}
        with self.assertRaisesRegex(ChapterFormatError, "branches from itself"):
            validate_level_chapter(data)

    def test_a_transposition_gets_the_texts_of_the_same_position(self):
        data = make_chapter()
        other = make_moves(("d4", "e6", "c4", "Nf6", "g3", "d5"))  # 1...e6 2...Nf6: the same position as main after 2...e6
        for step in other[2:]:
            step["strategic_idea"] = step["explanation"] = step["hint"] = None
        data["lines"]["other"] = other
        lines = validate_level_chapter(data)["lines"]
        self.assertEqual(lines["other"][4]["strategic_idea"], "idea 5")  # 3.g3 explained once, on main
        self.assertIsNone(lines["other"][2]["strategic_idea"])           # 2.c4 here is a different position

    def test_rejects_two_moves_for_the_player_in_one_position(self):
        data = make_chapter()
        data["lines"]["nf3"] = make_moves(("d4", "Nf6", "Nf3", "e6"))  # 2.Nf3 where main plays 2.c4
        with self.assertRaisesRegex(ChapterFormatError, "plays Nf3 where line 'main', ply 3 plays c4"):
            validate_level_chapter(data)


def parts_chapter(learn_parts=None, quiz_parts=None, retry=False):
    """Main line 1.d4 Nf6 2.c4 e6 3.g3 d5 and the branch 2...g6 3.Nc3, with a learn
    level and a quiz level that each cover both lines."""
    data = make_chapter(levels=[])
    data["lines"]["g6"] = branch(3, ("g6", "Nc3"))
    learn_parts = learn_parts or [{"line_id": "main", "from_ply": 4, "to_ply": 6, "intro": "First: 2...e6."},
                                  {"line_id": "g6", "from_ply": 4, "to_ply": 5, "intro": "Now: 2...g6.",
                                   "key_ideas": ["Play e4 next."]}]
    quiz = quiz_level(2, 1, 1)
    for key in ("line_id", "from_ply", "to_ply"):
        del quiz[key]
    quiz["parts"] = quiz_parts or [{"line_id": "main", "from_ply": 4, "to_ply": 6},
                                   {"line_id": "g6", "from_ply": 4, "to_ply": 5}]
    quiz["retry_mistakes"] = retry
    data["levels"] = [{"level": 1, "type": "learn", "title": "Two lines", "parts": learn_parts}, quiz]
    return validate_level_chapter(data)


class PartsTests(unittest.TestCase):
    """Levels that cover several lines one after another."""

    def test_rejects_broken_parts(self):
        def with_parts(parts, **extra):
            data = make_chapter(levels=[])
            data["lines"]["g6"] = branch(3, ("g6", "Nc3"))
            data["levels"] = [{"level": 1, "type": "learn", "title": "x", "parts": parts, **extra}]
            return data

        ok = {"line_id": "main", "from_ply": 1, "to_ply": 2}
        cases = {
            "parts and line_id": with_parts([ok], line_id="main"),
            "empty parts": with_parts([]),
            "unknown line": with_parts([{"line_id": "nope", "from_ply": 1, "to_ply": 2}]),
            "bad range": with_parts([{"line_id": "g6", "from_ply": 3, "to_ply": 9}]),
            "overlap on one line": with_parts([ok, {"line_id": "main", "from_ply": 2, "to_ply": 3}]),
            "empty intro": with_parts([{**ok, "intro": " "}]),
            "bad key ideas": with_parts([{**ok, "key_ideas": "plan"}]),
        }
        for name, data in cases.items():
            with self.subTest(name):
                with self.assertRaises(ChapterFormatError):
                    validate_level_chapter(data)
        validate_level_chapter(with_parts([ok, {"line_id": "g6", "from_ply": 2, "to_ply": 5}]))  # same plies, other line: fine

    def test_learn_level_steps_through_both_lines(self):
        chapter = parts_chapter()
        session = LevelSession(chapter, 1)
        main, g6 = chapter["lines"]["main"], chapter["lines"]["g6"]
        self.assertEqual((session.current_step, session.at_part_start, session.part_index), (None, True, 0))
        self.assertEqual((session.fen, session.step_count, session.current_part["intro"]), (main[3]["fen_before"], 5, "First: 2...e6."))
        self.assertEqual([session.next_step()["san"] for _ in range(3)], ["e6", "g3", "d5"])
        self.assertTrue(session.at_part_end and not session.is_complete)
        self.assertIsNone(session.next_step())  # the start of the second line
        self.assertEqual((session.at_part_start, session.part_index, session.fen, session.last_move, session.step_index),
                         (True, 1, g6[3]["fen_before"], None, 3))
        self.assertEqual(session.current_part["key_ideas"], ["Play e4 next."])
        self.assertEqual([session.next_step()["san"] for _ in range(2)], ["g6", "Nc3"])
        self.assertTrue(session.is_complete and session.at_part_end and session.passed)
        self.assertEqual((session.fen, session.step_index), (g6[4]["fen_after"], 5))
        self.assertIsNone(session.next_step())
        session.previous_step()
        session.previous_step()
        self.assertEqual((session.at_part_start, session.fen), (True, g6[3]["fen_before"]))
        self.assertEqual(session.previous_step()["san"], "d5")  # back across the boundary
        self.assertEqual((session.part_index, session.fen), (0, main[5]["fen_after"]))

    def test_quiz_crosses_to_the_next_line(self):
        chapter = parts_chapter(retry=True)
        main, g6 = chapter["lines"]["main"], chapter["lines"]["g6"]
        session = LevelSession(chapter, 2)
        self.assertEqual((question_count(chapter, chapter["levels"][1]), session.question_count), (2, 2))
        self.assertEqual((session.fen, session.last_move["san"]), (main[3]["fen_after"], "e6"))  # 2...e6 played for you
        wrong = session.submit_move("b1c3")
        self.assertEqual((wrong["status"], wrong["line_id"], wrong["ply"]), ("incorrect", "main", 5))
        result = session.submit_move("g2g3")
        self.assertEqual([step["san"] for step in result["opponent_moves"]], ["d5", "g6"])  # end of line 1, start of line 2
        self.assertEqual((session.part_index, session.fen, session.last_move["san"]), (1, g6[3]["fen_after"], "g6"))
        self.assertEqual(session.question_states(), ["hint", "current"])  # same ply 5 on both lines, counted apart
        result = session.submit_move("b1c3")
        self.assertEqual((result["line_id"], result["first_try"], result["starts_retry"]), ("g6", True, True))
        self.assertEqual((session.in_retry, session.part_index, session.fen), (True, 0, main[4]["fen_before"]))
        self.assertEqual(session.last_move["san"], "e6")
        session.submit_move("g2g3")
        self.assertTrue(session.is_complete)
        self.assertEqual([(i["line_id"], i["ply"], i["fixed"]) for i in session.review_items()], [("main", 5, True)])

    def test_a_line_that_starts_with_your_move(self):
        chapter = parts_chapter(quiz_parts=[{"line_id": "main", "from_ply": 4, "to_ply": 6},
                                            {"line_id": "g6", "from_ply": 5, "to_ply": 5}])
        session = LevelSession(chapter, 2)
        result = session.submit_move("g2g3")
        self.assertEqual([step["san"] for step in result["opponent_moves"]], ["d5"])
        g6 = chapter["lines"]["g6"]
        self.assertEqual((session.fen, session.last_move, session.current_question["san"]), (g6[4]["fen_before"], None, "Nc3"))


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

    def test_peek_classifies_without_counting(self):
        self.assertEqual(self.session.peek("d2d4"), {"status": "correct", "uci": "d2d4"})
        self.assertEqual(self.session.peek("a1a5"), {"status": "illegal"})
        off_book = self.session.peek("e2e4")
        self.assertEqual((off_book["status"], off_book["label"], off_book["book_uci"]), ("off_book", "1. e4", "d2d4"))
        self.assertEqual(off_book["fen"], chess.STARTING_FEN)
        self.assertEqual(self.session.question_states(), ["current", "pending", "pending"])  # nothing counted
        self.assertTrue(self.session.submit_move("d2d4")["first_try"])


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


class ReviewTests(unittest.TestCase):
    """The Daily review: database rows -> questions -> ReviewSession."""

    def setUp(self):
        self.chapter = load_level_chapter(REAL_CHAPTER_PATH)
        self.chapters = {"catalan_ch01_v2": self.chapter}

    def row(self, line_id, ply, chapter_id="catalan_ch01_v2", fen=None):
        if fen is None:
            fen = self.chapter["lines"][line_id][ply - 1]["fen_before"]
        return {"chapter_id": chapter_id, "line_id": line_id, "ply": ply, "fen": fen}

    def test_items_skip_changed_and_unknown_positions(self):
        rows = [
            self.row("main", 15),                                 # 8.Nbd2
            self.row("main", 13),                                 # 7.Qc2 ...
            self.row("line_2", 13),                               # ... the same position on the other branch
            self.row("main", 14),                                 # Black's move: not a question
            self.row("main", 15, chapter_id="catalan_ch01"),      # the old chapter file
            self.row("main", 17, fen="8/8/8/8/8/8/8/8 w - - 0 1"),  # the lesson changed
            self.row("line_9", 3, fen="x"),                       # unknown line
            self.row("main", 99, fen="x"),                        # past the end of the line
        ]
        items = build_review_items(rows, self.chapters)
        self.assertEqual([(item["line_id"], item["ply"]) for item in items], [("main", 15), ("main", 13)])
        self.assertEqual(items[1]["keys"], [("main", 13), ("line_2", 13)])  # asked once, both rows updated
        self.assertEqual(items[0]["previous"]["san"], "Nbd7")
        self.assertEqual(items[0]["chapter_title"], self.chapter["chapter_meta"]["chapter_title"])

    def test_review_session_uses_the_quiz_rules(self):
        items = build_review_items([self.row("main", 15), self.row("main", 13)], self.chapters)
        session = ReviewSession(items)
        self.assertEqual((session.count, session.fen), (2, items[0]["step"]["fen_before"]))
        result = session.submit_move("f1d1")  # 8.Rd1 instead of 8.Nbd2
        self.assertEqual((result["action"], result["hint"], result["review_days"]),
                         ("show_hint", items[0]["step"]["hint"], [1, 7]))
        result = session.submit_move("b1c3")
        self.assertEqual((result["action"], result["correct_san"], result["review_days"]),
                         ("show_correct_move", "Nbd2", [1, 3, 7]))
        self.assertEqual(session.submit_move("a1a5")["status"], "illegal")
        self.assertFalse(session.submit_move("b1d2")["first_try"])
        self.assertEqual(session.question_states(), ["shown", "current"])
        self.assertTrue(session.submit_move("d1c2")["first_try"])  # 7.Qc2
        self.assertTrue(session.is_complete)
        self.assertEqual((session.question_states(), session.accuracy), (["shown", "ok"], 50.0))
        self.assertEqual(session.submit_move("d1c2")["status"], "complete")

    def test_review_peek_classifies_without_counting(self):
        session = ReviewSession(build_review_items([self.row("main", 15)], self.chapters))
        check = session.peek("f1d1")
        self.assertEqual((check["status"], check["label"]), ("off_book", "8. Rd1"))
        self.assertEqual(session.question_states(), ["current"])
        self.assertTrue(session.submit_move("b1d2")["first_try"])
        self.assertEqual(session.peek("b1d2"), {"status": "complete"})

    def test_nothing_to_review(self):
        session = ReviewSession([])
        self.assertTrue(session.is_complete)
        self.assertEqual((session.fen, session.last_move), (chess.STARTING_FEN, None))

    def last_review_row(self, line_id, ply, streak=1, days="1,7"):
        """A row whose next review masters the position (day 7)."""
        return {**self.row(line_id, ply), "review_days": days, "streak_correct": streak}

    def test_last_review_asks_why_after_a_first_try_move(self):
        items = build_review_items([self.last_review_row("main", 17), self.row("main", 15)], self.chapters)
        self.assertEqual(([asks_purpose(item) for item in items], items[0]["final_keys"]), ([True, False], [("main", 17)]))
        session = ReviewSession(items, rng=random.Random(7))
        result = session.submit_move("e2e4")  # 9.e4 on the first try
        self.assertEqual((result["status"], result["ask_purpose"], session.awaiting_purpose), ("correct", True, True))
        self.assertIs(session.current, items[0])  # the position stays until the purpose answer
        self.assertEqual((session.question_states(), session.answered_count), (["current", "pending"], 1))
        purpose = items[0]["purpose"]
        choices = session.purpose_choices
        self.assertEqual(sorted(choices), sorted([purpose["answer"], *purpose["wrong"]]))
        self.assertEqual(session.purpose_choices, choices)  # the order stays while the question is open
        self.assertEqual(session.submit_move("e2e4")["status"], "purpose_pending")
        self.assertEqual(session.peek("e2e4"), {"status": "purpose_pending"})
        self.assertEqual(session.answer_purpose(5)["status"], "invalid")

        answer = session.answer_purpose(choices.index(purpose["answer"]))
        self.assertEqual((answer["status"], answer["is_complete"]), ("right", False))
        self.assertEqual(answer["choices"][answer["answer_index"]], purpose["answer"])
        self.assertEqual((session.current, session.purpose_choices), (items[1], []))
        self.assertEqual(session.answer_purpose(0)["status"], "no_question")
        self.assertFalse(session.submit_move("b1d2")["ask_purpose"])  # not its last review: no question
        self.assertEqual((session.question_states(), session.purpose_right_count, session.purpose_asked),
                         (["ok", "ok"], 1, 1))

    def test_a_wrong_purpose_answer_shows_as_a_warning(self):
        row = self.last_review_row("main", 17, streak=2, days="1,3,7")
        session = ReviewSession(build_review_items([row], self.chapters))
        session.submit_move("e2e4")
        wrong = session.current["purpose"]["wrong"][0]
        answer = session.answer_purpose(session.purpose_choices.index(wrong))
        self.assertEqual((answer["status"], answer["chosen"] == answer["answer_index"], answer["is_complete"]),
                         ("wrong", False, True))
        self.assertEqual((session.question_states(), session.accuracy, session.purpose_right_count),
                         (["hint"], 100.0, 0))

    def test_no_purpose_question_after_a_wrong_move(self):
        session = ReviewSession(build_review_items([self.last_review_row("main", 17)], self.chapters))
        self.assertEqual(session.submit_move("b2b3")["status"], "incorrect")  # the plan restarts instead
        result = session.submit_move("e2e4")
        self.assertEqual((result["first_try"], result["ask_purpose"], session.is_complete), (False, False, True))
        self.assertEqual(session.purpose_asked, 0)


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
