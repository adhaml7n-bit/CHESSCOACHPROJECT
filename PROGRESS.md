# ChessCoach — Development Progress

ChessCoach is a desktop chess trainer built with **Python**, **Flet**, **python-chess** and **SQLite**.
It teaches openings move by move, talks to you while you learn ("you", "your opponent"), tests you on what
you learned, remembers the moves you get wrong, and includes a 2D board with **Stockfish** analysis.

**Status:** Catalan opening page and Chapter 1 (Closed Catalan, 8 levels) playable · **Last updated:** 2026-11-17

---

## Features

| Area | Status | Details |
|---|---|---|
| App shell | ✅ Done | Collapsible sidebar, top bar, homepage dashboard, view routing |
| Themes | ✅ Done | Light / Dark UI, three board presets, custom HEX square colours |
| Engine & board | ✅ Done | Legal-move hints, promotion, castling, en passant, async Stockfish analysis with auto-detection |
| Opening page | ✅ Done | Catalan introduction, "ideal setup" board, six chapters with progress bars and Start / Resume / Practice again |
| Training screen | ✅ Done | Learn levels (move by move with ideas) and quiz levels (play the moves from memory) |
| Mistakes in a quiz | ✅ Done | 1st mistake: a hint (or the piece to move is highlighted); 2nd: the correct move is shown and you play it |
| Second chance | ✅ Done | Positions you missed come back at the end of a quiz, to check you understood |
| Passing a level | ✅ Done | 85 % first-try accuracy opens the next level; one mistake is always allowed in a short quiz |
| Chapter 1: Closed Catalan | ✅ Done | 8 levels on two branches (7...Nbd7 up to 14.Qe2, 7...b6 up to 13.b4), with your plan at the end of each line |
| Responsive board | ✅ Done | Board, panel and text grow with the window and the sidebar |
| Piece pictures | ✅ Done | Merida pieces on every board (see Credits) |
| Content import | ✅ Done | `pgn_import.py` turns a Lichess study (PGN) into a chapter file; every move is checked |
| User profiles | ✅ Done | Create and switch profiles; Guest mode saves nothing |
| Saved settings | ✅ Done | Theme and board colours restored per profile |
| Progress tracking | ✅ Done | Results per level; a Guest keeps progress until the app closes |
| Mistake tracking | ✅ Done | Every wrong move stored with its position, ready for spaced repetition |
| Review schedule & daily review | 🔜 Next | Review days shown in quizzes drive the schedule; the "Daily Revised" card drills due positions |
| Engine-approved alternatives | 📋 Planned | Moves Stockfish rates almost as good as the book move count as correct |
| Chapters 2–6 | 📋 Planned | Open Catalan, and the Catalan against the King's Indian, Semi-Slav, Grünfeld and other defences |
| Profile editing & online links | ⏸ Postponed | Rename profile, link Chess.com / Lichess accounts |

---

## Architecture

| Layer | Files | Responsibility |
|---|---|---|
| Interface | `chesscoach_flet.py`, `opening_hub_view.py`, `level_view.py`, `board_pieces.py`, `flet_compat.py` | Windows, themes, dialogs, the opening page, the training screen, board pieces |
| Training logic | `level_trainer.py`, `opening_hub.py` | Validates chapters and moves, runs learn / quiz levels, scores accuracy, unlocks levels; no UI, no database |
| Curriculum | `catalan_opening.json`, `catalan_ch01_v2.json` | The opening page (intro, setup, chapter list) and chapter 1 (lines, ideas, hints, levels) |
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

Today:
1. A wrong move is recorded and becomes due for review immediately.
2. Answering that position correctly on the first try moves it back **1 day**, then **3 days**.
3. The third correct answer in a row marks it as **mastered**.
4. Any new mistake on the position resets its streak.

Next: the review days a quiz shows you will drive this schedule: after one mistake **tomorrow and in 7 days**,
after two mistakes **tomorrow, in 3 days and in 7 days**.

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
129 unit tests: database (38), levels and quizzes (48), study import (23), opening page data (5), board layout (9) and piece pictures (6).

---

## Changelog

### 2026-11-17 — Training experience
- Catalan opening page: introduction, ideal-setup board and six chapters; Chapter 1 is ready, the rest are marked "Coming soon".
- New training screen with learn and quiz levels, hints, the correct move after a second mistake, a second-chance round, and progress per level.
- Chapter 1 rebuilt as 8 levels on two Closed Catalan branches, explained in the app's own voice.
- Lichess study importer for new chapters.
- The board, the panel and the text grow with the window.
- Pieces are now Merida pictures on every board (the black pawn no longer shows as an emoji on Windows).
- 91 new unit tests (129 in total).

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
