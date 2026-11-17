#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the pure helpers of level_view.py (no window is opened). Run from
the project folder:

    python -m unittest test_level_view -v
"""

import unittest

from level_view import (
    DEFAULT_AREA,
    MAX_SCALE,
    MAX_SQUARE,
    MIN_SQUARE,
    PANEL_BASE_WIDTH,
    compute_layout,
    move_label,
    review_days_text,
)


class LayoutTests(unittest.TestCase):
    def test_start_window_keeps_the_designed_size(self):
        # 1180 x 780 window with the sidebar open: exactly the original 56 px squares and 360 px panel.
        self.assertEqual(compute_layout(*DEFAULT_AREA), {"square": 56, "piece": 34, "panel": 360, "scale": 1.0})

    def test_big_window_grows_board_panel_and_text(self):
        # A maximized 1536 x 864 window (1920 x 1080 at 125 %) with the sidebar closed.
        self.assertEqual(compute_layout(1536, 738), {"square": 72, "piece": 43, "panel": 463, "scale": 1.29})

    def test_closing_the_sidebar_gives_a_bigger_board(self):
        self.assertGreater(compute_layout(1180, 722)["square"], compute_layout(925, 722)["square"])

    def test_huge_window_stops_at_the_maximum(self):
        layout = compute_layout(2560, 1300)
        self.assertEqual((layout["square"], layout["scale"]), (MAX_SQUARE, MAX_SCALE))

    def test_narrow_window_puts_the_panel_under_the_board(self):
        # The smallest window (960 x 660) with the sidebar open: no room side by side,
        # so the board is limited by the height only and the row wraps.
        layout = compute_layout(705, 602)
        self.assertEqual((layout["square"], layout["panel"]), (56, 360))
        self.assertGreater(8 * layout["square"] + 20 + layout["panel"], 705 - 40)

    def test_tiny_area_never_goes_below_the_minimum(self):
        self.assertEqual(compute_layout(300, 200)["square"], MIN_SQUARE)

    def test_sizes_always_stay_in_range(self):
        for width in range(300, 3001, 137):
            for height in range(200, 1801, 113):
                layout = compute_layout(width, height)
                with self.subTest(width=width, height=height):
                    self.assertEqual(layout["square"] % 4, 0)
                    self.assertTrue(MIN_SQUARE <= layout["square"] <= MAX_SQUARE)
                    self.assertTrue(1.0 <= layout["scale"] <= MAX_SCALE)
                    self.assertTrue(PANEL_BASE_WIDTH <= layout["panel"] <= round(PANEL_BASE_WIDTH * MAX_SCALE))


class TextTests(unittest.TestCase):
    def test_review_days_text(self):
        self.assertEqual(review_days_text([]), "")
        self.assertEqual(review_days_text([1]), "tomorrow")
        self.assertEqual(review_days_text([1, 7]), "tomorrow and in 7 days")
        self.assertEqual(review_days_text([1, 3, 7]), "tomorrow, in 3 days and in 7 days")

    def test_move_label(self):
        self.assertEqual(move_label({"move_number": 7, "turn": "white", "san": "Qc2"}), "7. Qc2")
        self.assertEqual(move_label({"move_number": 7, "turn": "black", "san": "Nbd7"}), "7... Nbd7")


if __name__ == "__main__":
    unittest.main()
