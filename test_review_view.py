#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the pure helpers of review_view.py (no window is opened). Run from
the project folder:

    python -m unittest test_review_view -v
"""

import unittest
from datetime import date, timedelta, timezone

from review_view import when_text

TODAY = date(2026, 11, 17)


class WhenTextTests(unittest.TestCase):
    def test_today_tomorrow_and_later(self):
        self.assertEqual(when_text("2026-11-17T08:00:00Z", TODAY, timezone.utc), "today")
        self.assertEqual(when_text("2026-11-10T00:00:00Z", TODAY, timezone.utc), "today")  # overdue
        self.assertEqual(when_text("2026-11-18T00:00:00Z", TODAY, timezone.utc), "tomorrow")
        weekday = f"{date(2026, 11, 22):%A}"
        self.assertEqual(when_text("2026-11-22T00:00:00Z", TODAY, timezone.utc), f"in 5 days ({weekday} 22 November)")

    def test_days_are_counted_in_local_time(self):
        amman = timezone(timedelta(hours=3))
        # 21:00 UTC on the 17th is already 00:00 on the 18th in Amman.
        self.assertEqual(when_text("2026-11-17T21:00:00Z", TODAY, amman), "tomorrow")
        self.assertEqual(when_text("2026-11-17T20:59:00Z", TODAY, amman), "today")


if __name__ == "__main__":
    unittest.main()
