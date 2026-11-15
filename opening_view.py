import chess
import flet as ft
from opening_trainer import load_and_validate_chapter, OpeningSession
from flet_compat import pad_symmetric, border_all, align_center
from database import LINE_CORE, LINE_REVIEW

PIECE_SYMBOLS = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}


def make_pill_button(label: str, on_click, bg_color: str = "#2563EB") -> ft.Container:
    """Creates a clean clickable button compatible with all Flet versions."""
    return ft.Container(
        content=ft.Text(label, color="#FFFFFF", size=13, weight=ft.FontWeight.W_600),
        bgcolor=bg_color,
        padding=pad_symmetric(horizontal=14, vertical=8),
        border_radius=8,
        on_click=on_click,
    )


def build_opening_trainer_view(
    page: ft.Page,
    json_path: str = "catalan_ch01.json",
    on_back=None,
    db=None,
) -> ft.Control:
    """Builds the interactive Opening Trainer UI ready to embed inside chesscoach_flet.py.

    db is the app's ChessCoachDB. It is optional so this file still runs on its own;
    without it (or in Guest mode) the trainer works but nothing is saved.
    """
    chapter = load_and_validate_chapter(json_path)
    session = OpeningSession(chapter)
    chapter_id = chapter["chapter_meta"]["chapter_id"]

    def save(method_name: str, *args):
        """Calls a ChessCoachDB method; a database problem never stops the lesson.
        The db object (not the user id) is kept, so switching account is seen at once."""
        if db is None:
            return
        try:
            getattr(db, method_name)(*args)
        except Exception as exc:  # e.g. the file is locked for longer than the timeout
            print(f"[ChessCoach] Could not save progress ({method_name}): {exc}")

    def current_line_id() -> str:
        """Which line this run counts for in line_progress."""
        if session.mode == "review":
            return LINE_REVIEW
        if session.mode == "branch":
            return session.active_branch_id
        return LINE_CORE

    state = {"selected_sq": None}

    board_grid = ft.Column(spacing=0)
    mode_badge = ft.Text(
        f"Mode: CORE TRUNK — {chapter['chapter_meta']['chapter_title']}",
        size=14,
        weight=ft.FontWeight.BOLD,
        color="#93C5FD",
    )
    status_title = ft.Text("Your turn (White)", size=18, weight=ft.FontWeight.BOLD, color="#F8FAFC")
    idea_text = ft.Text(chapter["chapter_meta"]["description"], size=14, color="#E2E8F0")
    explanation_text = ft.Text("Click a White piece, then click its target square.", size=13, color="#94A3B8")
    accuracy_text = ft.Text("Accuracy: 100%", size=13, weight=ft.FontWeight.W_600, color="#34D399")

    feedback_box = ft.Container(
        content=ft.Column([status_title, idea_text, explanation_text], spacing=8),
        bgcolor="#1E293B",
        padding=16,
        border_radius=12,
        border=border_all(1, "#334155"),
    )

    def render_board():
        board = chess.Board(session.current_fen)
        rows = []
        for rank in range(7, -1, -1):
            cells = []
            for file in range(8):
                sq = chess.square(file, rank)
                is_light = (rank + file) % 2 == 1

                if sq == state["selected_sq"]:
                    bg = "#BACA44"
                else:
                    bg = "#EEEED2" if is_light else "#769656"

                piece = board.piece_at(sq)
                symbol = PIECE_SYMBOLS[piece.symbol()] if piece else ""

                cells.append(
                    ft.Container(
                        content=ft.Text(symbol, size=34, color="#111827"),
                        width=60,
                        height=60,
                        bgcolor=bg,
                        alignment=align_center(),
                        on_click=lambda e, s=sq: handle_square_click(s),
                    )
                )
            rows.append(ft.Row(cells, spacing=0))
        board_grid.controls = rows

    def handle_square_click(clicked_sq: int):
        if session.is_complete:
            return

        board = chess.Board(session.current_fen)
        clicked_piece = board.piece_at(clicked_sq)

        # Select or switch between White pieces smoothly
        if clicked_piece and clicked_piece.color == chess.WHITE:
            state["selected_sq"] = clicked_sq
            render_board()
            page.update()
            return

        if state["selected_sq"] is None:
            return

        uci_move = chess.square_name(state["selected_sq"]) + chess.square_name(clicked_sq)
        state["selected_sq"] = None
        res = session.submit_move(uci_move)

        if res["status"] == "correct":
            if res["first_try"]:
                save("record_correct", chapter_id, session.active_branch_id, res["ply"])
            if res["is_complete"]:
                save("save_line_result", chapter_id, current_line_id(), res["accuracy"])

            feedback_box.border = border_all(1, "#22C55E")
            status_title.value = f"✔ {res['played_san']}"
            status_title.color = "#4ADE80"
            idea_text.value = f"Idea: {res['strategic_idea']}"
            explanation_text.value = res["explanation"]
            accuracy_text.value = f"Accuracy: {res['accuracy']}%"

            if res["opponent_moves"]:
                opp = res["opponent_moves"][-1]
                explanation_text.value += f"\n\nOpponent played {opp['san']}: {opp['explanation']}"

            if res["is_complete"]:
                takeaways = "\n• ".join(chapter["review_phase"]["summary_takeaways"])
                status_title.value = "★ Line Completed!"
                idea_text.value = f"Final Accuracy: {res['accuracy']}%"
                explanation_text.value = f"Key Takeaways:\n• {takeaways}"

        elif res["status"] == "incorrect":
            # fen = position before the move, played_san = the wrong move.
            save("record_mistake", chapter_id, session.active_branch_id, res["ply"], res["fen"], res["played_san"])

            feedback_box.border = border_all(1, "#F59E0B")
            status_title.value = f"✘ Not the book move ({res['played_san']})"
            status_title.color = "#FBBF24"
            idea_text.value = f"Hint: {res['hint']}"
            explanation_text.value = "Try another move for White."

        else:
            feedback_box.border = border_all(1, "#EF4444")
            status_title.value = "Illegal Move"
            status_title.color = "#F87171"
            idea_text.value = res["message"]

        render_board()
        page.update()

    def switch_mode(mode_name: str, branch_id: str | None = None):
        state["selected_sq"] = None
        feedback_box.border = border_all(1, "#334155")
        status_title.color = "#F8FAFC"

        if mode_name == "core":
            session.start_core()
            mode_badge.value = f"Mode: CORE TRUNK — {chapter['chapter_meta']['chapter_title']}"
            status_title.value = "Core Trunk Started (White)"
            idea_text.value = chapter["chapter_meta"]["description"]
            explanation_text.value = "Play the main Catalan move order."
        elif mode_name == "branch" and branch_id:
            session.start_branch(branch_id)
            b_title = next(b["branch_title"] for b in chapter["branches"] if b["branch_id"] == branch_id)
            mode_badge.value = f"Mode: BRANCH — {b_title}"
            status_title.value = f"Branch Loaded: {b_title}"
            idea_text.value = "Black deviated from the main line. Find White's response."
            explanation_text.value = "Select your piece on the board."
        elif mode_name == "review":
            session.start_review()
            mode_badge.value = "Mode: REVIEW TEST"
            status_title.value = "Review Mode — Full Line"
            idea_text.value = "Complete the entire trunk with minimal errors."
            explanation_text.value = "Your accuracy is being tracked."
            accuracy_text.value = "Accuracy: 100%"

        render_board()
        page.update()

    # Mode selector buttons (Core + Dynamic Branches + Review)
    mode_buttons = [
        make_pill_button("Core Trunk", lambda e: switch_mode("core"), "#2563EB"),
    ]
    for br in chapter.get("branches", []):
        b_id = br["branch_id"]
        mode_buttons.append(
            make_pill_button(br["branch_title"], lambda e, bid=b_id: switch_mode("branch", bid), "#475569")
        )
    mode_buttons.append(make_pill_button("Review Mode", lambda e: switch_mode("review"), "#059669"))

    if on_back:
        mode_buttons.insert(0, make_pill_button("← Back", lambda e: on_back(), "#334155"))

    render_board()

    right_panel = ft.Column(
        [
            mode_badge,
            accuracy_text,
            ft.Row(mode_buttons, wrap=True, spacing=8),
            feedback_box,
        ],
        width=420,
        spacing=14,
    )

    return ft.Container(
        content=ft.Row(
            [board_grid, right_panel],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=28,
        ),
        padding=24,
        bgcolor="#0F172A",
        expand=True,
    )


if __name__ == "__main__":
    def main(page: ft.Page):
        page.title = "ChessCoach — Opening Trainer"
        page.bgcolor = "#0F172A"
        page.window.width = 1020
        page.window.height = 620
        page.add(build_opening_trainer_view(page))

    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
    