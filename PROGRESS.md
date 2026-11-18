# ChessCoach — Development Progress

ChessCoach is a desktop chess trainer built with **Python**, **Flet**, **python-chess** and **SQLite**.
It teaches openings move by move, talks to you while you learn ("you", "your opponent"), tests you on what
you learned, remembers the moves you get wrong, and includes a 2D board with **Stockfish** analysis.

**Status:** Catalan opening page, Chapter 1 (Closed Catalan, 40 levels) and the first levels of Chapter 2 (Open Catalan) playable · **Last updated:** 2026-11-18

---

## Features

| Area | Status | Details |
|---|---|---|
| App shell | ✅ Done | Collapsible sidebar, top bar, homepage dashboard, view routing |
| Themes | ✅ Done | Light / Dark UI, three board presets, custom HEX square colours |
| Engine & board | ✅ Done | Legal-move hints, promotion, castling, en passant, async Stockfish analysis with auto-detection |
| Opening page | ✅ Done | Catalan introduction, "ideal setup" board, six chapters with progress bars and Start / Resume / Practice again |
| Training screen | ✅ Done | Learn levels (move by move with ideas) and quiz levels (play the moves from memory) |
| Levels page | ✅ Done | A chapter opens on a page with all its levels as tiles (passed, next, locked, best quiz score) and a Continue button; inside a level, a one-line header leaves the room to the board |
| Mistakes in a quiz | ✅ Done | 1st mistake: a hint (or the piece to move is highlighted); 2nd: the correct move is shown and you play it |
| Second chance | ✅ Done | Positions you missed come back at the end of a quiz, to check you understood |
| Passing a level | ✅ Done | 85 % first-try accuracy opens the next level; one mistake is always allowed in a short quiz |
| Chapter 1: Closed Catalan | ✅ Done | 40 levels on 28 lines, every Closed Catalan line of the source study up to move 16: 7...Nbd7 and 7...b6 with their side lines, the e5 pawn structure, Black's other 6th moves (6...b6, 6...Ne4 with ...f5), the check 4...Bb4+ (5...Be7, 5...Bxd2+, the sharp 5...a5, 5...Bd6), and 4...Nbd7, 4...g6 and 4...Ne4, with your plan at the end of each line |
| Responsive board | ✅ Done | Board, panel and text grow with the window and the sidebar |
| Piece pictures | ✅ Done | Merida pieces on every board (see Credits) |
| Content import | ✅ Done | `pgn_import.py` turns a Lichess study (PGN) into a chapter file; every move is checked |
| User profiles | ✅ Done | Create and switch profiles; Guest mode saves nothing |
| Saved settings | ✅ Done | Theme and board colours restored per profile |
| Progress tracking | ✅ Done | Results per level; a Guest keeps progress until the app closes |
| Mistake tracking | ✅ Done | Every wrong move stored with its position, ready for spaced repetition |
| Review schedule | ✅ Done | A missed position comes back tomorrow and on day 7 (after two mistakes: days 1, 3 and 7), then it is mastered |
| Daily review | ✅ Done | The "Daily Revised" card shows how many positions are due and drills them, with the next review date after each answer |
| "Why this move?" | ✅ Done | On a position's last review (day 7) you also pick the move's purpose from three answers; it is mastered only when both are right |
| Engine second opinion | ✅ Done | A different move that Stockfish rates at most half a pawn worse than the lesson's move is praised, with no penalty; an optional "Use engine" card after each level shows where the engine agrees or prefers another move |
| Chapter 2: Open Catalan | 🚧 In progress | Your opponent takes your c4-pawn. Levels 1-13 are ready: 4...Be7 with 6...dxc4 7.Qc2 a6 8.a4, winning the pawn back, the trap 16...Qxd4? 17.Ne4, Black's other tries (10...Nbd7, 10...a5, 8...Nc6, 7...Bd7), and 7...b5 8.a4 with the double threat 11.Ng5. About 41 levels are planned, one group per Black defence (5...a6, 5...c5, 5...Nc6, 5...b5, 5...c6, 5...Bb4+, 4...Nbd7 and more) |
| Chapters 3–6 | 📋 Planned | The Catalan against the King's Indian, Semi-Slav, Grünfeld and other defences |
| Profile editing & online links | ⏸ Postponed | Rename profile, link Chess.com / Lichess accounts |

---

## Architecture

| Layer | Files | Responsibility |
|---|---|---|
| Interface | `chesscoach_flet.py`, `opening_hub_view.py`, `level_view.py`, `review_view.py`, `board_view.py`, `board_pieces.py`, `flet_compat.py` | Windows, themes, dialogs, the opening page, the training and review screens, the board and its pieces |
| Training logic | `level_trainer.py`, `opening_hub.py`, `engine_judge.py` | Validates chapters and moves, runs learn / quiz levels and reviews, scores accuracy, unlocks levels, asks Stockfish for a second opinion; no UI, no database |
| Curriculum | `catalan_opening.json`, `catalan_ch01_v2.json`, `catalan_ch02.json` | The opening page (intro, setup, chapter list), chapter 1 and chapter 2 (lines, ideas, hints, levels) |
| Content tools | `pgn_import.py` | Lichess study PGN → chapter file |
| Persistence | `database.py` | Profiles, settings, progress and mistakes in a local SQLite file |
| Assets | `assets/pieces/merida/` | Piece pictures and their license |

The first trainer (`opening_trainer.py`, `opening_view.py`, `catalan_ch01.json`) is kept in the repository but no longer opened by the app.

Design principles:
- **Theory and user data are kept apart.** Lessons live in JSON files; only the user's own data goes into the database.
- **Every move is checked.** Chapter files are validated move by move with python-chess when they load, and imported studies are checked the same way.
- **The app talks to you.** Explanations and messages are written in the second person, in the app's own words.
- **Guest mode is enforced in one place.** The database layer refuses every write for a guest, so no screen can save by accident.
- **Derived values are computed, not stored.** Level and chapter progress are calculated from saved results.
- **Schema changes use migrations,** so updates never wipe a user's progress.

---

## Spaced repetition

1. A wrong move in a quiz is recorded with its review days: after one mistake **tomorrow and day 7**,
   after two mistakes on the same position **days 1, 3 and 7**. Days are counted from the day of the
   mistake, in your local time ("tomorrow" starts at midnight).
2. On a review day, the position appears in the **Daily review**. Finding the move on the first try moves
   it to its next review day; after the last one it is **mastered** and does not come back.
3. On the last review day, finding the move is followed by **"Why do you play this move?"** with three answers.
   A wrong answer shows the right idea, and the position comes back **3 days** later with both questions.
4. A late review never brings a position back on the same day.
5. A new mistake restarts the position's review days.

Repeating the same line many times in one day does not count as a review.

---

## Getting started

Requirements: Windows, Python 3.12+, a Stockfish binary in a `stockfish*` folder (optional, for analysis).

```powershell
git clone <repository-url>
cd CHESSCOACHPROJECT
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe chesscoach_flet.py
```

The database file `chesscoach.db` is created automatically on first launch and is not tracked by Git.

### Tests
```powershell
.venv\Scripts\python.exe -m unittest
```
185 unit tests: database (47), levels, quizzes and reviews (72, including checks that both chapters can be played to the end and never teach two moves in one position), study import (23), opening page data (6), screen layout (14), piece pictures (6), review dates (2) and the engine (15, two of them with the real Stockfish when it is installed).

---

## Changelog

### 2026-11-18 — Open Catalan begins
- Chapter 2 (Open Catalan) is on the Catalan page with its first 13 levels: 4...Be7 5.Nf3 O-O 6.O-O dxc4 7.Qc2 a6 8.a4, winning the c4-pawn back, the trap 16...Qxd4? 17.Ne4, Black's other tries 10...Nbd7, 10...a5, 8...Nc6 and 7...Bd7, and 7...b5 8.a4 (the double threat 11.Ng5, and 8...b4 9.Nfd2). More levels follow, one group per Black defence.
- Where chapter 2 starts with the same moves as chapter 1, it uses the same explanations, and both chapters always teach the same move in the same position.
- 2 new unit tests (185 in total).

### 2026-11-17 — Training experience
- Catalan opening page: introduction, ideal-setup board and six chapters; Chapter 1 is ready, the rest are marked "Coming soon".
- New training screen with learn and quiz levels, hints, the correct move after a second mistake, a second-chance round, and progress per level.
- Chapter 1 rebuilt as 8 levels on two Closed Catalan branches, explained in the app's own voice.
- Lichess study importer for new chapters.
- The board, the panel and the text grow with the window.
- Pieces are now Merida pictures on every board (the black pawn no longer shows as an emoji on Windows).
- Review schedule: missed positions come back tomorrow and on day 7 (days 1, 3 and 7 after two mistakes); database schema version 2 (existing progress is kept).
- Daily review screen behind the homepage's "Daily Revised" card.
- "Why this move?": on the last review of a position, a multiple-choice question about the move's purpose (all 141 White moves of chapter 1 have one).
- Stockfish as a second opinion: good alternative moves are accepted without penalty, and an optional "Use engine" card follows each level.
- Fixed: with several Stockfish downloads, the app could pick a build for another processor and silently run without the engine. It now tries every binary it finds, builds for another processor last.
- Chapter format: a line can branch from another line, each move's explanation is written once for its position, and a level can cover several lines one after another (preparing the full Closed Catalan).
- Chapter 1 levels 9-16: the 7...b6 line to move 16, the e5 pawn structure (9...Nbd7, 13...a5, 9...Bb7) and the 7...Nbd7 side lines (9...dxe4, 8...b5, 8...Re8); levels 17-20: 6...b6 and 6...Ne4 with ...f5; levels 21-24: 4...Bb4+ 5.Bd2 Be7 (9...Nbd7, 9...Bb7, 9...Ba6); levels 25-28: 5...Bxd2+ (with 8...c5 and its three follow-ups); levels 29-32: 5...a5, the pawn-grab line with its traps, and 6...O-O; levels 33-36: 5...Bd6, and 4...Nbd7 with ...Bd6; levels 37-40: 4...g6 and 4...Ne4. Chapter 1 is complete.
- Levels page: a chapter now opens on a page with all its levels as tiles and a Continue button, instead of a bar of level buttons above the board; the board uses the room the bar took.
- 145 new unit tests (183 in total).

### 2026-11-15 — Persistence & profiles
- Added the SQLite database layer with 38 unit tests.
- Profiles with a top-bar account button; Guest mode by default.
- Appearance settings saved and restored per profile.
- Opening trainer now records mistakes, first-try answers and completed lines.
- Accuracy is now scored separately for every run.
- Light mode now uses a light sidebar.
- Compatibility layer for Flet 0.28 and 1.0+.

---

## Credits

- Chess pieces: **Merida** by Armando Hernandez Marroquin, GNU General Public License v2 or later. The unmodified files and the license are in `assets/pieces/merida/`.
