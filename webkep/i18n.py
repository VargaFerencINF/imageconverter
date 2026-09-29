"""Egyszerű, függőségmentes többnyelvűsítés (magyar / angol)."""

from __future__ import annotations

from ._strings import STRINGS

LANGUAGES = {"hu": "Magyar", "en": "English"}
_lang = "hu"


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in LANGUAGES else "hu"


def get_language() -> str:
    return _lang


def tr(key: str, **kwargs: object) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        text = key
    else:
        text = entry[0] if _lang == "hu" else entry[1]
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def _decimal(value: float, decimals: int) -> str:
    text = f"{value:.{decimals}f}"
    return text.replace(".", ",") if _lang == "hu" else text


def fmt_bytes(n: int | float) -> str:
    n = float(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return f"{sign}{int(n)} B"
            return f"{sign}{_decimal(n, 1 if n < 100 else 0)} {unit}"
        n /= 1024
    return f"{sign}{n} TB"  # pragma: no cover


def fmt_percent(ratio: float, decimals: int = 1, signed: bool = False) -> str:
    value = ratio * 100
    text = _decimal(abs(value), decimals)
    if signed:
        return ("-" if value >= 0 else "+") + text + "%"
    return ("-" if value < 0 else "") + text + "%"


def fmt_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        unit = "mp" if _lang == "hu" else "s"
        return f"{_decimal(seconds, 1 if seconds < 10 else 0)} {unit}"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
