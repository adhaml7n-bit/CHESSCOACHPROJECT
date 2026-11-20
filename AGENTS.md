# AGENTS.md — ChessCoach Subagent Architecture

To minimize context bloat and prevent hallucinations, divide work across these 6 specialized subagents (via `define_subagent` / `invoke_subagent`). Each agent must stay strictly within its assigned files and verify changes with `.venv\Scripts\python.exe -m unittest`.

| Subagent | Scope (Allowed Files) | Forbidden |
|---|---|---|
| `curriculum-builder` | `sources/*`, `catalan_opening.json`, `catalan_ch01_v2.json`, `catalan_ch02.json` | Never hand-edit generated chapter JSONs (always regenerate from `sources/`); no UI or DB edits |
| `chess-logic` | `level_trainer.py`, `opening_trainer.py`, `opening_hub.py`, `engine_judge.py`, `pgn_import.py`, and their `test_*.py` | No `flet` or `sqlite3` imports; no UI or DB edits |
| `ui-flet` | `chesscoach_flet.py`, `level_view.py`, `review_view.py`, `opening_hub_view.py`, `board_view.py`, `board_pieces.py`, `flet_compat.py`, and their `test_*.py` | No raw SQL or chess state-machine logic |
| `db-persistence` | `database.py`, `test_database.py` | Must use `?` parameterized SQL; no UI or trainer logic |
| `qa-verifier` | Read-only + `unittest` runner (`test_*.py`), `git status`/`diff` | Never edit production `.py` or `.json` files |
| `security-auditor` | Read-only defensive security audit across the repo (see `.agents/skills/security-auditor/SKILL.md`) | Never modify files or generate exploit payloads; report findings + defensive fixes only |
