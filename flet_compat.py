"""
Flet cross-version compatibility helpers (Flet 1.0+ and Flet 0.28.x).

Why this file exists:
Flet 1.0 renamed several things (ft.padding.symmetric -> ft.Padding.symmetric,
ft.border.all -> ft.Border.all, ft.alignment.center -> ft.Alignment.CENTER).
Each helper below checks which spelling the installed Flet has and uses it,
so the same code runs on both versions.
"""
import flet as ft


def pad_symmetric(horizontal: int = 0, vertical: int = 0):
    if hasattr(ft, "Padding") and hasattr(ft.Padding, "symmetric"):
        return ft.Padding.symmetric(horizontal=horizontal, vertical=vertical)
    return ft.padding.symmetric(horizontal=horizontal, vertical=vertical)


def border_all(width: float, color: str):
    if hasattr(ft, "Border") and hasattr(ft.Border, "all"):
        return ft.Border.all(width, color)
    return ft.border.all(width, color)


def align_center():
    if hasattr(ft, "Alignment") and hasattr(ft.Alignment, "CENTER"):
        return ft.Alignment.CENTER
    return ft.alignment.center
