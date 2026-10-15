"""Utilitários de texto em português."""
from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    """Minúsculas, sem acentos e sem espaços duplicados."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def plural(n: float, singular: str, plural_form: str | None = None) -> str:
    word = singular if abs(n) == 1 else (plural_form or singular + "s")
    return f"{n:g} {word}"


def liters(ml: int) -> str:
    return f"{ml / 1000:.1f}".replace(".", ",") + " L"
