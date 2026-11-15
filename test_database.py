#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for database.py. Run from the project folder:

    python -m unittest test_database -v

Every test works on a throw-away database inside a temporary folder, so the
real chesscoach.db is never touched.
"""

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import database
from database import (
    LINE_CORE,
    LINE_REVIEW,
    ChessCoachDB,
    DatabaseVersionError,
    UsernameTakenError,
    summarize_chapter_progress,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
REAL_CHAPTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalan_ch01.json")


class FakeClock:
    """Replaces database._utc_now so tests can move time forward."""

    def __init__(self):
        self.now = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "chesscoach.db")

        self.clock = FakeClock()
        patcher = mock.patch.object(database, "_utc_now", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.db = ChessCoachDB(self.db_path)

    def snapshot(self):
        """Fingerprint of the folder: file names plus the database's exact bytes."""
        with open(self.db_path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        return sorted(os.listdir(self._tmp.name)), digest, os.stat(self.db_path).st_mtime_ns

    def raw(self, sql, params=()):
        """Runs SQL directly, bypassing ChessCoachDB (to inspect or to break rules on purpose)."""
        with self.db._connection(writable=True) as conn:
            return conn.execute(sql, params).fetchall()


class SchemaTests(DatabaseTestCase):
    def test_first_launch_creates_the_four_tables(self):
        tables = {row[0] for row in self.raw("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(tables, {"users", "user_settings", "line_progress", "move_mistakes"})
        self.assertEqual(self.raw("PRAGMA user_version")[0][0], database.SCHEMA_VERSION)

    def test_second_launch_writes_nothing(self):
        before = self.snapshot()
        ChessCoachDB(self.db_path)
        self.assertEqual(self.snapshot(), before)

    def test_database_from_a_newer_app_is_refused(self):
        self.raw("PRAGMA user_version = 99")
        with self.assertRaises(DatabaseVersionError):
            ChessCoachDB(self.db_path)

    def test_strict_tables_reject_wrong_types(self):
        user = self.db.create_user("adham")
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw(
                "INSERT INTO move_mistakes (user_id, chapter_id, line_id, ply, fen, last_wrong_san, "
                "last_mistake_at, next_due_at) VALUES (?, 'c', 'core', 'seven', 'f', 'e4', 't', 't')",
                (user["user_id"],),
            )

    def test_foreign_keys_are_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw(
                "INSERT INTO line_progress (user_id, chapter_id, line_id, times_completed, last_played_at) "
                "VALUES (999, 'catalan_ch01', 'core', 1, 't')"
            )

    def test_deleting_a_user_deletes_everything_they_own(self):
        user = self.db.create_user("adham")
        self.db.save_line_result("catalan_ch01", LINE_CORE)
        self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "e4")
        self.raw("DELETE FROM users WHERE user_id = ?", (user["user_id"],))
        for table in ("user_settings", "line_progress", "move_mistakes"):
            self.assertEqual(self.raw(f"SELECT COUNT(*) FROM {table}")[0][0], 0, table)


class GuestModeTests(DatabaseTestCase):
    def test_new_database_starts_in_guest_mode(self):
        self.assertTrue(self.db.is_guest)
        self.assertIsNone(self.db.get_current_user())
        self.assertIsNone(self.db.get_user_settings())

    def test_guest_writes_return_false_and_leave_the_file_untouched(self):
        self.db.create_user("adham")
        self.db.switch_to_guest()
        before = self.snapshot()

        self.assertFalse(self.db.update_user_profile(display_name="Hacker"))
        self.assertFalse(self.db.save_user_settings(ui_mode="light"))
        self.assertFalse(self.db.save_line_result("catalan_ch01", LINE_CORE, 90.0))
        self.assertFalse(self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "e4"))
        self.assertFalse(self.db.record_correct("catalan_ch01", None, 7))

        # Reads are allowed, and must not change the file either.
        self.assertEqual(len(self.db.list_users()), 1)
        self.assertEqual(self.db.get_chapter_progress("catalan_ch01"), {})
        self.assertEqual(self.db.get_due_mistakes(), [])

        self.assertEqual(self.snapshot(), before)

    def test_sqlite_itself_blocks_writes_on_read_connections(self):
        # Layer 2: even code that forgets the guest check cannot write.
        with self.assertRaises(sqlite3.OperationalError):
            with self.db._connection(writable=False) as conn:
                conn.execute(
                    "INSERT INTO users (username, display_name, created_at, updated_at, last_login_at) "
                    "VALUES ('x', 'x', 't', 't', 't')"
                )
        self.assertEqual(self.db.list_users(), [])

    def test_guest_cannot_see_another_users_data(self):
        self.db.create_user("adham")
        self.db.save_line_result("catalan_ch01", LINE_CORE)
        self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "e4")
        self.db.switch_to_guest()
        self.assertEqual(self.db.get_chapter_progress("catalan_ch01"), {})
        self.assertEqual(self.db.get_due_mistakes(), [])


class UserTests(DatabaseTestCase):
    def test_create_user_logs_in_and_creates_default_settings(self):
        user = self.db.create_user("  Adham  ")
        self.assertEqual(user["username"], "Adham")
        self.assertEqual(user["display_name"], "Adham")
        self.assertFalse(self.db.is_guest)
        self.assertEqual(
            self.db.get_user_settings(),
            {"ui_mode": "dark", "board_preset": "classic", "light_sq_color": None,
             "dark_sq_color": None, "engine_time_limit": 0.5},
        )

    def test_usernames_are_unique_ignoring_case(self):
        self.db.create_user("Adham")
        with self.assertRaises(UsernameTakenError):
            self.db.create_user("adham")
        self.assertEqual(len(self.db.list_users()), 1)

    def test_invalid_usernames_are_rejected(self):
        for bad in ("", "   ", "x" * 33):
            with self.assertRaises(ValueError):
                self.db.create_user(bad)
        self.assertEqual(self.db.list_users(), [])

    def test_failed_creation_leaves_no_half_made_profile(self):
        self.db.create_user("adham")
        with self.assertRaises(UsernameTakenError):
            self.db.create_user("ADHAM")
        self.assertEqual(self.raw("SELECT COUNT(*) FROM users")[0][0], 1)
        self.assertEqual(self.raw("SELECT COUNT(*) FROM user_settings")[0][0], 1)

    def test_sql_injection_attempt_is_stored_as_plain_text(self):
        nasty = "x'); DROP TABLE users;--"
        user = self.db.create_user(nasty)
        self.assertEqual(user["username"], nasty)
        self.assertEqual([u["username"] for u in self.db.list_users()], [nasty])

    def test_login_last_user_picks_the_most_recent_profile(self):
        first = self.db.create_user("first")
        self.clock.advance(minutes=1)
        self.db.create_user("second")
        self.clock.advance(minutes=1)
        self.db.login(first["user_id"])

        reopened = ChessCoachDB(self.db_path)
        self.assertTrue(reopened.is_guest)
        self.assertEqual(reopened.login_last_user()["username"], "first")
        self.assertEqual([u["username"] for u in reopened.list_users()], ["first", "second"])

    def test_login_last_user_with_no_profiles_stays_guest(self):
        self.assertIsNone(self.db.login_last_user())
        self.assertTrue(self.db.is_guest)

    def test_login_unknown_user_changes_nothing(self):
        user = self.db.create_user("adham")
        self.assertIsNone(self.db.login(12345))
        self.assertEqual(self.db.current_user_id, user["user_id"])

    def test_update_profile(self):
        self.db.create_user("adham")
        self.clock.advance(hours=1)
        self.assertTrue(self.db.update_user_profile(display_name="Adham K", chesscom_username=" adham_cc "))
        user = self.db.get_current_user()
        self.assertEqual(user["display_name"], "Adham K")
        self.assertEqual(user["chesscom_username"], "adham_cc")
        self.assertIsNone(user["lichess_username"])
        self.assertGreater(user["updated_at"], user["created_at"])

        # None keeps a value, an empty string removes the link.
        self.assertTrue(self.db.update_user_profile(chesscom_username=""))
        user = self.db.get_current_user()
        self.assertIsNone(user["chesscom_username"])
        self.assertEqual(user["display_name"], "Adham K")

    def test_renaming_to_a_taken_username_is_refused(self):
        self.db.create_user("first")
        self.db.create_user("second")
        with self.assertRaises(UsernameTakenError):
            self.db.update_user_profile(username="FIRST")
        self.assertEqual(self.db.get_current_user()["username"], "second")
        # Changing only the letter case of your own name is fine.
        self.assertTrue(self.db.update_user_profile(username="Second"))


class SettingsTests(DatabaseTestCase):
    def test_settings_are_saved_per_user(self):
        first = self.db.create_user("first")
        self.assertTrue(self.db.save_user_settings(ui_mode="light", board_preset="emerald",
                                                   light_sq_color="#EEEED2", dark_sq_color="#769656"))
        self.db.create_user("second")
        self.assertEqual(self.db.get_user_settings()["ui_mode"], "dark")

        self.db.login(first["user_id"])
        self.assertEqual(
            self.db.get_user_settings(),
            {"ui_mode": "light", "board_preset": "emerald", "light_sq_color": "#EEEED2",
             "dark_sq_color": "#769656", "engine_time_limit": 0.5},
        )

    def test_partial_save_keeps_other_values(self):
        self.db.create_user("adham")
        self.db.save_user_settings(ui_mode="light", light_sq_color="#fff")
        self.db.save_user_settings(engine_time_limit=2)
        settings = self.db.get_user_settings()
        self.assertEqual(settings["ui_mode"], "light")
        self.assertEqual(settings["light_sq_color"], "#fff")
        self.assertEqual(settings["engine_time_limit"], 2.0)

    def test_invalid_values_are_rejected_by_the_database(self):
        self.db.create_user("adham")
        bad_values = [
            {"ui_mode": "blue"},
            {"light_sq_color": "red"},
            {"dark_sq_color": "#12345G"},
            {"dark_sq_color": "#12345"},
            {"engine_time_limit": 0},
        ]
        for bad in bad_values:
            with self.assertRaises(sqlite3.IntegrityError, msg=bad):
                self.db.save_user_settings(**bad)
        self.assertEqual(self.db.get_user_settings()["ui_mode"], "dark")


class ProgressTests(DatabaseTestCase):
    CHAPTER = {
        "chapter_meta": {"chapter_id": "demo_ch01"},
        "branches": [{"branch_id": "branch_01"}, {"branch_id": "branch_02"}],
        "review_phase": {"min_accuracy_to_pass": 85},
    }

    def summary(self):
        return summarize_chapter_progress(self.CHAPTER, self.db.get_chapter_progress("demo_ch01"))

    def test_one_row_per_line_and_best_accuracy_is_kept(self):
        self.db.create_user("adham")
        self.assertTrue(self.db.save_line_result("demo_ch01", LINE_REVIEW, 70.0))
        self.clock.advance(minutes=5)
        self.db.save_line_result("demo_ch01", LINE_REVIEW, 92.5)
        self.db.save_line_result("demo_ch01", LINE_REVIEW, 80.0)
        self.db.save_line_result("demo_ch01", LINE_REVIEW)  # accuracy not measured

        self.assertEqual(self.raw("SELECT COUNT(*) FROM line_progress")[0][0], 1)
        row = self.db.get_chapter_progress("demo_ch01")[LINE_REVIEW]
        self.assertEqual(row["times_completed"], 4)
        self.assertEqual(row["best_accuracy"], 92.5)
        self.assertEqual(row["last_played_at"], "2026-11-15T12:05:00Z")

    def test_accuracy_can_arrive_after_a_run_without_one(self):
        self.db.create_user("adham")
        self.db.save_line_result("demo_ch01", LINE_CORE)
        self.assertIsNone(self.db.get_chapter_progress("demo_ch01")[LINE_CORE]["best_accuracy"])
        self.db.save_line_result("demo_ch01", LINE_CORE, 60)
        self.assertEqual(self.db.get_chapter_progress("demo_ch01")[LINE_CORE]["best_accuracy"], 60.0)

    def test_out_of_range_accuracy_is_rejected(self):
        self.db.create_user("adham")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.save_line_result("demo_ch01", LINE_CORE, 140)

    def test_summary_goes_from_not_started_to_completed(self):
        self.assertEqual(self.summary()["status"], "not_started")  # guest
        self.db.create_user("adham")
        self.assertEqual(self.summary()["completion_pct"], 0)

        self.db.save_line_result("demo_ch01", LINE_CORE)
        self.assertEqual((self.summary()["status"], self.summary()["completion_pct"]), ("in_progress", 25))

        self.db.save_line_result("demo_ch01", "branch_01")
        self.db.save_line_result("demo_ch01", "branch_02")
        self.db.save_line_result("demo_ch01", LINE_REVIEW, 80.0)  # below the 85 pass mark
        result = self.summary()
        self.assertEqual((result["status"], result["completion_pct"]), ("in_progress", 75))
        self.assertFalse(result["review_passed"])

        self.db.save_line_result("demo_ch01", LINE_REVIEW, 85.0)
        result = self.summary()
        self.assertEqual((result["status"], result["completion_pct"]), ("completed", 100))
        self.assertEqual(result["best_review_accuracy"], 85.0)

    def test_progress_is_separate_for_each_user(self):
        self.db.create_user("first")
        self.db.save_line_result("demo_ch01", LINE_CORE)
        self.db.create_user("second")
        self.assertEqual(self.db.get_chapter_progress("demo_ch01"), {})

    @unittest.skipUnless(os.path.exists(REAL_CHAPTER_PATH), "catalan_ch01.json is not next to this test")
    def test_summary_with_the_real_catalan_chapter(self):
        with open(REAL_CHAPTER_PATH, encoding="utf-8") as handle:
            chapter = json.load(handle)
        chapter_id = chapter["chapter_meta"]["chapter_id"]
        self.db.create_user("adham")
        self.db.save_line_result(chapter_id, LINE_CORE)
        for branch in chapter["branches"]:
            self.db.save_line_result(chapter_id, branch["branch_id"])
        self.db.save_line_result(chapter_id, LINE_REVIEW, 100.0)
        result = summarize_chapter_progress(chapter, self.db.get_chapter_progress(chapter_id))
        self.assertEqual((result["status"], result["completion_pct"]), ("completed", 100))


class MistakeTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.db.create_user("adham")

    def mistake_rows(self):
        return self.raw("SELECT line_id, ply, wrong_count, streak_correct, last_wrong_san FROM move_mistakes "
                        "ORDER BY line_id, ply")

    def test_same_position_is_one_row_even_when_line_id_is_none(self):
        # The NULL trap: with a NULL line id, UNIQUE would never match and rows would pile up.
        self.assertTrue(self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "e4"))
        self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "d4")
        self.db.record_mistake("catalan_ch01", LINE_REVIEW, 7, START_FEN, "c4")  # review = core positions
        self.db.record_mistake("catalan_ch01", LINE_CORE, 7, START_FEN, "Nc3")
        rows = self.mistake_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(tuple(rows[0]), ("core", 7, 4, 0, "Nc3"))

    def test_same_ply_in_a_branch_is_a_different_position(self):
        self.db.record_mistake("catalan_ch01", None, 15, START_FEN, "e4")
        self.db.record_mistake("catalan_ch01", "branch_01", 15, START_FEN, "e4")
        self.assertEqual([row["line_id"] for row in self.mistake_rows()], ["branch_01", "core"])

    def test_new_mistake_is_due_immediately(self):
        self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "e4")
        due = self.db.get_due_mistakes()
        self.assertEqual(len(due), 1)
        self.assertEqual((due[0]["chapter_id"], due[0]["line_id"], due[0]["ply"]), ("catalan_ch01", "core", 7))
        self.assertEqual(due[0]["fen"], START_FEN)

    def test_spaced_repetition_schedule_and_mastery(self):
        self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "e4")

        self.assertTrue(self.db.record_correct("catalan_ch01", None, 7))   # streak 1, back in 1 day
        self.assertEqual(self.db.get_due_mistakes(), [])
        self.assertFalse(self.db.record_correct("catalan_ch01", None, 7))  # same day: does not count

        self.clock.advance(hours=23)
        self.assertEqual(self.db.get_due_mistakes(), [])
        self.clock.advance(hours=1)
        self.assertEqual(len(self.db.get_due_mistakes()), 1)

        self.assertTrue(self.db.record_correct("catalan_ch01", LINE_REVIEW, 7))  # streak 2, back in 3 days
        self.clock.advance(days=2)
        self.assertEqual(self.db.get_due_mistakes(), [])
        self.clock.advance(days=1)
        self.assertEqual(len(self.db.get_due_mistakes()), 1)

        self.assertTrue(self.db.record_correct("catalan_ch01", None, 7))   # streak 3 = mastered
        self.clock.advance(days=365)
        self.assertEqual(self.db.get_due_mistakes(), [])
        self.assertFalse(self.db.record_correct("catalan_ch01", None, 7))
        self.assertEqual(self.mistake_rows()[0]["streak_correct"], database.MASTERY_STREAK)

    def test_a_new_mistake_resets_the_streak(self):
        self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "e4")
        self.db.record_correct("catalan_ch01", None, 7)
        self.clock.advance(days=1)
        self.db.record_correct("catalan_ch01", None, 7)
        self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "d4")
        row = self.mistake_rows()[0]
        self.assertEqual((row["wrong_count"], row["streak_correct"]), (2, 0))
        self.assertEqual(len(self.db.get_due_mistakes()), 1)

    def test_correct_move_without_a_recorded_mistake_does_nothing(self):
        self.assertFalse(self.db.record_correct("catalan_ch01", None, 3))
        self.assertEqual(self.mistake_rows(), [])

    def test_due_list_is_per_user_ordered_and_limited(self):
        self.db.record_mistake("catalan_ch01", None, 9, START_FEN, "e4")
        self.clock.advance(minutes=1)
        self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "e4")
        self.clock.advance(minutes=1)
        self.assertEqual([m["ply"] for m in self.db.get_due_mistakes()], [9, 7])
        self.assertEqual([m["ply"] for m in self.db.get_due_mistakes(limit=1)], [9])

        self.db.create_user("second")
        self.assertEqual(self.db.get_due_mistakes(), [])

    def test_database_rejects_a_review_line_id_for_mistakes(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw(
                "INSERT INTO move_mistakes (user_id, chapter_id, line_id, ply, fen, last_wrong_san, "
                "last_mistake_at, next_due_at) VALUES (?, 'c', 'review', 1, 'f', 'e4', 't', 't')",
                (self.db.current_user_id,),
            )


class ThreadingTests(DatabaseTestCase):
    def test_database_can_be_used_from_another_thread(self):
        self.db.create_user("adham")
        results = []

        def worker():
            try:
                results.append(self.db.record_mistake("catalan_ch01", None, 7, START_FEN, "e4"))
                results.append(len(self.db.get_due_mistakes()))
            except Exception as exc:  # report instead of dying silently in the thread
                results.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(results, [True, 1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
