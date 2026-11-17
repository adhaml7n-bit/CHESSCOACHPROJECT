"""
ChessCoach - the board shared by the training and review screens
===============================================================
render_board() draws a position: square colours from the board settings, the
last move and the selected piece highlighted, outlined hint squares, dots
(empty squares) and rings (captures) on the selected piece's legal targets,
coordinates, and the pieces (board_pieces.py). click_square() turns the
player's clicks into a move, so both screens behave the same way.
"""

import chess
import flet as ft

from board_pieces import piece_controls
from flet_compat import align_center, border_all


def click_square(board: chess.Board, selected: int | None, square: int) -> tuple[str | None, int | None]:
    """Handles a click on `square` while `selected` is the selected square (or None).

    Returns (uci, new_selected): uci is the move to play when the click
    completes one (a pawn reaching the last rank becomes a queen), else None;
    new_selected is the square that is selected after the click.
    """
    if selected is not None and square != selected:
        moves = [m for m in board.legal_moves if m.from_square == selected and m.to_square == square]
        if moves:
            move = next((m for m in moves if m.promotion in (None, chess.QUEEN)), moves[0])
            return move.uci(), None
    piece = board.piece_at(square)
    if piece and piece.color == board.turn and square != selected:
        return None, square
    return None, None


def render_board(
    board: chess.Board,
    colors: dict,
    square_size: int,
    *,
    piece_size: int,
    coord_size: int = 10,
    dot_size: int = 16,
    white_bottom: bool = True,
    selected: int | None = None,
    last_move_uci: str | None = None,
    marked: dict | None = None,
    on_square=None,
) -> ft.Container:
    """The board as a Flet control.

    colors       - board colours: light_sq, dark_sq, selected, last_move,
                   hint_sq, legal_dot, legal_capture and the piece colours
    marked       - {square: border width} outlined with hint_sq (hints, shown moves)
    on_square    - called with the square when it is clicked; None = not clickable
    """
    last_squares = set()
    if last_move_uci:
        move = chess.Move.from_uci(last_move_uci)
        last_squares = {move.from_square, move.to_square}
    targets = {}  # square -> True for a capture
    if selected is not None:
        for move in board.legal_moves:
            if move.from_square == selected:
                targets[move.to_square] = board.is_capture(move)
    marked = marked or {}

    rows = []
    for row in range(8):
        rank = 7 - row if white_bottom else row
        cells = []
        for col in range(8):
            file = col if white_bottom else 7 - col
            square = chess.square(file, rank)
            cells.append(_square(board, square, row, col, colors, square_size, piece_size, coord_size, dot_size,
                                 selected, last_squares, marked, targets, on_square))
        rows.append(ft.Row(spacing=0, tight=True, controls=cells))
    return ft.Container(
        border_radius=4,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column(spacing=0, tight=True, controls=rows),
    )


def _square(board, square, row, col, c, size, piece_size, coord_size, dot_size,
            selected, last_squares, marked, targets, on_square) -> ft.Container:
    file, rank = chess.square_file(square), chess.square_rank(square)
    is_light = (file + rank) % 2 == 1
    fill = c["light_sq"] if is_light else c["dark_sq"]
    if square == selected:
        fill = c["selected"]
    elif square in last_squares:
        fill = c["last_move"]
    coord_color = c["dark_sq"] if is_light else c["light_sq"]

    items = []
    if col == 0:
        items.append(ft.Container(left=3, top=1, content=ft.Text(
            str(rank + 1), size=coord_size, weight=ft.FontWeight.BOLD, color=coord_color)))
    if row == 7:
        items.append(ft.Container(right=3, bottom=1, content=ft.Text(
            chess.FILE_NAMES[file], size=coord_size, weight=ft.FontWeight.BOLD, color=coord_color)))
    if square in marked:
        items.append(ft.Container(width=size, height=size, border_radius=4,
                                  border=border_all(marked[square], c["hint_sq"])))

    piece = board.piece_at(square)
    if piece:  # a picture from assets/pieces (glyph as backup)
        items.extend(piece_controls(piece, size, c, glyph_size=piece_size))

    if square in targets:
        if targets[square]:  # ring for a capture
            ring = size - 8
            marker = ft.Container(width=ring, height=ring, border_radius=ring // 2,
                                  border=border_all(4, c["legal_capture"]))
        else:                # dot for an empty square
            marker = ft.Container(width=dot_size, height=dot_size, border_radius=dot_size // 2,
                                  bgcolor=c["legal_dot"])
        items.append(ft.Container(width=size, height=size, alignment=align_center(), content=marker))

    return ft.Container(
        width=size,
        height=size,
        bgcolor=fill,
        on_click=(lambda e, s=square: on_square(s)) if on_square else None,
        content=ft.Stack(width=size, height=size, controls=items),
    )
