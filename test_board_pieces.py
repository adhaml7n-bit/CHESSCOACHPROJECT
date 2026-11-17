#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for board_pieces.py (no window is opened). Run from the project folder:

    python -m unittest test_board_pieces -v
"""

import os
import unittest

import chess
import flet as ft

from board_pieces import ASSETS_DIR, PIECE_SET, has_piece_images, piece_asset, piece_controls

COLORS = {"piece_white": "#FFFFFF", "piece_black": "#0F172A", "piece_shadow": "#475569"}
BLACK_PAWN = chess.Piece(chess.PAWN, chess.BLACK)
WHITE_QUEEN = chess.Piece(chess.QUEEN, chess.WHITE)


def texts(controls):
    """Text values inside a list of controls (following .content)."""
    found = []
    for control in controls:
        while control is not None:
            if isinstance(control, ft.Text):
                found.append(control)
                break
            control = getattr(control, "content", None)
    return found


class PieceSetTests(unittest.TestCase):
    def test_asset_names(self):
        self.assertEqual(piece_asset(chess.Piece(chess.KING, chess.WHITE)), "pieces/merida/wK.svg")
        self.assertEqual(piece_asset(BLACK_PAWN, "other"), "pieces/other/bP.svg")

    def test_merida_is_installed_with_its_license(self):
        self.assertEqual(PIECE_SET, "merida")
        self.assertTrue(has_piece_images())
        folder = os.path.join(ASSETS_DIR, "pieces", "merida")
        with open(os.path.join(folder, "LICENSE.txt"), encoding="utf-8") as handle:
            self.assertIn("GNU GENERAL PUBLIC LICENSE", handle.read())
        with open(os.path.join(folder, "README.md"), encoding="utf-8") as handle:
            self.assertIn("Armando Hernandez Marroquin", handle.read())

    def test_unknown_set_is_not_installed(self):
        self.assertFalse(has_piece_images("no_such_set"))


class PieceControlTests(unittest.TestCase):
    def test_installed_set_draws_one_picture(self):
        controls = piece_controls(BLACK_PAWN, 56, COLORS)
        self.assertEqual(len(controls), 1)
        image = controls[0].content
        self.assertIsInstance(image, ft.Image)
        self.assertEqual((image.src, image.width, image.height), ("/pieces/merida/bP.svg", 56, 56))
        self.assertEqual(image.error_content.value, "♟︎")  # backup if the picture fails to load

    def test_missing_set_falls_back_to_the_glyph_with_a_shadow(self):
        controls = piece_controls(WHITE_QUEEN, 50, COLORS, piece_set="no_such_set")
        shadow, glyph = texts(controls)
        self.assertEqual((shadow.value, glyph.value), ("♕", "♕"))
        self.assertEqual((shadow.color, glyph.color), (COLORS["piece_shadow"], COLORS["piece_white"]))
        self.assertEqual(glyph.size, 30)  # 60 % of the square by default

    def test_glyph_size_can_be_set(self):
        glyph = texts(piece_controls(WHITE_QUEEN, 60, COLORS, glyph_size=36, piece_set="no_such_set"))[1]
        self.assertEqual(glyph.size, 36)


if __name__ == "__main__":
    unittest.main()
