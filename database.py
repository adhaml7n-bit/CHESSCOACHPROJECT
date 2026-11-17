#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChessCoach - SQLite persistence layer
=====================================
Stores everything that belongs to a USER: profiles, settings, training progress
and recorded mistakes. Opening theory stays in the *.json chapter files and is
never copied into the database.

Tables (schema version 2)
    users           one row per local profile (no passwords)
    user_settings   one row per user: UI theme, board colours, engine time
    line_progress   one row per user + chapter + line ("core", "review", a branch id or "level_N")
    move_mistakes   one row per user + position where a wrong move was played, with its
                    review plan (review_days) and mastered_at once it is learned

Guest mode
    While nobody is logged in (current_user_id is None) the app is in Guest mode
    and nothing the guest does is saved. Two independent layers enforce this:
      1. every user-data write goes through ChessCoachDB._write(), which refuses
         when is_guest is True;
      2. every read uses a connection with PRAGMA query_only = ON, so SQLite
         itself rejects a write even if a future method forgets layer 1.
    The only writes allowed without a logged-in user are creating the empty
    tables on first launch and create_user() / login(), which are the way out
    of Guest mode.

Values that can be calculated are not stored: chapter status and completion %
come from summarize_chapter_progress(). A position is mastered once its last
review day was answered correctly (mastered_at is then set).

Spaced repetition (DESIGN.md section 3)
    A mistake comes back on the days of its review plan, counted in local
    calendar days from the day of the mistake: one mistake -> tomorrow and
    day 7; two mistakes in one go -> days 1, 3 and 7. A first-try correct
    answer on a due day moves on to the next day of the plan (never to the
    same day again); after the last one the position is mastered and does
    not come back. A new mistake restarts the plan.
    On the last review the screen also asks why the move is played; a wrong
    answer there keeps the position at that last review and brings it back
    PURPOSE_RETRY_DAYS later (postpone_review), with the same questions.
"""

import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone

DB_FILENAME = "chesscoach.db"
SCHEMA_VERSION = 2
MIN_SQLITE_VERSION = (3, 37, 0)  # STRICT tables need SQLite 3.37+

# Line identifiers. A branch uses its own "branch_id" from the chapter JSON.
LINE_CORE = "core"
LINE_REVIEW = "review"

MAX_USERNAME_LENGTH = 32  # keep in sync with the CHECK on users.username

# Review plans for recorded mistakes, in days after the mistake (see the module docstring).
# The quiz levels pass their own plan from the chapter JSON ("on_mistake"); these are the defaults.
ONE_MISTAKE_DAYS = (1, 7)
TWO_MISTAKES_DAYS = (1, 3, 7)
# Right move but wrong purpose answer on the last review: back in this many days (owner, 2026-11-17).
PURPOSE_RETRY_DAYS = 3


class UsernameTakenError(ValueError):
    """Raised when a username already exists (compared case-insensitively)."""


class DatabaseVersionError(RuntimeError):
    """Raised when chesscoach.db was created by a newer version of the app."""


# =====================================================================
# 1. Schema & Migrations
# =====================================================================
# MIGRATIONS[n] upgrades a database from version n to version n + 1, and its
# last statement stores the new version number. To change the schema later,
# append a new tuple (for example an ALTER TABLE ... ADD COLUMN) and raise
# SCHEMA_VERSION. Never edit a migration that has already shipped, and never
# delete chesscoach.db to "fix" the schema: that would erase user progress.

_SCHEMA_V1 = (
    """
    CREATE TABLE users (
        user_id           INTEGER PRIMARY KEY,
        username          TEXT NOT NULL COLLATE NOCASE UNIQUE
                          CHECK (username = trim(username) AND length(username) BETWEEN 1 AND 32),
        display_name      TEXT NOT NULL CHECK (length(display_name) >= 1),
        chesscom_username TEXT,            -- NULL = not linked
        lichess_username  TEXT,            -- NULL = not linked
        created_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL,
        last_login_at     TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE user_settings (
        user_id           INTEGER PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
        ui_mode           TEXT NOT NULL DEFAULT 'dark' CHECK (ui_mode IN ('light', 'dark')),
        board_preset      TEXT NOT NULL DEFAULT 'classic' CHECK (length(board_preset) >= 1),
        -- NULL = use the colours of board_preset; otherwise '#RGB' or '#RRGGBB'
        light_sq_color    TEXT CHECK (light_sq_color IS NULL OR (
                              length(light_sq_color) IN (4, 7)
                              AND light_sq_color GLOB '#*'
                              AND substr(light_sq_color, 2) NOT GLOB '*[^0-9A-Fa-f]*')),
        dark_sq_color     TEXT CHECK (dark_sq_color IS NULL OR (
                              length(dark_sq_color) IN (4, 7)
                              AND dark_sq_color GLOB '#*'
                              AND substr(dark_sq_color, 2) NOT GLOB '*[^0-9A-Fa-f]*')),
        engine_time_limit REAL NOT NULL DEFAULT 0.5 CHECK (engine_time_limit > 0)
    ) STRICT
    """,
    """
    CREATE TABLE line_progress (
        user_id         INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
        chapter_id      TEXT NOT NULL CHECK (length(chapter_id) >= 1),
        line_id         TEXT NOT NULL CHECK (length(line_id) >= 1),
        times_completed INTEGER NOT NULL DEFAULT 0 CHECK (times_completed >= 0),
        best_accuracy   REAL CHECK (best_accuracy BETWEEN 0 AND 100),  -- NULL = never measured
        last_played_at  TEXT NOT NULL,
        PRIMARY KEY (user_id, chapter_id, line_id)
    ) STRICT
    """,
    """
    CREATE TABLE move_mistakes (
        mistake_id      INTEGER PRIMARY KEY,
        user_id         INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
        chapter_id      TEXT NOT NULL CHECK (length(chapter_id) >= 1),
        -- 'core' or a branch id. Never NULL: SQLite treats every NULL as different
        -- inside UNIQUE, which would let the same position be stored many times.
        -- Never 'review' either: review replays the core positions.
        line_id         TEXT NOT NULL CHECK (length(line_id) >= 1 AND line_id <> 'review'),
        ply             INTEGER NOT NULL CHECK (ply >= 1),
        fen             TEXT NOT NULL,     -- position before the move (fingerprint of the lesson)
        last_wrong_san  TEXT NOT NULL,
        wrong_count     INTEGER NOT NULL DEFAULT 1 CHECK (wrong_count >= 1),
        streak_correct  INTEGER NOT NULL DEFAULT 0 CHECK (streak_correct >= 0),
        last_mistake_at TEXT NOT NULL,
        next_due_at     TEXT NOT NULL,
        UNIQUE (user_id, chapter_id, line_id, ply)
    ) STRICT
    """,
    "CREATE INDEX idx_move_mistakes_due ON move_mistakes (user_id, next_due_at)",
    "PRAGMA user_version = 1",
)

# Version 2: the review plan of each mistake. Existing rows keep the old
# schedule's three steps (1, 3, 7) and their due dates; rows the old rule
# counted as mastered (3 correct answers) get mastered_at.
_SCHEMA_V2 = (
    """
    ALTER TABLE move_mistakes ADD COLUMN review_days TEXT NOT NULL DEFAULT '1,3,7'
        CHECK (length(review_days) >= 1 AND review_days NOT GLOB '*[^0-9,]*')
    """,
    "ALTER TABLE move_mistakes ADD COLUMN mastered_at TEXT",  # NULL = still being reviewed
    "UPDATE move_mistakes SET mastered_at = next_due_at WHERE streak_correct >= 3",
    "PRAGMA user_version = 2",
)

MIGRATIONS = (_SCHEMA_V1, _SCHEMA_V2)


# =====================================================================
# 2. Small Helpers
# =====================================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_time(moment: datetime) -> str:
    """ISO 8601 in UTC, e.g. '2026-11-15T17:04:00Z'. Text in this fixed format sorts by time."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp() -> str:
    return _format_time(_utc_now())


def _parse_time(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _local_timezone():
    """The computer's time zone ("tomorrow" means the player's next calendar day)."""
    return datetime.now().astimezone().tzinfo


def _day_start_after(moment: datetime, days: int) -> datetime:
    """Local midnight `days` calendar days after `moment`, in UTC."""
    local = moment.astimezone(_local_timezone())
    start = datetime.combine(local.date() + timedelta(days=days), time.min, tzinfo=local.tzinfo)
    return start.astimezone(timezone.utc)


def _check_review_days(days) -> tuple[int, ...]:
    """A review plan must be increasing whole days above 0, e.g. (1, 7)."""
    days = tuple(days)
    if (not days or not all(isinstance(d, int) and not isinstance(d, bool) and d > 0 for d in days)
            or any(a >= b for a, b in zip(days, days[1:]))):
        raise ValueError(f"review_days must be increasing whole days above 0, e.g. (1, 7); got {days!r}.")
    return days


def parse_review_days(text: str) -> tuple[int, ...]:
    """The review_days column ('1,3,7') as a tuple of ints."""
    return tuple(int(part) for part in text.split(","))


def _open_connection(path: str) -> sqlite3.Connection:
    # This module starts and ends its own transactions (BEGIN / COMMIT), so the
    # sqlite3 module must not open hidden ones: "PRAGMA foreign_keys = ON" is
    # silently ignored when it runs inside a transaction.
    if sys.version_info >= (3, 12):
        return sqlite3.connect(path, timeout=5, autocommit=True)
    return sqlite3.connect(path, timeout=5, isolation_level=None)


def _clean_username(username: str) -> str:
    username = (username or "").strip()
    if not username:
        raise ValueError("Username cannot be empty.")
    if len(username) > MAX_USERNAME_LENGTH:
        raise ValueError(f"Username cannot be longer than {MAX_USERNAME_LENGTH} characters.")
    return username


def _is_unique_violation(exc: sqlite3.IntegrityError) -> bool:
    return "UNIQUE constraint failed" in str(exc)


def _position_line(line_id: str | None) -> str:
    """Line id used for a position. Core and review share the same positions, so
    both map to 'core' (OpeningSession.active_branch_id is None in those modes)."""
    return LINE_CORE if line_id in (None, LINE_REVIEW) else line_id


def summarize_chapter_progress(chapter: dict, line_rows: dict) -> dict:
    """Derives a chapter's status and completion % from its saved lines.

    chapter   - a chapter dict loaded from its JSON file
    line_rows - the result of ChessCoachDB.get_chapter_progress(chapter_id)

    A chapter consists of the core trunk, every branch, and the review test.
    Core and branches count once completed; the review counts once its best
    accuracy reaches review_phase.min_accuracy_to_pass.
    """
    pass_mark = chapter.get("review_phase", {}).get("min_accuracy_to_pass", 0)
    practice_lines = [LINE_CORE] + [branch["branch_id"] for branch in chapter.get("branches", [])]

    lines_done = sum(
        1 for line in practice_lines
        if line in line_rows and line_rows[line]["times_completed"] >= 1
    )
    review_row = line_rows.get(LINE_REVIEW)
    best_review_accuracy = review_row["best_accuracy"] if review_row else None
    review_passed = best_review_accuracy is not None and best_review_accuracy >= pass_mark
    if review_passed:
        lines_done += 1
    lines_total = len(practice_lines) + 1

    if not line_rows:
        status = "not_started"
    elif lines_done == lines_total:
        status = "completed"
    else:
        status = "in_progress"

    return {
        "status": status,
        "completion_pct": round(100 * lines_done / lines_total),
        "lines_done": lines_done,
        "lines_total": lines_total,
        "review_passed": review_passed,
        "best_review_accuracy": best_review_accuracy,
        "last_played_at": max((row["last_played_at"] for row in line_rows.values()), default=None),
    }


# =====================================================================
# 3. ChessCoachDB
# =====================================================================

class ChessCoachDB:
    def __init__(self, db_path: str | None = None):
        if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
            raise RuntimeError(
                f"ChessCoach needs SQLite {'.'.join(map(str, MIN_SQLITE_VERSION))} or newer "
                f"(found {sqlite3.sqlite_version})."
            )
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_FILENAME)
        self.db_path = db_path
        self.current_user_id: int | None = None  # None = Guest mode
        self._ensure_schema()

    @property
    def is_guest(self) -> bool:
        return self.current_user_id is None

    # -----------------------------------------------------------------
    # Connections: a short-lived connection per operation
    # -----------------------------------------------------------------
    # Flet may run event handlers on different threads, and a sqlite3
    # connection may only be used by the thread that opened it. Opening one
    # per operation avoids that problem, and is cheap for a local file.

    @contextmanager
    def _connection(self, writable: bool):
        conn = _open_connection(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            # Foreign keys are OFF by default in SQLite and must be enabled on
            # every connection, otherwise REFERENCES / ON DELETE CASCADE do nothing.
            conn.execute("PRAGMA foreign_keys = ON")
            if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise RuntimeError("SQLite refused to enable foreign key enforcement.")
            if writable:
                conn.execute("BEGIN IMMEDIATE")
            else:
                conn.execute("PRAGMA query_only = ON")
            yield conn
            if writable:
                conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def _fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._connection(writable=False) as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def _fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self._fetch_all(sql, params)
        return rows[0] if rows else None

    def _write(self, sql: str, params: tuple) -> bool:
        """The single door for saving user data.

        Returns True only if a row was actually written. In Guest mode it
        returns False without opening a writable connection. Real failures
        (broken constraint, disk full, ...) raise instead of returning False.
        """
        if self.is_guest:
            return False
        with self._connection(writable=True) as conn:
            return conn.execute(sql, params).rowcount > 0

    def _ensure_schema(self) -> None:
        with self._connection(writable=False) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return  # normal launch: nothing is written
        if version > SCHEMA_VERSION:
            raise DatabaseVersionError(
                f"{self.db_path} has schema version {version}, but this app only "
                f"understands up to version {SCHEMA_VERSION}. Update ChessCoach."
            )
        # One transaction: either every statement applies or none does.
        with self._connection(writable=True) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for migration in MIGRATIONS[version:]:
                for statement in migration:
                    conn.execute(statement)

    # -----------------------------------------------------------------
    # Users & session (the way in and out of Guest mode)
    # -----------------------------------------------------------------
    def list_users(self) -> list[dict]:
        """All profiles, most recently used first."""
        return self._fetch_all("SELECT * FROM users ORDER BY last_login_at DESC, username")

    def get_user(self, user_id: int) -> dict | None:
        return self._fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))

    def get_current_user(self) -> dict | None:
        return None if self.is_guest else self.get_user(self.current_user_id)

    def create_user(self, username: str, display_name: str = "") -> dict:
        """Creates a profile with default settings and logs in as that user.

        Raises ValueError for an empty or too long username, and
        UsernameTakenError when the name exists already ('Adham' == 'adham').
        """
        username = _clean_username(username)
        display_name = (display_name or "").strip() or username
        now = _timestamp()
        try:
            # The profile and its settings row are created together or not at all.
            with self._connection(writable=True) as conn:
                user_id = conn.execute(
                    "INSERT INTO users (username, display_name, created_at, updated_at, last_login_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (username, display_name, now, now, now),
                ).lastrowid
                conn.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
        except sqlite3.IntegrityError as exc:
            if _is_unique_violation(exc):
                raise UsernameTakenError(f"The username '{username}' is already taken.") from exc
            raise
        self.current_user_id = user_id
        return self.get_user(user_id)

    def login(self, user_id: int) -> dict | None:
        """Switches to an existing profile. Returns it, or None if it does not exist."""
        with self._connection(writable=True) as conn:
            found = conn.execute(
                "UPDATE users SET last_login_at = ? WHERE user_id = ?",
                (_timestamp(), user_id),
            ).rowcount > 0
        if not found:
            return None
        self.current_user_id = user_id
        return self.get_user(user_id)

    def login_last_user(self) -> dict | None:
        """Logs in as the most recently used profile (call once at startup).
        Returns None, and stays in Guest mode, when no profile exists yet."""
        row = self._fetch_one("SELECT user_id FROM users ORDER BY last_login_at DESC, user_id DESC LIMIT 1")
        return self.login(row["user_id"]) if row else None

    def switch_to_guest(self) -> None:
        """Leaves the current profile. From here on nothing is saved."""
        self.current_user_id = None

    def update_user_profile(
        self,
        username: str | None = None,
        display_name: str | None = None,
        chesscom_username: str | None = None,
        lichess_username: str | None = None,
    ) -> bool:
        """Edits the current profile. None keeps a field as it is; an empty
        string for chesscom_username / lichess_username removes the link."""
        user = self.get_current_user()
        if user is None:
            return False

        new_username = user["username"] if username is None else _clean_username(username)
        new_display = user["display_name"] if display_name is None else (display_name.strip() or new_username)
        new_chesscom = user["chesscom_username"] if chesscom_username is None else (chesscom_username.strip() or None)
        new_lichess = user["lichess_username"] if lichess_username is None else (lichess_username.strip() or None)

        try:
            return self._write(
                "UPDATE users SET username = ?, display_name = ?, chesscom_username = ?, "
                "lichess_username = ?, updated_at = ? WHERE user_id = ?",
                (new_username, new_display, new_chesscom, new_lichess, _timestamp(), user["user_id"]),
            )
        except sqlite3.IntegrityError as exc:
            if _is_unique_violation(exc):
                raise UsernameTakenError(f"The username '{new_username}' is already taken.") from exc
            raise

    # -----------------------------------------------------------------
    # Settings
    # -----------------------------------------------------------------
    def get_user_settings(self) -> dict | None:
        """Settings of the current user, or None in Guest mode.
        A colour that is None means "use the colours of board_preset"."""
        return self._fetch_one(
            "SELECT ui_mode, board_preset, light_sq_color, dark_sq_color, engine_time_limit "
            "FROM user_settings WHERE user_id = ?",
            (self.current_user_id,),
        )

    def save_user_settings(
        self,
        ui_mode: str | None = None,
        board_preset: str | None = None,
        light_sq_color: str | None = None,
        dark_sq_color: str | None = None,
        engine_time_limit: float | None = None,
    ) -> bool:
        """Saves the given settings; a value left as None is not changed."""
        # COALESCE(a, b) returns a unless it is NULL, so a None argument keeps the stored value.
        return self._write(
            "UPDATE user_settings SET "
            "ui_mode = COALESCE(?, ui_mode), "
            "board_preset = COALESCE(?, board_preset), "
            "light_sq_color = COALESCE(?, light_sq_color), "
            "dark_sq_color = COALESCE(?, dark_sq_color), "
            "engine_time_limit = COALESCE(?, engine_time_limit) "
            "WHERE user_id = ?",
            (ui_mode, board_preset, light_sq_color, dark_sq_color, engine_time_limit, self.current_user_id),
        )

    # -----------------------------------------------------------------
    # Progress
    # -----------------------------------------------------------------
    def save_line_result(self, chapter_id: str, line_id: str, accuracy: float | None = None) -> bool:
        """Call when the player finishes a line (LINE_CORE, LINE_REVIEW or a branch id).

        Counts one more completion and keeps the best accuracy seen so far.
        Pass accuracy=None when it was not measured for this run.
        """
        # INSERT ... ON CONFLICT DO UPDATE ("upsert"): insert the row, or update
        # the one that already holds this primary key. "excluded" is the row we
        # tried to insert.
        return self._write(
            """
            INSERT INTO line_progress (user_id, chapter_id, line_id, times_completed, best_accuracy, last_played_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT (user_id, chapter_id, line_id) DO UPDATE SET
                times_completed = times_completed + 1,
                best_accuracy = CASE
                    WHEN excluded.best_accuracy IS NULL THEN best_accuracy
                    WHEN best_accuracy IS NULL THEN excluded.best_accuracy
                    ELSE MAX(best_accuracy, excluded.best_accuracy)
                END,
                last_played_at = excluded.last_played_at
            """,
            (self.current_user_id, chapter_id, line_id, accuracy, _timestamp()),
        )

    def get_chapter_progress(self, chapter_id: str) -> dict:
        """Saved lines of one chapter as {line_id: row}. Empty for a guest or a new chapter.
        Feed the result to summarize_chapter_progress() for status and completion %."""
        rows = self._fetch_all(
            "SELECT line_id, times_completed, best_accuracy, last_played_at "
            "FROM line_progress WHERE user_id = ? AND chapter_id = ?",
            (self.current_user_id, chapter_id),
        )
        return {row["line_id"]: row for row in rows}

    # -----------------------------------------------------------------
    # Mistakes & spaced repetition
    # -----------------------------------------------------------------
    def record_mistake(
        self,
        chapter_id: str,
        line_id: str | None,
        ply: int,
        fen: str,
        wrong_san: str,
        review_days=ONE_MISTAKE_DAYS,
    ) -> bool:
        """Call each time the player plays a wrong move.

        line_id may be OpeningSession.active_branch_id as it is (None in core
        and review mode). fen is the position before the move. review_days is
        the review plan in days after today (the quiz's on_mistake rule, e.g.
        (1, 7) after one mistake, (1, 3, 7) after two). The plan restarts: the
        position is due from tomorrow (its first day) and is no longer mastered.
        """
        days = _check_review_days(review_days)
        now = _utc_now()
        return self._write(
            """
            INSERT INTO move_mistakes
                (user_id, chapter_id, line_id, ply, fen, last_wrong_san, last_mistake_at, next_due_at, review_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, chapter_id, line_id, ply) DO UPDATE SET
                fen = excluded.fen,
                last_wrong_san = excluded.last_wrong_san,
                wrong_count = wrong_count + 1,
                streak_correct = 0,
                last_mistake_at = excluded.last_mistake_at,
                next_due_at = excluded.next_due_at,
                review_days = excluded.review_days,
                mastered_at = NULL
            """,
            (self.current_user_id, chapter_id, _position_line(line_id), ply, fen, wrong_san,
             _format_time(now), _format_time(_day_start_after(now, days[0])), ",".join(map(str, days))),
        )

    def record_correct(self, chapter_id: str, line_id: str | None, ply: int) -> bool:
        """Call when the player finds the right move on the FIRST try.

        Only counts when a mistake is recorded for this position and it is due:
        repeating a line many times on the same day does not fake mastery.
        The position then moves to the next day of its plan (counted from the
        mistake, but never earlier than tomorrow), or is mastered after the last
        one. Returns True if the review counted.
        """
        now = _utc_now()
        mistake = self._fetch_one(
            "SELECT mistake_id, streak_correct, review_days, last_mistake_at FROM move_mistakes "
            "WHERE user_id = ? AND chapter_id = ? AND line_id = ? AND ply = ? "
            "AND mastered_at IS NULL AND next_due_at <= ?",
            (self.current_user_id, chapter_id, _position_line(line_id), ply, _format_time(now)),
        )
        if mistake is None:
            return False
        days = parse_review_days(mistake["review_days"])
        streak = mistake["streak_correct"] + 1
        if streak >= len(days):
            return self._write(
                "UPDATE move_mistakes SET streak_correct = ?, mastered_at = ? WHERE mistake_id = ? AND user_id = ?",
                (streak, _format_time(now), mistake["mistake_id"], self.current_user_id),
            )
        planned = _day_start_after(_parse_time(mistake["last_mistake_at"]), days[streak])
        next_due = max(planned, _day_start_after(now, 1))
        return self._write(
            "UPDATE move_mistakes SET streak_correct = ?, next_due_at = ? WHERE mistake_id = ? AND user_id = ?",
            (streak, _format_time(next_due), mistake["mistake_id"], self.current_user_id),
        )

    def postpone_review(self, chapter_id: str, line_id: str | None, ply: int,
                        days: int = PURPOSE_RETRY_DAYS) -> bool:
        """Call when the move was found on the last review but the purpose answer was wrong.

        The position is not mastered and stays at its last review; it comes back
        `days` calendar days from today (local midnight) with the same questions.
        Only a due position that is not mastered moves. Returns True if it moved.
        """
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            raise ValueError(f"days must be a whole number of 1 or more, got {days!r}.")
        now = _utc_now()
        return self._write(
            "UPDATE move_mistakes SET next_due_at = ? "
            "WHERE user_id = ? AND chapter_id = ? AND line_id = ? AND ply = ? "
            "AND mastered_at IS NULL AND next_due_at <= ?",
            (_format_time(_day_start_after(now, days)), self.current_user_id, chapter_id,
             _position_line(line_id), ply, _format_time(now)),
        )

    def _due_filter(self, chapter_ids) -> tuple[str, list]:
        """SQL condition and parameters: the current user's positions that are not mastered."""
        sql = "user_id = ? AND mastered_at IS NULL"
        params: list = [self.current_user_id]
        if chapter_ids is not None:
            ids = list(chapter_ids)
            sql += f" AND chapter_id IN ({', '.join('?' * len(ids)) or 'NULL'})"
            params += ids
        return sql, params

    def get_due_mistakes(self, limit: int = 20, chapter_ids=None) -> list[dict]:
        """Mistakes of the current user that should be drilled now, oldest due first.

        chapter_ids limits the list to those chapters (e.g. the chapters the app
        can still open). Each row points at a position (chapter_id, line_id, ply);
        the expected move, hint and explanation are read from the chapter JSON.
        If the row's fen no longer matches the JSON's fen_before, the lesson has changed.
        """
        condition, params = self._due_filter(chapter_ids)
        return self._fetch_all(
            f"SELECT * FROM move_mistakes WHERE {condition} AND next_due_at <= ? "
            "ORDER BY next_due_at, wrong_count DESC, last_mistake_at, mistake_id LIMIT ?",
            (*params, _timestamp(), limit),
        )

    def count_due_mistakes(self, chapter_ids=None) -> int:
        """How many positions are due now (for the Daily review card)."""
        condition, params = self._due_filter(chapter_ids)
        row = self._fetch_one(
            f"SELECT COUNT(*) AS due FROM move_mistakes WHERE {condition} AND next_due_at <= ?",
            (*params, _timestamp()),
        )
        return row["due"] if row else 0

    def get_next_review_at(self, chapter_ids=None) -> str | None:
        """When the earliest position not yet mastered is due (UTC text), or None."""
        condition, params = self._due_filter(chapter_ids)
        row = self._fetch_one(f"SELECT MIN(next_due_at) AS next_due FROM move_mistakes WHERE {condition}", tuple(params))
        return row["next_due"] if row else None

    def get_mistake(self, chapter_id: str, line_id: str | None, ply: int) -> dict | None:
        """The current user's row for one position (e.g. to show its next review), or None."""
        return self._fetch_one(
            "SELECT * FROM move_mistakes WHERE user_id = ? AND chapter_id = ? AND line_id = ? AND ply = ?",
            (self.current_user_id, chapter_id, _position_line(line_id), ply),
        )
