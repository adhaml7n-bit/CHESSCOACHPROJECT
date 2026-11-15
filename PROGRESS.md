# ChessCoach — Development Progress

ChessCoach is a desktop chess trainer built with **Python**, **Flet**, **python-chess** and **SQLite**.
It teaches openings move by move, remembers the moves you get wrong, brings them back for review,
and includes a 2D board with **Stockfish** analysis.

**Status:** Phase 1 complete (persistence wired into the app) · **Last updated:** 2026-11-15

---

## Features

| Area | Status | Details |
|---|---|---|
| App shell | ✅ Done | Collapsible sidebar, top bar, homepage dashboard, view routing |
| Themes | ✅ Done | Light / Dark UI, three board presets, custom HEX square colours |
| Engine & board | ✅ Done | Legal-move hints, promotion, castling, en passant, async Stockfish analysis with auto-detection |
| Opening trainer | ✅ Done | Catalan Chapter 1: main line, 2 branches, review mode, per-run accuracy |
| User profiles | ✅ Done | Create and switch profiles; Guest mode saves nothing |
| Saved settings | ✅ Done | Theme and board colours restored per profile |
| Progress tracking | ✅ Done | Lines completed and best accuracy per line |
| Mistake tracking | ✅ Done | Every wrong move stored with its position, ready for spaced repetition |
| Catalan Hub screen | 🔜 Next | Chapter overview with progress bars and Start / Resume buttons |
| Daily review | 📋 Planned | Drill your own recorded mistakes on a spaced-repetition schedule |
| Richer training loop | 📋 Planned | Guided discovery → branch sparring → hint-free mastery test |
| Profile editing & online links | ⏸ Postponed | Rename profile, link Chess.com / Lichess accounts |

---

## Architecture

| Layer | Files | Responsibility |
|---|---|---|
| Interface | `chesscoach_flet.py`, `opening_view.py`, `flet_compat.py` | Windows, themes, dialogs, board rendering |
| Training logic | `opening_trainer.py` | Validates moves and tracks lines and accuracy; no UI, no database |
| Curriculum | `catalan_ch01.json` | Opening theory: moves, ideas, hints, branches |
| Persistence | `database.py` | Profiles, settings, progress and mistakes in a local SQLite file |

Design principles:
- **Theory and user data are kept apart.** Lessons live in JSON files; only the user's own data goes into the database.
- **Guest mode is enforced in one place.** The database layer refuses every write for a guest, so no screen can save by accident.
- **Derived values are computed, not stored.** Chapter completion is calculated from saved line results.
- **Schema changes use migrations,** so updates never wipe a user's progress.

---

## Spaced repetition

1. A wrong move is recorded and becomes due for review immediately.
2. Answering that position correctly on the first try moves it back **1 day**, then **3 days**.
3. The third correct answer in a row marks it as **mastered**.
4. Any new mistake on the position resets its streak.

Repeating the same line many times in one day does not count as mastery.

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
.venv\Scripts\python.exe -m unittest test_database -v
```
38 unit tests cover the database layer: schema, guest mode, profiles, settings, progress, mistakes and thread safety.

---

## Changelog

### 2026-11-15 — Persistence & profiles
- Added the SQLite database layer with 38 unit tests.
- Profiles with a top-bar account button; Guest mode by default.
- Appearance settings saved and restored per profile.
- Opening trainer now records mistakes, first-try answers and completed lines.
- Accuracy is now scored separately for every run.
- Light mode now uses a light sidebar.
- Compatibility layer for Flet 0.28 and 1.0+.
