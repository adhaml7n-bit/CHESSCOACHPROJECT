# CLAUDE.md — ChessCoach Project Context & Engineering Guide

## 1. Project Overview
**ChessCoach** (`CHESSCOACHPROJECT`) is a modular, interactive 2D chess training, opening repertoire trainer, and Stockfish analysis desktop application built in Python with **Flet** and **python-chess**.

- **Developer / Owner:** Adham Kloop
- **Repository Status:** Initialized with Git and published to GitHub (`main` branch).
- **Environment:** Windows, Python 3.x virtual environment (`.venv`).

---

## 2. Architecture & Current Directory Structure
The project strictly follows **separation of concerns** across four layers (GUI Shell, Training Logic, Static Curriculum Data, and Dynamic SQLite Persistence):

```text
CHESSCOACHPROJECT/
├── CLAUDE.md                 # This architectural & progress context file for Claude Code
├── .gitignore                # Ignores .venv/, __pycache__/, *.pyc, *.zip, stockfish*/, .vscode/, *.db (the `*.db` entry was added on 2026-11-15)
├── chesscoach_flet.py        # Main Flet application shell, themes, sidebar, Stockfish board & view router
├── opening_trainer.py        # Pure python-chess logic engine for opening move validation & FEN progression
├── opening_view.py           # Flet UI component for the interactive opening training board
├── catalan_ch01.json         # Static curriculum JSON for Closed Catalan (Chapter 1)
├── database.py               # [NOT CREATED YET] planned SQLite persistence layer (ChessCoachDB)
├── chesscoach.db             # [NOT CREATED YET] local SQLite database (will be gitignored)
└── stockfish*/               # Local Stockfish UCI binaries (gitignored, auto-detected at runtime)
```

---

## 3. Completed Milestones (What Has Been Built & Verified)

1. **Main Application Shell (`chesscoach_flet.py`):**
   - Built around `ChessCoachFletApp` with collapsible left sidebar (`☰` Hamburger menu), top bar, and `ft.Stack`-based view routing (`homepage_view`, `engine_view`, `opening_trainer_view`).
   - Full **Light/Dark UI Theme** switching and **Board Square Color** customization (Classic Wood, Modern Blue, Tournament Green, and custom HEX).
   - Non-blocking async **Stockfish UCI** engine integration with automatic local binary detection (`_auto_detect_stockfish`) and 1-ply fallback evaluation.
   - Homepage dashboard with categorized training cards (`Daily Revised`, `Daily Puzzles`, `Opening`, `Middle Game`, `End Game`). The first card in the `Opening` section is wired to **"Catalan Opening"** (`Chapter 1 • Ready`) and opens the trainer view cleanly.

2. **Opening Training Engine & View (`opening_trainer.py` + `opening_view.py`):**
   - `opening_trainer.py` parses chapter JSON files, tracks `core_trunk` and `branches`, validates SAN/UCI moves via `python-chess`, and computes FEN states.
   - `opening_view.py` exposes `build_opening_trainer_view(page, json_path, on_back)` to render the interactive 2D training board, move feedback, hints, and `← Back` navigation to the homepage.

3. **Standardized Opening Curriculum (`catalan_ch01.json`):**
   - Formatted, validated JSON schema containing:
     - `chapter_meta` (`chapter_id: "catalan_ch01"`, `opening_name: "Catalan Opening"`, `chapter_title: "An Introduction to the Closed Catalan"`, `player_color: "white"`, `description`).
     - `core_trunk` (16 plies / 8 full moves with `strategic_idea`, `explanation`, and `hint`).
     - `branches` (`branch_01`: Early Queenside Fianchetto `7...b6`; `branch_02`: Consolidation Maneuver `8...Re8`).
     - `review_phase` (`min_accuracy_to_pass: 85`, `key_checkpoint_plies`, `summary_takeaways`).

4. **SQLite Persistence Layer (`database.py`) — DESIGN ONLY, NOT BUILT YET:**
   - Status (verified 2026-11-15): the file does not exist and no code references `sqlite` or `ChessCoachDB`. The notes below are the planned design, to be written from scratch.
   - Planned `ChessCoachDB` managing `chesscoach.db` with 4 relational tables:
     - `users`: `user_id`, `username` (unique, case-insensitive, passwordless profile), `display_name`, `chesscom_username`, `lichess_username`, `created_at`, `updated_at`.
     - `user_settings`: `user_id`, `ui_mode`, `board_preset`, `light_sq_color`, `dark_sq_color`, `engine_time_limit`.
     - `chapter_progress`: `progress_id`, `user_id`, `opening_id`, `chapter_id`, `status`, `completion_pct`, `best_accuracy`, `completed_branches_json`, `attempts_count`, `last_played_at`.
     - `move_mistakes`: `mistake_id`, `user_id`, `opening_id`, `chapter_id`, `branch_id`, `ply`, `fen`, `expected_san`, `last_wrong_san`, `hint_text`, `wrong_count`, `streak_correct`, `mastered`, `last_mistake_at`.
   - **Ephemeral Guest Mode (`current_user_id = None`):** When `db.is_guest` is `True`, all write methods (`save_chapter_progress`, `record_mistake`, `save_user_settings`, `update_user_profile`) silently return `False` without modifying disk records.

---

## 4. Active Roadmap & Next Tasks (In Execution Order)

### Phase 1: Create `database.py`, then wire it into the Application UI (Immediate Next Step)
0. **Write `database.py` from scratch** following the design in Milestone 4 (the file does not exist yet).
1. **Optional Future-Proof Columns in `database.py`:**
   - Before live integration, optionally add `chesscom_rating INTEGER NOT NULL DEFAULT 0`, `lichess_rating INTEGER NOT NULL DEFAULT 0`, and `last_api_sync TEXT NOT NULL DEFAULT ''` to the `users` table in `database.py` (delete any test `chesscoach.db` afterward so the schema recreates cleanly).
2. **User Profile, Guest Mode & External Links in `chesscoach_flet.py`:**
   - Instantiate `self.db = ChessCoachDB()` inside `ChessCoachFletApp.__init__`.
   - Add a **User Profile / Account Switcher** button in the top bar (next to `Settings`) showing either `"👤 Guest (Not Saving)"` or the active user's `display_name`.
   - Build a modal dialog allowing the user to:
     - Switch to **Guest Mode** (ephemeral session, zero disk writes).
     - Select an existing user or create a new user by `username` (no password required).
     - Edit their profile (`username`, `display_name`) and link external **Chess.com** and **Lichess** usernames.
   - Persist `Settings` changes (`ui_mode`, `board_preset`, `light_sq_color`, `dark_sq_color`) to `user_settings` when logged in as a registered user, and load them automatically on login.
3. **Record Progress & Mistakes During Training (`opening_view.py` & `opening_trainer.py`):**
   - Pass `db: ChessCoachDB` into `build_opening_trainer_view(...)`.
   - Call `db.record_mistake(...)` whenever the player makes an incorrect move.
   - Call `db.save_chapter_progress(...)` upon completing lines/chapters so accuracy and completion percentages are persisted.

### Phase 2: Build the Approved "Catalan Hub" Screen (`catalan_hub_view.py`)
- **Design Approved by User:** Instead of jumping directly from the Homepage `"Catalan Opening"` card into the raw board, open an intermediate **Catalan Hub** view (`catalan_hub_view.py`):
  - **Top Section:** Header (`"CATALAN OPENING — CHAPTERS & THEORY"`), concise 3–4 line strategic overview (`1.d4 Nf6 2.c4 e6 3.g3...`), and Strategic Focus highlights (`g2-Bishop pressure, Kingside safety, Central control`).
  - **Right Visual Card:** `"IDEAL CATALAN SETUP"` visual diagram/board preview highlighting the `g2` bishop and `h1-a8` diagonal pressure.
  - **Bottom Section (`"CHAPTERS TO MASTER"`):** Scrollable chapter cards dynamically reading metadata from `catalan_ch01.json` and progress from `ChessCoachDB`:
    - Displays chapter title, scope (`8 Moves • 2 Branches • Target Accuracy: 85%`), completion progress bar (e.g., `40% COMPLETE`), and smart action button (`START` / `RESUME TRAINING →` / `PRACTICE AGAIN`) that launches `opening_view.py`.
    - Includes upcoming chapter placeholders (e.g., `Chapter 2: The Open Catalan` with `COMING SOON` badge).

### Phase 3: Future Expansion
- **Unified 3-Stage Training Loop:** Combine (1) Guided Visual Discovery (board arrows/square highlights before moving), (2) Adaptive Randomized Branch Sparring (engine surprises the player with branches mid-line), and (3) Hintless Mastery Gauntlet.
- **Spaced Repetition Review (`Daily Revised`):** Wire the Homepage `"Daily Revised"` card to `db.get_due_mistakes()` so users drill their actual recorded mistakes.
- **More Content & Public API Sync:** Add Chapter 2+ JSON files and optional public API sync for Chess.com / Lichess ratings and PGNs.

---

## 5. Critical Technical Rules & Constraints
1. **Cross-Version Flet Compatibility:** Always preserve and use the compatibility helpers at the top of `chesscoach_flet.py` (`_pad_symmetric`, `_pad_only`, `_border_all`, `_align_center`, `_open_dialog`, `_close_dialog`, and `ft.run(main)` / `ft.app(target=main)`) so the app runs cleanly on both **Flet 1.0+** and **Flet 0.28.x**.
2. **Theme Synchronization:** Any new view (`catalan_hub_view.py`, profile dialogs, updated `opening_view.py`) must respect the active `UI_THEMES[self.ui_mode]` (`light` / `dark`) and custom board square colors (`self.light_sq_color`, `self.dark_sq_color`).
3. **Static vs. Dynamic Data:** Never hardcode opening moves in Python or store static lesson text in SQLite. Keep opening theory in `*.json` files and user state/progress/mistakes in `chesscoach.db`.
4. **Guest Mode Integrity:** Never write to `chesscoach.db` when `db.is_guest` is `True`.

---

## 6. Known Issues (verified 2026-11-15)
1. `database.py` is missing (see Milestone 4 and Phase 1, step 0).
2. `opening_view.py` calls `ft.Padding.symmetric`, `ft.Border.all` and `ft.Alignment(0, 0)` directly instead of the compatibility helpers in `chesscoach_flet.py`, so it may break on Flet 0.28.x (violates Rule 1). Works on the installed Flet 1.1.2.
3. `opening_view.py` uses hardcoded colors and ignores `UI_THEMES` and the custom board square colors (violates Rule 2).