#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for pgn_import.py. Run from the project folder:

    python -m unittest test_pgn_import -v

The PGN texts copy the layout of a Lichess study export (headers, comments
with [%cal] arrows, '*' results). Files are only written to a temporary folder.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

from level_trainer import load_level_chapter, validate_level_chapter
from pgn_import import PgnImportError, _split_comment, import_pgn_file, main, pgn_to_chapter

REAL_CHAPTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalan_ch01_v2.json")

# Chapter 1 of the app written as two study chapters (its levels 1 and 3).
CH1_SETUP = "1. d4 Nf6 2. c4 e6 3. g3 d5 4. Bg2 Be7 5. Nf3 O-O 6. O-O c6 7. Qc2 Nbd7 8. Nbd2 b6 9. e4"
CH1_DXC4 = CH1_SETUP + " dxc4 10. Nxc4 Bb7 11. Rd1"

COMMENTED = (
    "1. d4 { Take the center. [%cal Gd2d4] } 1... Nf6 { Stop e4. [%csl Ge4] } "
    "2. c4 { Hit d5.\nOpen lines for the queenside. Hint: Use your c-pawn. } 2... e6 "
    "3. g3 { [%eval 0.25] } 3... d5"
)


def study_chapter(moves, chapter="Setup", study="Closed Catalan", intro=None, orientation="white", extra_headers=""):
    """One study chapter laid out the way Lichess exports it."""
    root = f"{{ {intro} }} " if intro else ""
    return (
        f'[Event "{study}: {chapter}"]\n'
        '[Site "https://lichess.org/study/AbCdEfGh/IjKlMnOp"]\n'
        '[Result "*"]\n'
        '[Variant "Standard"]\n'
        '[ECO "E08"]\n'
        '[Opening "Catalan Opening: Closed"]\n'
        '[Annotator "https://lichess.org/@/some_author"]\n'
        f'[StudyName "{study}"]\n'
        f'[ChapterName "{chapter}"]\n'
        f'[Orientation "{orientation}"]\n'
        f"{extra_headers}\n"
        f"{root}{moves} *\n\n\n"
    )


def knight_dance(full_moves):
    """A legal line of any length: 1.Nf3 Nf6 2.Ng1 Ng8 3.Nf3 Nf6 ..."""
    return " ".join(f"{n}. Nf3 Nf6" if n % 2 else f"{n}. Ng1 Ng8" for n in range(1, full_moves + 1))


def sans(line):
    return [step["san"] for step in line]


def ranges(levels):
    return [(level["level"], level["type"], level["line_id"], level["from_ply"], level["to_ply"]) for level in levels]


class CommentTests(unittest.TestCase):
    def test_idea_explanation_and_hint(self):
        self.assertEqual(_split_comment("Hit d5.\nOpen lines. Hint: Use your c-pawn."),
                         ("Hit d5.", "Open lines.", "Use your c-pawn."))

    def test_lichess_commands_are_removed(self):
        self.assertEqual(_split_comment("Take the center. [%cal Gd2d4,Gc2c4] [%eval 0.3]"),
                         ("Take the center.", None, None))
        self.assertEqual(_split_comment("[%clk 0:10:00]"), (None, None, None))

    def test_hint_only(self):
        self.assertEqual(_split_comment("hint: Move a knight."), (None, None, "Move a knight."))

    def test_arabic_hint_marker(self):
        self.assertEqual(_split_comment("فكرة النقلة. تلميح: حرّك الحصان"), ("فكرة النقلة.", None, "حرّك الحصان"))


class ImportTests(unittest.TestCase):
    def test_single_study_chapter(self):
        chapter, warnings = pgn_to_chapter(study_chapter(COMMENTED, intro="Black builds a solid center."), "test_ch")
        meta = chapter["chapter_meta"]
        self.assertEqual((meta["chapter_id"], meta["chapter_title"], meta["player_color"]),
                         ("test_ch", "Closed Catalan", "white"))
        self.assertEqual((meta["description"], meta["min_accuracy_to_pass"]), ("Black builds a solid center.", 85))
        main_line = chapter["lines"]["main"]
        self.assertEqual(sans(main_line), ["d4", "Nf6", "c4", "e6", "g3", "d5"])
        self.assertEqual((main_line[0]["strategic_idea"], main_line[0]["hint"]), ("Take the center.", None))
        self.assertEqual(main_line[1]["strategic_idea"], "Stop e4.")
        self.assertEqual((main_line[2]["strategic_idea"], main_line[2]["explanation"], main_line[2]["hint"]),
                         ("Hit d5.", "Open lines for the queenside.", "Use your c-pawn."))
        self.assertEqual((main_line[4]["strategic_idea"], main_line[4]["explanation"]), (None, None))
        self.assertEqual(ranges(chapter["levels"]), [(1, "learn", "main", 1, 6), (2, "quiz", "main", 1, 6)])
        self.assertEqual(chapter["levels"][0]["title"], "Setup")
        self.assertEqual(chapter["levels"][0]["intro"], "Black builds a solid center.")
        self.assertEqual(chapter["levels"][1]["title"], "Test: Setup")
        self.assertEqual([rule["review_days"] for rule in chapter["levels"][1]["on_mistake"]], [[1, 7], [1, 3, 7]])
        self.assertEqual(warnings, [])
        validate_level_chapter(chapter)

    def test_headers_and_commands_never_reach_the_chapter(self):
        chapter, _ = pgn_to_chapter(study_chapter(COMMENTED), "test_ch")
        text = json.dumps(chapter, ensure_ascii=False)
        for unwanted in ("E08", "lichess.org", "some_author", "Catalan Opening: Closed", "[%", "fen_before"):
            self.assertNotIn(unwanted, text)

    def test_continuing_chapter_extends_the_line(self):
        pgn = study_chapter("1. d4 Nf6 2. c4 e6") + study_chapter("1. d4 Nf6 2. c4 e6 3. g3 d5", chapter="More")
        chapter, _ = pgn_to_chapter(pgn, "test_ch")
        self.assertEqual(list(chapter["lines"]), ["main"])
        self.assertEqual(len(chapter["lines"]["main"]), 6)
        self.assertEqual(ranges(chapter["levels"])[2:], [(3, "learn", "main", 5, 6), (4, "quiz", "main", 5, 6)])

    def test_chapter_that_leaves_the_line_gets_a_new_line(self):
        pgn = study_chapter("1. d4 Nf6 2. c4 e6") + study_chapter("1. d4 Nf6 2. c4 c5 3. d5", chapter="Benoni")
        chapter, _ = pgn_to_chapter(pgn, "test_ch")
        self.assertEqual(sans(chapter["lines"]["line_2"]), ["d4", "Nf6", "c4", "c5", "d5"])
        self.assertEqual(ranges(chapter["levels"])[2:], [(3, "learn", "line_2", 4, 5), (4, "quiz", "line_2", 4, 5)])

    def test_chapter_without_new_moves_is_refused(self):
        pgn = study_chapter("1. d4 Nf6 2. c4 e6") + study_chapter("1. d4 Nf6", chapter="Again")
        with self.assertRaisesRegex(PgnImportError, "no new moves"):
            pgn_to_chapter(pgn, "test_ch")

    def test_new_moves_without_a_player_move_are_refused(self):
        pgn = study_chapter("1. d4 Nf6 2. c4") + study_chapter("1. d4 Nf6 2. c4 e6", chapter="Black only")
        with self.assertRaisesRegex(PgnImportError, "no white move"):
            pgn_to_chapter(pgn, "test_ch")

    def test_illegal_move_is_refused(self):
        with self.assertRaisesRegex(PgnImportError, "Setup"):
            pgn_to_chapter(study_chapter("1. d4 Nf6 2. Nf6"), "test_ch")

    def test_set_up_position_is_refused(self):
        headers = '[SetUp "1"]\n[FEN "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1"]\n'
        with self.assertRaisesRegex(PgnImportError, "starting position"):
            pgn_to_chapter(study_chapter("1... Nf6 2. c4", extra_headers=headers), "test_ch")

    def test_side_variations_are_left_out_with_a_warning(self):
        chapter, warnings = pgn_to_chapter(study_chapter("1. d4 Nf6 2. c4 (2. Nf3 d5) 2... e6"), "test_ch")
        self.assertEqual(sans(chapter["lines"]["main"]), ["d4", "Nf6", "c4", "e6"])
        self.assertTrue(any("side variations" in warning for warning in warnings))

    def test_moves_after_move_14_are_left_out(self):
        chapter, warnings = pgn_to_chapter(study_chapter(knight_dance(16)), "test_ch")
        self.assertEqual(len(chapter["lines"]["main"]), 28)  # 14...Ng8 is the last move kept
        self.assertEqual(chapter["lines"]["main"][-1]["move_number"], 14)
        self.assertTrue(any("after move 14" in warning and "15.Nf3" in warning for warning in warnings))

    def test_black_orientation_trains_black(self):
        moves = "1. d4 { Hint: x } 1... Nf6 { Hint: Develop toward the center. } 2. c4 e6"
        chapter, warnings = pgn_to_chapter(study_chapter(moves, orientation="black"), "test_ch")
        self.assertEqual(chapter["chapter_meta"]["player_color"], "black")
        main_line = chapter["lines"]["main"]
        self.assertEqual((main_line[0]["hint"], main_line[1]["hint"]), (None, "Develop toward the center."))
        self.assertTrue(any("hint on 1.d4" in warning for warning in warnings))

    def test_names_from_event_when_name_headers_are_missing(self):
        pgn = '[Event "Closed Catalan: 6...c6 with 8.Nbd2: Setup"]\n\n1. d4 Nf6 2. c4 e6 *\n'
        chapter, _ = pgn_to_chapter(pgn, "test_ch")
        self.assertEqual(chapter["chapter_meta"]["chapter_title"], "Closed Catalan: 6...c6 with 8.Nbd2")
        self.assertEqual(chapter["levels"][0]["title"], "Setup")
        self.assertEqual(chapter["chapter_meta"]["player_color"], "white")  # no Orientation header

    def test_color_argument_wins_over_orientation(self):
        chapter, _ = pgn_to_chapter(study_chapter("1. d4 Nf6 2. c4 e6"), "test_ch", player_color="black")
        self.assertEqual(chapter["chapter_meta"]["player_color"], "black")

    def test_empty_pgn_is_refused(self):
        with self.assertRaises(PgnImportError):
            pgn_to_chapter("", "test_ch")


class PilotTest(unittest.TestCase):
    """Two study chapters must give back the moves and levels of catalan_ch01_v2.json."""

    def test_reproduces_chapter_1(self):
        pgn = study_chapter(CH1_SETUP) + study_chapter(CH1_DXC4, chapter="9...dxc4")
        chapter, warnings = pgn_to_chapter(pgn, "catalan_ch01_pilot")
        existing = load_level_chapter(REAL_CHAPTER_PATH)
        self.assertEqual(warnings, [])
        imported = sans(chapter["lines"]["main"])
        self.assertEqual(imported, sans(existing["lines"]["main"])[:len(imported)])  # the real line may go further
        # Levels 1-3 match; the real level 4 was set by hand to test everything (plies 1-21).
        self.assertEqual(ranges(chapter["levels"])[:3], ranges(existing["levels"])[:3])
        self.assertEqual(ranges(chapter["levels"])[3], (4, "quiz", "main", 18, 21))


class FileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pgn_path = os.path.join(self._tmp.name, "study.pgn")
        with open(self.pgn_path, "w", encoding="utf-8-sig") as handle:  # Lichess files may start with a BOM
            handle.write(study_chapter(COMMENTED))
        self.json_path = os.path.join(self._tmp.name, "my_chapter.json")

    def test_writes_a_valid_chapter_file(self):
        import_pgn_file(self.pgn_path, self.json_path)
        chapter = load_level_chapter(self.json_path)
        self.assertEqual(chapter["chapter_meta"]["chapter_id"], "my_chapter")
        with open(self.json_path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('"review_days": [1, 7]', text)
        self.assertNotIn("fen_before", text)

    def test_existing_file_is_never_replaced_without_force(self):
        with open(self.json_path, "w", encoding="utf-8") as handle:
            handle.write("keep me")
        with self.assertRaisesRegex(PgnImportError, "already exists"):
            import_pgn_file(self.pgn_path, self.json_path)
        with open(self.json_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "keep me")
        import_pgn_file(self.pgn_path, self.json_path, force=True)
        load_level_chapter(self.json_path)

    def test_output_must_be_json(self):
        with self.assertRaises(PgnImportError):
            import_pgn_file(self.pgn_path, os.path.join(self._tmp.name, "chapter.txt"))

    def test_command_line(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main([self.pgn_path, self.json_path]), 0)
            self.assertEqual(main([self.pgn_path, self.json_path]), 1)  # the file exists now
            self.assertEqual(main([os.path.join(self._tmp.name, "missing.pgn"), "other.json"]), 1)
        self.assertIn("level  2  quiz", out.getvalue())
        self.assertIn("already exists", err.getvalue())


if __name__ == "__main__":
    unittest.main()
