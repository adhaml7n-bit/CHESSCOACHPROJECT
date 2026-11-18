#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for opening_hub.py. Run from the project folder:

    python -m unittest test_opening_hub -v

Most tests build small openings in memory; one loads the real
catalan_opening.json so the shipped hub is checked too.
"""

import copy
import os
import tempfile
import unittest

import chess

from opening_hub import OpeningFormatError, chapters_by_id, load_hub_chapters, load_opening, validate_opening

PROJECT = os.path.dirname(os.path.abspath(__file__))
REAL_OPENING_PATH = os.path.join(PROJECT, "catalan_opening.json")

EXAMPLE = {
    "title": "Test opening",
    "subtitle": "Chapters",
    "player_color": "white",
    "intro": "An introduction.",
    "strategic_focus": ["First idea", "Second idea"],
    "setup": {"title": "Setup", "moves": ["d4", "Nf6", "g3"], "focus_square": "g3", "path": ["f4", "e5"]},
    "release_note": "More is coming.",
    "chapters": [
        {"number": 1, "title": "Ready chapter", "file": "ready.json"},
        {"number": 2, "title": "Later chapter", "file": None},
    ],
}


def example():
    return copy.deepcopy(EXAMPLE)


class RealOpeningTests(unittest.TestCase):
    def test_catalan_opening_loads(self):
        opening = load_opening(REAL_OPENING_PATH)
        self.assertEqual(len(opening["chapters"]), 6)
        self.assertEqual(opening["chapters"][0]["title"], "Closed Catalan")
        board = chess.Board(opening["setup"]["fen"])
        self.assertEqual(board.piece_at(chess.G2), chess.Piece(chess.BISHOP, chess.WHITE))  # the Catalan bishop
        items = load_hub_chapters(opening)
        self.assertIsNone(items[0]["error"])
        self.assertEqual(items[0]["chapter"]["chapter_meta"]["chapter_id"], "catalan_ch01_v2")
        self.assertIsNone(items[1]["error"])
        self.assertEqual(items[1]["chapter"]["chapter_meta"]["chapter_id"], "catalan_ch02")  # the Open Catalan
        self.assertTrue(all(item["chapter"] is None and item["error"] is None for item in items[2:]))  # coming soon

    def test_ready_chapters_by_id(self):
        chapters = chapters_by_id([REAL_OPENING_PATH])
        self.assertEqual(list(chapters), ["catalan_ch01_v2", "catalan_ch02"])  # coming-soon chapters are left out
        self.assertIn("main", chapters["catalan_ch01_v2"]["lines"])
        self.assertIn("qc2", chapters["catalan_ch02"]["lines"])


class ValidationTests(unittest.TestCase):
    def test_valid_example(self):
        opening = validate_opening(example(), "some_folder")
        self.assertEqual(opening["chapters"][0]["path"], os.path.join("some_folder", "ready.json"))
        self.assertIsNone(opening["chapters"][1]["path"])
        self.assertEqual(chess.Board(opening["setup"]["fen"]).piece_at(chess.G3).symbol(), "P")

    def test_rejects_broken_openings(self):
        cases = {
            "missing title": lambda d: d.pop("title"),
            "empty intro": lambda d: d.update(intro=" "),
            "bad colour": lambda d: d.update(player_color="red"),
            "focus not a list": lambda d: d.update(strategic_focus="Pressure"),
            "illegal setup move": lambda d: d["setup"].update(moves=["d4", "d4"]),
            "bad focus square": lambda d: d["setup"].update(focus_square="z9"),
            "bad path square": lambda d: d["setup"].update(path=["e5", "h0"]),
            "no chapters": lambda d: d.update(chapters=[]),
            "numbering gap": lambda d: d["chapters"][1].update(number=3),
            "missing chapter title": lambda d: d["chapters"][0].update(title=""),
            "file not json": lambda d: d["chapters"][0].update(file="ready.pgn"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                data = example()
                mutate(data)
                with self.assertRaises(OpeningFormatError):
                    validate_opening(data, "some_folder")


class ChapterLoadingTests(unittest.TestCase):
    def test_a_broken_chapter_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "ready.json"), "w", encoding="utf-8") as handle:
                handle.write("{ not json")
            items = load_hub_chapters(validate_opening(example(), folder))
        self.assertIsNone(items[0]["chapter"])
        self.assertTrue(items[0]["error"])
        self.assertIsNone(items[1]["error"])  # a coming-soon chapter is not an error

    def test_a_missing_chapter_file_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            items = load_hub_chapters(validate_opening(example(), folder))
        self.assertIsNone(items[0]["chapter"])
        self.assertTrue(items[0]["error"])


if __name__ == "__main__":
    unittest.main()
