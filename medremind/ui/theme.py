"""Design tokens do MedRemind (Clinical Clarity refinado)."""
from __future__ import annotations

import flet as ft

# Cores -----------------------------------------------------------------------
BG = "#F6F7FB"
SURFACE = "#FFFFFF"
SURFACE_2 = "#EEF1F7"
LINE = "#E3E7EF"
LINE_STRONG = "#C9D1E0"
INK = "#121826"
INK_2 = "#4A5468"

PRIMARY = "#0B5BD3"
PRIMARY_DARK = "#0A3F94"
PRIMARY_TINT = "#E6EEFC"
PRIMARY_ON_DARK = "#D6E3FB"

SUCCESS = "#0F7A3A"
SUCCESS_INK = "#0F5A2C"
SUCCESS_TINT = "#E3F4E9"

WARN = "#C26A00"
WARN_INK = "#8A4B00"
WARN_TINT = "#FFF1DE"

DANGER = "#B42318"
DANGER_TINT = "#FDE8E6"

STREAK = "#B45309"
AVATAR_BG = "#FDE7D4"
AVATAR_INK = "#7A3A00"

DARK = "#0E1A33"

# Tipografia --------------------------------------------------------------------
# O Flutter não sintetiza bem pesos de fonte, então cada peso é uma família.
FONTS = {
    "Jakarta": "fonts/PlusJakartaSans_400Regular.ttf",
    "Jakarta500": "fonts/PlusJakartaSans_500Medium.ttf",
    "Jakarta600": "fonts/PlusJakartaSans_600SemiBold.ttf",
    "Jakarta700": "fonts/PlusJakartaSans_700Bold.ttf",
    "Jakarta800": "fonts/PlusJakartaSans_800ExtraBold.ttf",
}


def family(weight: int) -> str:
    return "Jakarta" if weight <= 400 else f"Jakarta{min(800, max(500, round(weight / 100) * 100))}"


def T(value: str, size: float = 15, w: int = 400, color: str = INK, **kw) -> ft.Text:
    """Atalho para texto com a fonte e o peso corretos."""
    return ft.Text(value, size=size, font_family=family(w), color=color, **kw)


def theme() -> ft.Theme:
    return ft.Theme(color_scheme_seed=PRIMARY, font_family="Jakarta", use_material3=True)


# Espaçamentos e raios ------------------------------------------------------------
GUTTER = 20
R_CARD = 22
R_BUTTON = 16
R_ICON = 14

SHADOW = ft.BoxShadow(blur_radius=18, spread_radius=-10, offset=ft.Offset(0, 6),
                      color=ft.Colors.with_opacity(0.14, INK))
