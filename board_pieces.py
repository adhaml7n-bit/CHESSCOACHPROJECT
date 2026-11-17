"""
ChessCoach - chess pieces for every board
=========================================
The training screen, the opening hub and the Engine & Board screen all draw
their pieces through piece_controls(). A piece is a picture from
assets/pieces/<set>/ (wK.svg ... bP.svg; see the README there for the author
and the license). The Unicode glyph is the backup: it is drawn when the
pictures are not installed, and Flet shows it if a picture fails to load.

The app starts Flet with assets_dir=ASSETS_DIR so the pictures can be found.
"""

import os
from functools import lru_cache

import chess
import flet as ft

from flet_compat import align_center, pad_only

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
PIECE_SET = "merida"  # Armando Hernandez Marroquin, GPLv2+ (see assets/pieces/merida/README.md)

# Backup glyphs. U+FE0E asks for the text form of the black pawn, although
# Windows may still draw ♟ as a coloured emoji (the reason for the pictures).
PIECE_GLYPHS = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟︎", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}


def piece_asset(piece: chess.Piece, piece_set: str = PIECE_SET) -> str:
    """The picture of a piece inside the assets folder, e.g. 'pieces/merida/bP.svg'."""
    color = "w" if piece.color == chess.WHITE else "b"
    return f"pieces/{piece_set}/{color}{piece.symbol().upper()}.svg"


@lru_cache(maxsize=None)
def has_piece_images(piece_set: str = PIECE_SET) -> bool:
    """True when all 12 pictures of the set are installed."""
    return all(
        os.path.isfile(os.path.join(ASSETS_DIR, piece_asset(chess.Piece(piece_type, color), piece_set)))
        for piece_type in chess.PIECE_TYPES
        for color in chess.COLORS
    )


def _glyph(piece: chess.Piece, size: int, colors: dict, shadow: bool) -> list:
    symbol = PIECE_GLYPHS[piece.symbol()]
    color = colors["piece_white"] if piece.color == chess.WHITE else colors["piece_black"]
    glyph = ft.Text(symbol, size=size, color=color)
    if not shadow:
        return [glyph]
    return [
        ft.Container(alignment=align_center(), padding=pad_only(left=2, top=3),
                     content=ft.Text(symbol, size=size, color=colors["piece_shadow"])),
        ft.Container(alignment=align_center(), content=glyph),
    ]


def piece_controls(piece: chess.Piece, square_size: int, colors: dict,
                   glyph_size: int | None = None, piece_set: str = PIECE_SET) -> list:
    """Controls that draw `piece` on a square of square_size pixels; add them to
    the square's Stack. colors needs piece_white, piece_black and piece_shadow
    (used by the backup glyph). glyph_size defaults to 60 % of the square."""
    size = glyph_size or round(square_size * 0.6)
    if has_piece_images(piece_set):
        return [ft.Container(
            width=square_size,
            height=square_size,
            alignment=align_center(),
            content=ft.Image(
                src=f"/{piece_asset(piece, piece_set)}",
                width=square_size,
                height=square_size,
                error_content=_glyph(piece, size, colors, shadow=False)[0],
            ),
        )]
    return [ft.Container(width=square_size, height=square_size, content=control)
            for control in _glyph(piece, size, colors, shadow=True)]
