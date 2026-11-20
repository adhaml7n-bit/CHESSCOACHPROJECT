---
name: security-auditor
description: >-
  Defensive cybersecurity audit checklist for ChessCoach. Use when reviewing the
  codebase for leaked API keys/secrets, SQL injection, unsafe subprocess/Stockfish
  calls, path traversal, or .gitignore leaks.
---

# Defensive Security Auditor Checklist (ChessCoach)

Strictly read-only defensive review. Report exact `file:line`, severity (`Critical` / `High` / `Medium` / `Low` / `Info`), risk explanation, and defensive remediation.

## Audit Categories

1. **Secrets & API Key Exposure**
   - Scan Python, JSON, Markdown, and config files for hardcoded API keys, tokens, passwords, or private credentials.
   - Verify `.gitignore` excludes `*.db`, `.venv/`, `.env`, `CLAUDE.md`, `sources/`, and any local secret files.

2. **SQL Injection & Database Safety (`database.py`)**
   - Verify all `sqlite3` queries use `?` parameter placeholders.
   - Flag any f-strings, `%` formatting, `.format()`, or `+` concatenation inside SQL strings.

3. **Subprocess & External Binary Safety (`engine_judge.py`, `chesscoach_flet.py`, `pgn_import.py`)**
   - Check `subprocess` / `chess.engine` calls for `shell=True`, untrusted arguments, or unvalidated binary paths.

4. **Path Traversal & Unsafe Deserialization (`opening_hub.py`, `pgn_import.py`, `board_pieces.py`)**
   - Check file path construction from user/data inputs for `..` traversal or absolute path escapes.
   - Confirm no `pickle`, `eval()`, `exec()`, or `yaml.load()` without `SafeLoader`.
