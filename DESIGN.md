# ChessCoach - Training Experience Design (draft v6, 2026-11-17)

> Owner-approved design decisions for the next big feature (training experience). Written on 2026-11-16 in a claude.ai chat and copied here so Claude Code can read it. No code for this feature exists yet.

Principle: **understanding first, then memorization.**

## 0. Release scope (owner's decision)
- **Chapters follow Black's defences** (owner's design of 2026-11-17, from his hub picture; replaces "one chapter per branch"): 1 Closed Catalan, 2 Open Catalan, 3 Catalan against the King's Indian, 4 against the Semi-Slav, 5 against the Grünfeld, 6 against other defences. A chapter's branches are lines inside its file (chapter 1: `main` = 7...Nbd7, `line_2` = 7...b6), taught level by level.
- Version 1 ships **chapter 1 (Closed Catalan)**; chapters 2-6 show "Coming soon" on the hub, and the hub says so honestly. The source study (`sources/`) already has material for all six.
- The app states honestly (e.g. a note on the opening hub) that this release covers the main branches and the rest are coming soon.
- Do not chase perfection in the first release.
- Data format must make adding a new branch = adding a new JSON file, and adding a level = adding an entry to `levels`, without touching code. Remaining chapter cards show "Coming Soon".
- Workflow (owner's decision 2026-11-17): content is built in **Lichess studies** and imported with `pgn_import.py`; nobody types chapter JSON by hand any more. No PDFs.
  - One study = one chapter (one branch). One study chapter = one learn level; the importer adds a quiz level after each learn level (default `on_mistake` rules: hint +1/+7, correct move +1/+3/+7).
  - Each study chapter holds its full line from `1.d4`; its levels teach and test only the moves that are new compared with the study chapters before it (a chapter that continues a line extends it; one that leaves it becomes a new line).
  - Comments: first line = the move's idea, a second line = explanation, text after `Hint:` = hint (White moves only), comment before move 1 = the level intro. Comments may be written in Arabic; Claude translates them to English after the import.
  - The importer checks every move with python-chess, drops every header except study/chapter names and orientation (no names, ECO, links or the author's account), drops `[%cal]`/`[%eval]` commands and side variations (with a warning), cuts moves after move 14 (with a warning), and never overwrites a file without `--force`.
  - The owner downloads the study PGN and either runs `.venv\Scripts\python.exe pgn_import.py study.pgn catalan_chXX.json` or sends the PGN to Claude. Claude reviews the result with the owner before it is used. The chat template (branch name, full line, one idea per move) still works for small changes.

## 0b. Source data (owner's decision 2026-11-17)
- `sources/lichess_catalan_3evqn8kF.pgn`: a full public Lichess study (https://lichess.org/study/3evqn8kF), 64 chapters (Open Catalan 22, Closed Catalan 15, Slav, QID, KID, Benoni, ...). Kept whole as raw data for the future; v1 uses only what each chapter needs.
- When a chapter is designed, the owner picks its study chapters; the importer then needs: chapter selection (`--chapters`), `--moves-only` (the author's comments are not ours to copy), and side variations turned into extra levels. Not built yet.
- Note: the study's move order is `1.d4 d5 2.c4 e6 3.Nf3 Nf6 4.g3`, ours is `1.d4 Nf6 2.c4 e6 3.g3`; decide per chapter. Several lines go past move 14 (cut on import).
- The file carries the study author's account (Annotator header) and comments; keep it out of the public GitHub repository.

## 1. Opening hub (per opening, e.g. Catalan)
Built 2026-11-17 from the owner's picture (`opening_hub_view.py`, data in `catalan_opening.json`, loader `opening_hub.py`):
- **Top left:** title "CATALAN OPENING", subtitle "CHAPTERS & THEORY", the introduction (in the app's voice) and "Strategic focus".
- **Top right:** card "IDEAL CATALAN SETUP": a board with the Closed Catalan setup after `6.O-O`; the g2-bishop's square is filled and the long diagonal f3-a8 is outlined (no arrow, for Flet compatibility).
- **Below:** "CHAPTERS TO MASTER" and the honest release note, then one card per chapter. A ready chapter shows "N levels • N branches • Target accuracy", a "% COMPLETE" badge (levels passed / levels), a progress bar and START / RESUME TRAINING → / PRACTICE AGAIN. A chapter whose "file" is null shows COMING SOON with placeholder lines; adding it later only means setting its file.
- The homepage Catalan card opens the hub; the training screen's back button returns to it with the progress updated. A Guest's progress is kept in the app's memory until it closes.

## 1b. Where deep explanation lives (owner's decision)
- Opening chapters stay LEAN: skeleton of the line, the idea of each move, deviations. Early levels may use short/general explanations (they cover what players already know).
- Detailed explanations (what is truly worth explaining, not what everyone knows) go to the homepage card **"Opening Middle Game"** (currently a placeholder in `chesscoach_flet.py`, subtitle: "Transitions from opening theory into dynamic middlegame play").
- Chapters link to their deep-dive lessons (planned field: `deep_dive_ref`) with a small "See deeper explanation" card at the end of a level/chapter.
- Strategic-plan questions ("choose the plan") belong mainly to Opening Middle Game, not to the opening chapter levels.

## 2. Chapter flow
Each chapter (one branch) has **5 to 10 levels**, as many as the branch needs. It starts from the base line and goes deeper step by step. Levels **alternate learn and quiz** (owner's decision 2026-11-17):

| Level | Type | Content |
|---|---|---|
| 1 | learn | Show the branch and explain its ideas, move by move; player presses "Next" |
| 2 | quiz | Test level 1: player plays the moves from memory, no explanations shown |
| 3 | learn | A sub-branch of the same branch, or the line extended by more moves |
| 4 | quiz | Test the new material |
| 5, 7, 9 | learn | Extend the branch further / another sub-branch |
| 6, 8, 10 | quiz | Test the new material |

- Mistake handling in quiz levels: see section 3.
- **End of level**: a small optional "Use engine" card appears (see section 5).
- After the last level the branch is mastered and the next chapter opens.
- **Passing a quiz** (owner's decision 2026-11-17): first-try accuracy of at least `min_accuracy_to_pass` (85%). On top of that, `chapter_meta.allowed_mistakes` (1) first-try mistakes always pass: in a short quiz the mark is lowered to (questions − 1) / questions when that is lower (3 questions -> 67%). A quiz still needs at least one move right on the first try. Quizzes with 7 or more questions are unchanged (85% already allows one mistake). The second-chance round does not count.
- Each level is one entry in the chapter JSON's `levels` list (`level`, `type`, `title`, `line_id`, `from_ply`, `to_ply`; quiz levels add `question_type`, `show_explanations`, `on_mistake`). Moves live in `lines` (e.g. `"main"`), each with `strategic_idea`, `explanation`, `hint` (hints on White moves only).
- **Format extension (2026-11-17, for the Closed Catalan expansion; owner chose about 40 levels over 62 one-line levels):**
  - A line can be a branch of another line: `{"from_line": "line_2", "after_ply": 17, "moves": [...]}`; on load it becomes a full line (the parent's first moves are copied with their texts).
  - Texts belong to a position and its move: a line that reaches the same position (shared start or transposition) gets the texts it leaves empty, so each move is explained once.
  - Validation refuses a chapter where the same position has two different moves for the player (a quiz accepts one move per position).
  - A level can list several `parts` instead of one `line_id` / `from_ply` / `to_ply`: each part is a line range with an optional `intro` (shown at its start) and `key_ideas` (shown at its last move). Learn levels show a start page for each part; quiz levels jump to each part's position and play the opponent's first moves.
- **Plan: levels 9-40 (approved 2026-11-17; all built the same day by `sources/build_closed.py`, 28 lines; 15.Naxc4 in the 5...a5 line and 13.e3 after 12...Re8 were added with Stockfish and approved).** 9 learn / 10 quiz: 7...b6 line to 16.Rac1. 11 learn: 9...Nbd7 10.e5 ... 16.h4. 12 learn: 13...a5, and 9...Bb7 in the 7...Nbd7 line (transposes to level 11). 13 quiz: 11-12. 14 learn: 9...dxe4, 8...b5. 15 learn: 8...Re8 to 16.Nb5 (16.Nb5 added with Stockfish). 16 quiz: 14-15. 17-18: 6...b6. 19-20: 6...Ne4 7.Nc3 f5 (two White moves about half a pawn below the engine's choice; kept as the study's). 21-22: 4...Bb4+ 5.Bd2 Be7 with 9...Nbd7 (and 12...Nxe5). 23-24: the same with 9...Bb7 and 9...Ba6. 25-26: 5...Bxd2+. 27-28: 5...Bxd2+ with 8...c5 (10...cxd4, 10...b6, 10...c4). 29-30: 5...a5 6.Nf3 dxc4 (with 14...Nxe2+ and 12...f6). 31-32: 5...a5 6.Nf3 O-O 7.Qb3. 33-34: 5...Bd6 to 14.Rfc1 (with 10...Qxf6). 35-36: 4...Nbd7 / ...Bd6. 37-38: 4...g6 (with 8...Nxe5). 39-40: 4...Ne4 with 8.e3. Left out: White alternatives in the same position (6.Qc2, 6.b3, 7.b3, 7.Nc3, 8.Bf4, 14.cxd5, 8.Nxe4), 14.Qxa7?? (a trap, taught as a warning), the early ...dxc4 lines of study ch. 29 (Open Catalan), and study lines that stop on Black's move without a White answer.

### Older level ladder (draft from 2026-11-16, superseded by the learn/quiz table above)
Kept only as a list of question-type ideas that later quiz levels may use; not a fixed level order.
| Level | Learns | Question type |
|---|---|---|
| 1 | Core structure and idea of each move | Choose the move |
| 2 | Pawn structure, key squares | "Why this move?" (pick the idea) |
| 3 | Move order / transposition risks | "What if the order is reversed?" |
| 4 | First common opponent deviation | Choose the reply |
| 5 | Tactical motifs in the line | Find the shot |
| 6 | Common opponent mistakes | Find the refutation |
| 7 | Deeper main line | Choose the move |
| 8 | Strategic plans in final positions | Choose the plan (-> mostly Opening Middle Game) |
| 9 | Mixed review of all levels | No hints, shuffled |
| 10 | Free play from the final position | Play vs engine (limited strength) |

### Chapter 1: `catalan_ch01_v2.json` (branch `6...c6`, 8.Nbd2) - in progress
Line: `1.d4 Nf6 2.c4 e6 3.g3 d5 4.Bg2 Be7 5.Nf3 O-O 6.O-O c6 7.Qc2 Nbd7 8.Nbd2 b6 9.e4` (17 plies, checked with python-chess).
| Level | Type | Status |
|---|---|---|
| 1 | learn: the setup up to 9.e4 | Written and approved by the owner (2026-11-17) |
| 2 | quiz: play the 9 White moves from memory | Written (2026-11-17) |
| 3 | learn: `9...dxc4 10.Nxc4 Bb7 11.Rd1` (main line of study chapter 24, "Closed Catalan (main ideas)") | Owner's decision 2026-11-17: follow the study; explanations and hints written by Claude in the app's voice. Replaces the earlier `9...dxe4` line (in git history; also a side line of study chapter 24) |
| 4 | quiz: plies 1-21 (levels 1 and 3 together), `retry_mistakes: true` | Owner's decision 2026-11-17: a wrong move is fixed in place (hint, then the correct move, which the player plays); every missed position comes back once at the end of the level ("second chance") to check the mistake is understood. Accuracy counts the first pass only |
| 5 | learn: `11...c5 12.e5 Nd5 13.Nd6 Nb4 14.Qe2` (end of the line, move 14) | 2026-11-17: the study stops at 11.Rd1, so Claude chose the continuation with Stockfish as a second opinion (12.e5 best, about +0.1; 12.d5 drops a pawn; 13.Qe4 avoided because it leads into a piece sacrifice past move 14). Owner to review. The 11.Rd1 explanation now says "answer ...c5 with e4-e5" instead of d4-d5 |
| 6 | quiz: plies 22-27 (level 5: `12.e5`, `13.Nd6`, `14.Qe2`; `11...c5` is played for the player), `retry_mistakes: true` | 2026-11-17. One first-try mistake is allowed (`allowed_mistakes: 1`), so 2 of 3 (67%) passes; two mistakes mean repeating the level. Engine note: `13.Qe4` (slightly better) and `14.Qc3` (about equal) count as mistakes until accepted alternatives exist (DESIGN.md section 5, step F) |
| 7 | learn on a second line `line_2`: `7...b6 8.Nbd2 Bb7 9.e4 Na6 10.a3 c5 11.exd5 exd5 12.dxc5 Nxc5 13.b4` (plies 14-25), with key ideas | 2026-11-17, owner's choice: study chapter 26 "Closed Catalan, mainline", moves only, cut after 13.b4. The study's order `1.d4 d5 2.c4 e6 3.Nf3 Nf6 4.g3` reaches the same position after `7.Qc2`, so `line_2` uses our order for moves 1-7. Every move checked with Stockfish (all within about 0.25 of the engine's best; +0.17 after 13.b4). Theme: Black ends up with an isolated d5-pawn |
| 8 | quiz on `line_2`, plies 14-25 (level 7: `8.Nbd2 9.e4 10.a3 11.exd5 12.dxc5 13.b4`; `7...b6` is played for the player), `retry_mistakes: true` | 2026-11-17. 6 questions, so the one-mistake rule sets the mark to 83.3% (5 of 6 passes). Engine note: `8.Rd1` / `8.b3` (slightly better than `8.Nbd2`), `10.cxd5` / `10.Rd1` and `11.cxd5` count as mistakes until accepted alternatives exist (step F) |
| 9+ | | Next content |

The old `catalan_ch01.json` (16 plies ending with `8.Rd1`, branches `7...b6` and `8...Re8`) is untouched and still used by the app until the level code exists. The `8.Rd1 b6 9.b3 Bb7 10.Nc3` material from the owner's PDF (`closed-catalan-e08-9b3-10nc3-monograph.pdf`) belongs to another branch/chapter later; its page-4 line was corrected by the owner to `10...Rc8 11.e4 Nxe4 12.Nxe4 dxe4 13.Qxe4 Nf6 14.Qe1`.

- **Chapter 2, Open Catalan (owner's request 2026-11-17, plan 2026-11-18).** Source: the study's chapters 2-22 and the ...dxc4 lines of chapter 29, rewritten in our order by a helper agent and re-checked (`sources/open_lines.py`, O1-O100). The owner accepted the helper's White moves: 5.Nf3 against 4...dxc4 (not 5.Qa4+), 7.Qc2 against 6...dxc4 (not 7.Ne5), 8.a4 after 7.Qc2 a6, chapter 1's moves wherever the chapters meet, and the move most study lines use elsewhere unless Stockfish says it is clearly worse; lines where the study's White move loses (14.Nc6, 16.N1c3, 15.Rd1) are left out. 44 lines remain. Plan, about 40 levels: 1-4 the 7.Qc2 a6 8.a4 main line (built 2026-11-18); 5-8 the same with 10...Nbd7, 10...a5, 8...Nc6 and 7...Bd7 (8.Qxc4 added with Stockfish; built 2026-11-18); 9-13 7...b5 8.a4 (8...bxa4; 8...b4 9.Nfd2 with 9...c6 and 9...Nd5, one learn level each; built 2026-11-18); 14-17 4...dxc4 5.Nf3 a6 6.O-O Nc6 (9.b3 cxb3 10.axb3: White stays a pawn down for open lines; 11...O-O and 11...Nb4, with 13.Na3 added with Stockfish; built 2026-11-18); 18-19 5...a6 6.O-O b5 (a knight for two pawns; built 2026-11-18); 20-24 5...c5 (O44 cut at 13.Bxb7, O47 at 9.Qxc4, no added moves; built 2026-11-18); 25-27 5...Nc6 (built 2026-11-18); 28-31 5...b5 6.a4 c6 7.Ne5, first half: O57-O59 (built 2026-11-18); 32-35 the second half: O61, O62, O64, O69 (built 2026-11-18); 36-39 5...c6: O70-O73 (built 2026-11-19); 40-43 5...Bb4+ 6.Bd2: O75 cut at 16.Nxc4 and O77 cut at 14.a3 (built 2026-11-19); 44-45 5...Be7 and 5...Bd7: O83-O84 (built 2026-11-19); 46-49 4...Nbd7 5.Nf3 dxc4 6.O-O (first half): O89 + added 9.Nxd8, O92, O93, O99 (built 2026-11-19); and 50-51 4...Nbd7 5.Nf3 dxc4 6.O-O c5 7.Na3: O96, O97, O98 (built 2026-11-19 — all 51 levels / 42 lines complete; Day-7 purpose questions next). A line that stops on Black's move gets one Stockfish move, named as an addition in its batch, or is cut back to White's last move. Each text batch is fact-checked by an independent checker agent before the owner sees it (batch 1: 8 near-truths found and fixed, about 150 claims confirmed).

## 3. Mistakes, hints, and spaced review
In-session (same position), quiz levels show no explanations:
- 1st wrong answer -> **show the hint**; the position enters review with days **+1, +7**. A move without a written hint gets an automatic one: the piece that must move is highlighted on the board (board colour `hint_sq`) (Claude's proposal 2026-11-17, owner may still change it).
- 2nd wrong answer (same position, same session) -> **show the correct move** (owner's decision 2026-11-17, replaces "re-explain the idea"); the review becomes days **+1, +3, +7**.
- The rule is stored per level in the chapter JSON (`on_mistake` list: `wrong_attempt`, `action`, `review_days`), so it can change without code. First used in `catalan_ch01_v2.json` level 2.

Review schedule (replaces the old +1 / +3 / mastered-at-streak-3 rule in `database.py`, `MASTERY_STREAK=3`):
- **One mistake**: Day +1 (no hint), then Day +7 (purpose multiple-choice question).
- **Two mistakes (owner's decision)**: gets ONE EXTRA review day (no hint) in addition to the schedule above. Confirmed spacing: +1, +3, +7 (never two consecutive review days).
- Day +7 question: **multiple-choice "what is the purpose of this variation / move?"** (understanding check).
- After a successful Day +7 review the position is **mastered and finished**. NO maintenance reviews (owner's decision: the player is expected to face real opponents with the line).
- Intervals should live in a config list (e.g. `REVIEW_INTERVALS`), not hard-coded. Existing 38 tests (`test_database.py`) must be updated in a separate step/commit. A DB migration (`PRAGMA user_version`) may be needed; never delete `chesscoach.db`.
- **Implemented 2026-11-17 (step E, owner's go-ahead):** schema v2 adds `review_days` (the plan, e.g. `1,7`) and `mastered_at` to `move_mistakes`. Days are counted in **local calendar days from the day of the mistake** (owner confirmed this reading over "gaps between reviews"); "tomorrow" starts at local midnight. A first-try answer on a due day moves to the next day of the plan, never earlier than tomorrow (a late review does not repeat the same day); after the last day the position is mastered. A new mistake restarts the plan. The quiz passes its on_mistake `review_days` to `record_mistake`; the default plans are `ONE_MISTAKE_DAYS` / `TWO_MISTAKES_DAYS` in `database.py`. Old rows keep their due dates with the plan `1,3,7`; rows the old rule had mastered keep `mastered_at`. The day-7 multiple-choice "purpose" question was added the same day (next item).
- **Day-7 purpose question, built 2026-11-17 (owner's choices):** (1) on the last review of a position's plan, the player first finds the move as on every review day; after a first-try move, "Why do you play 9. e4?" follows with three answers (one right, two wrong, shuffled). Both right = mastered. (2) A wrong answer marks the choices (right ✓, chosen ✗), shows the move's explanation and keeps the position at its last review: it comes back in **3 days** with both questions (`postpone_review`, `PURPOSE_RETRY_DAYS`). (3) Every White move of chapter 1 has a question (20 positions). A wrong move on day 7 skips the question: the plan restarts as usual. After the answer the player presses "Next position" (no timed jump), so there is time to read. Format: each player move may carry `"purpose": {"answer": "...", "wrong": ["...", "..."]}`; a position shared by two lines writes it once. Claude wrote the texts; every factual claim behind a wrong answer (e.g. "13.Nd6 protects e5", "after 3.g3 ...Bb4+ is impossible") was checked false with python-chess, and answers that were near-truths were replaced (13.b4 does free b2 for the dark bishop; ...bxc5 would leave hanging pawns). The owner approved all 20 questions as written and ran the feature in the real app (2026-11-17; a test database with backdated day-7 reviews, the real `chesscoach.db` untouched). **Extended the same day to the whole of chapter 1:** after levels 9-40 were built, the 121 new White moves got their questions in 4 approved batches, checked the same way; all 141 White-move positions now have one (the tests require it).

## 4. Daily review card
- The homepage "Daily Revised" card (currently a placeholder) shows pending mistakes/reviews due today (`db.get_due_mistakes()`). No maintenance items.
- **Built 2026-11-17** (`review_view.py`): the card's badge shows "N due today" / "Nothing due"; it opens the Daily review, which asks the due positions of every ready chapter one after another (a position shared by two lines is asked once and updates both rows), with the quiz rules (hint, then the correct move to play). After a first-try answer it says "Next review: tomorrow / in N days (...)" or "Mastered!". The done card shows first-try answers, positions mastered today and the next review date; a Guest is told nothing is saved. Positions whose lesson changed (fen no longer matches) or from chapters the app no longer opens are skipped.

## 5. Stockfish as assistant (never overrides the lesson)
Book/author content is the source of truth. Engine lines carry no human idea, so the engine is a *second opinion*, not a teacher.
1. Hidden during Learn and Quiz (no eval, arrows or hints from engine before answering).
2. After an answer that differs from the book move: compare eval loss.
   - Loss below **50 cp** (owner-approved threshold, configurable): **"off-book but acceptable"** - no review penalty, prompt to return to the studied line.
   - Larger loss: real mistake -> review system.
3. **End-of-level "Use engine" card** (owner's decision): after finishing a level, a small optional card offers engine analysis of that level's positions (eval + best line, clearly labeled as engine opinion; highlights positions where the engine differs from the book).
4. Level 10 (where a chapter has it): play vs engine at limited strength (UCI_LimitStrength / UCI_Elo).
All engine work runs in a background thread (UI must not freeze); reuse `engine_time_limit`.

**Implemented 2026-11-17 (step F, owner's go-ahead)** in `engine_judge.py` (logic, no UI) and `ScreenBase` (level_view.py):
- A quiz or review move that is legal but not the lesson's move is checked before it counts (`peek()` on the sessions counts nothing). The engine compares both moves in one search (`multipv=2`, `root_moves=[book, played]`), scores from the side to move. Loss ≤ `MAX_LOSS_CP` (50, configurable in engine_judge.py) → "Good move: 13. Qe4 … Find the lesson's move: no penalty" with the engine's numbers; no hint, no mistake recorded, the lesson's move afterwards still counts as first try. Otherwise the usual hint / correct-move rules. Without Stockfish, or if it fails, the move is judged as before.
- The panel shows "Checking your move with the engine…" while the search runs (`asyncio.to_thread`, like the Engine & Board screen); the board is locked meanwhile.
- `EngineAssistant` uses the app's engine and engine lock; the time limit is the user's `engine_time_limit`, clamped to 0.1–2 s.
- Level-done card: "Use engine (optional)" → "Analyse with Stockfish" checks each of the player's moves in the level: "✓ 12. e5: the engine agrees (+0.10)" or "13. Nd6: the engine prefers Qe4 (+0.20 against +0.01)" with the engine line, labelled as a second opinion.
- Verified with real Stockfish: before 13.Nd6, 13.Qe4 is accepted and 13.Qxh7+?? is rejected.
- Not built: level 10 (play against the engine at limited strength); no chapter has a level 10 yet.

## 6. Content
- Source: human sources (the owner's chess books and analyses). Explanations are written originally (not copied from books); the owner (about 2000 Elo) reviews and corrects them.
- Pilot: chapter 1 only, then expand.
- **Branch length** (owner's decision 2026-11-17): the chapters teach the opening, not the middlegame. A branch line is about 8-10 moves long and ends at **move 14 at the latest**. Longer analysis is cut at move 14. **Updated by the owner (2026-11-17, "all Closed Catalan variations from the study, 30-40 levels"):** a line may run to move 15-16 where it needs to, so the player reaches a position that is easy to continue from. Claude proposed the plan (29 study lines rewritten in chapter 1's move order, each checked to reach the study's exact position; White alternatives in the same position left out so every position has one book move) and the first batch of explanations; both wait for the owner's approval before anything goes into the app.
- **No names** (owner's decision 2026-11-17): no player names, game references or named gambits in the JSON or the explanations. Branches are named by their move (e.g. `10...b5`) or by their idea.
- **Voice: the app talks to the player** (owner's decision 2026-11-17). Ideas and explanations are written in the second person: the player's moves use "you / your" ("You take control of the center."), the other side is "your opponent" ("Your opponent stops you from playing e4."). Screen messages follow the same voice ("Your move", "Not quite: ...", "Well done!", "We'll review this position tomorrow and in 7 days."). Claude writes this text when a chapter is prepared; no AI runs inside the app and no API key is shipped. A live AI coach (answering the player's questions, checked against Stockfish and the lesson) is a later, separate feature that would need its own server.
- **Explanations are our own** (2026-11-17): from a Lichess study we take the moves; the explanations are written fresh by Claude in the app's voice and reviewed by the owner, not rewritten from the study author's comments.
- **No evaluations in the content** (owner's decision 2026-11-17): numbers like +0.75 from sources are not copied; the engine supplies evaluations later (section 5).

## 7. Open items
- Exact format of `deep_dive_ref` / Opening Middle Game lessons (decide later; not needed for the pilot).
- Whether the 5th main branch is included in v1 (owner to decide).
- Format of `quiz_options` for multiple-choice quiz levels (not needed yet: quizzes use `play_move`). The day-7 question uses `purpose` (section 3).

## 8. Build order
A. Data format (`intro`, `levels`, `quiz_options`, `purpose_options`; existing per-move `explanation`, `hint`, `strategic_idea` stay) - pilot chapter 1 as `catalan_ch01_v2.json`. **In progress:** `lines` + `levels` format in use, levels 1-3 written (2026-11-17; level 3 has moves only). Logic: `level_trainer.py` (validation, learn / quiz sessions, mistake rules, level unlocking; 35 tests). Import: `pgn_import.py` (Lichess study PGN -> chapter JSON; 23 tests, reproduces chapter 1). Training screen design approved 2026-11-17 (mockup: board left, panel right, level bar on top; after the 2nd mistake the player must play the shown move; next level opens at 85% first-try accuracy; Black's quiz moves play by themselves). Instead of a pilot study, a full public study is kept as source data (section 0b). Training screen `level_view.py` (C + D) written 2026-11-17: level bar, board, learn / quiz / done panels; the Catalan card opens it; the 2nd-mistake arrow is drawn as two highlighted squares (from and to). Layout (owner's request 2026-11-17, "too much wasted area"): the board fills the height left by the header and level bar (squares 48-96 px, multiples of 4) while leaving room for the panel; the panel and all text grow with it up to x1.35; recomputed on window resize / maximize and when the sidebar opens or closes. The start window keeps the original 56 px squares and 360 px panel (`compute_layout` in level_view.py). Pieces (owner's choice 2026-11-17): every board draws the **Merida** SVG pictures (Armando Hernandez Marroquin, GPLv2+; unmodified, from the Lichess repository) through `board_pieces.py`; the files, the GPLv2 text and a README with the source are in `assets/pieces/merida/`, and PROGRESS.md credits the author. Chessnut (Apache 2.0) was tried first; the owner wanted a simpler, classic look. GPL artwork is fine while ChessCoach is free and open source; before a closed or paid release, switch to a permissive set (rhosgfx CC0, shapes CC BY-SA, chessnut Apache 2.0) by changing `PIECE_SET` and the folder. This replaced the Unicode glyphs, because Windows kept drawing ♟ as a purple emoji even with U+FE0E. The glyph stays as a backup (missing files, or a picture that fails to load). A "Piece style" setting would need a new settings column (migration), so it is a later step. Next: owner's run in the real app, then E (review intervals in the database).
   Levels page (owner's request 2026-11-17, with 40 levels: "this level [bar] takes too much area ... all these levels in a window after you enter the Closed Catalan"): the level bar is gone. A chapter opens on its levels page: header (back to the opening hub, chapter title), "N levels · k passed · p% complete" with a progress bar, a Start / Continue button for the first level not passed (or "You've passed all N levels" when done), a one-line legend, and one tile per level in rows that fill the width (at least 160 px each, scaled with the text; 5 per row in the start window). A tile shows the number, Learn / Quiz, its title (two lines at most) and its state: ✓ (with the best accuracy for a quiz), "Next", or 🔒 (cannot be opened). A passed level can always be opened. Inside a level the header is one line: "← All levels", "Level n of N", the type and the title; the freed height goes to the board (`CHROME_HEIGHT` 150 → 110). Possible next step: group the tiles by Black's defence (section names would be chapter data, shown to the owner first).
B. Opening hub screen. **Done 2026-11-17** (section 1).
C. Learn mode.
D. Quiz mode with hints / show correct move.
E. Review: interval config, hint levels, purpose-MCQ, daily review card. **Done 2026-11-17** (the purpose question too, section 3).
F. End-of-level "Use engine" card. **Done 2026-11-17**, together with engine-approved alternative moves in quizzes and reviews (section 5).
G. Opening Middle Game section (deep explanations) - later.

Working rules for this feature: one small step per commit; the owner runs terminal/git commands himself; explain each step to the owner (English is fine in chat since 2026-11-17; Jordanian Arabic was used before), keep project files in English; never begin coding before the owner confirms the step.
