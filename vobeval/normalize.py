"""Deterministic parsing and comparison of benefit values.

Portal text writes the same amount many ways ("$25", "25.00", "twenty-five
dollars"). The eval engine compares normalized values so formatting
differences never count as extraction errors.
"""

from __future__ import annotations

import re
from typing import Any

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_ONES_INV = {v: k for k, v in _ONES.items()}
_TENS_INV = {v: k for k, v in _TENS.items()}


def words_to_number(text: str) -> int | None:
    """'twenty-five' -> 25, 'one thousand five hundred' -> 1500."""
    tokens = re.split(r"[\s-]+", text.lower().replace(" and ", " ").strip())
    if not tokens or tokens == [""]:
        return None
    total, current = 0, 0
    for tok in tokens:
        if tok in _ONES:
            current += _ONES[tok]
        elif tok in _TENS:
            current += _TENS[tok]
        elif tok == "hundred":
            current = max(current, 1) * 100
        elif tok == "thousand":
            total += max(current, 1) * 1000
            current = 0
        else:
            return None
    return total + current


def number_to_words(n: int) -> str:
    """25 -> 'twenty-five'. Supports 0..999999."""
    if n < 20:
        return _ONES_INV[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS_INV[tens * 10] + (f"-{_ONES_INV[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES_INV[hundreds]} hundred" + (f" {number_to_words(rest)}" if rest else "")
    thousands, rest = divmod(n, 1000)
    return f"{number_to_words(thousands)} thousand" + (f" {number_to_words(rest)}" if rest else "")


_NONE_WORDS = {"", "n/a", "na", "none", "null", "not applicable", "-", "--", "not listed"}


def _is_none(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in _NONE_WORDS)


def parse_money(value: Any) -> float | None:
    if _is_none(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 2)
    s = str(value).strip().lower()
    if s in {"no charge", "no cost", "free", "$0 (no charge)"}:
        return 0.0
    s = re.sub(r"\b(usd|dollars?|per (session|visit|day))\b", " ", s)
    s = s.replace("$", " ").replace(",", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", s)
    if m:
        return round(float(m.group(1)), 2)
    n = words_to_number(s)
    if n is not None:
        return float(n)
    raise ValueError(f"not a dollar amount: {value!r}")


def parse_percent(value: Any) -> float | None:
    if _is_none(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        return round(v * 100 if 0 < v < 1 else v, 2)
    s = str(value).strip().lower()
    s = re.sub(r"\b(percent|pct|coinsurance|coins)\b", " ", s).replace("%", " ").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", s)
    if not m:
        n = words_to_number(s)
        if n is None:
            raise ValueError(f"not a percentage: {value!r}")
        return float(n)
    v = float(m.group(1))
    if "." in m.group(1) and 0 < v < 1:
        v *= 100
    return round(v, 2)


_TRUE = {"true", "yes", "y", "required", "pa required", "covered", "active", "active coverage", "allowed", "1"}
_FALSE = {"false", "no", "n", "not required", "not covered", "inactive", "terminated", "not allowed", "0"}


def parse_bool(value: Any) -> bool | None:
    if _is_none(value):
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise ValueError(f"not a yes/no value: {value!r}")


def parse_int(value: Any) -> int | None:
    if _is_none(value):
        return None
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().lower().replace(",", "")
    s = re.sub(r"\b(units?|sessions?|visits?|per (day|year)|/day|/yr|/year)\b", " ", s).strip()
    if re.fullmatch(r"\d+", s):
        return int(s)
    n = words_to_number(s)
    if n is None:
        raise ValueError(f"not a number: {value!r}")
    return n


def parse_pos(value: Any) -> list[str] | None:
    if _is_none(value):
        return None
    items = value if isinstance(value, (list, tuple, set)) else re.split(r"[\s,;/]+", str(value))
    out = set()
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        if not item.isdigit():
            raise ValueError(f"not a place-of-service code: {item!r}")
        out.add(item.zfill(2))
    return sorted(out)


def parse_text(value: Any) -> str | None:
    if _is_none(value):
        return None
    return " ".join(str(value).split())


PARSERS = {
    "money": parse_money,
    "percent": parse_percent,
    "bool": parse_bool,
    "int": parse_int,
    "pos": parse_pos,
    "text": parse_text,
}


def parse(kind: str, value: Any) -> Any:
    return PARSERS[kind](value)


def values_equal(kind: str, predicted: Any, gold: Any) -> bool:
    """Exact match after normalization. Money and percent compare numerically."""
    try:
        p, g = parse(kind, predicted), parse(kind, gold)
    except ValueError:
        return False
    if p is None or g is None:
        return p is None and g is None
    if kind in ("money", "percent"):
        return abs(p - g) < 0.005
    if kind == "text":
        return p.lower().rstrip(".") == g.lower().rstrip(".")
    return p == g


def display(kind: str, value: Any) -> str:
    """Human-readable form for the UI."""
    if value is None:
        return "—"
    if kind == "money":
        return f"${value:,.2f}".replace(".00", "")
    if kind == "percent":
        return f"{value:g}%"
    if kind == "bool":
        return "Yes" if value else "No"
    if kind == "pos":
        return ", ".join(value)
    return str(value)


def to_input(kind: str, value: Any) -> str:
    """Value as typed into an edit box."""
    if value is None:
        return ""
    if kind == "money":
        return f"{value:g}"
    if kind == "percent":
        return f"{value:g}"
    if kind == "bool":
        return "yes" if value else "no"
    if kind == "pos":
        return ", ".join(value)
    return str(value)
