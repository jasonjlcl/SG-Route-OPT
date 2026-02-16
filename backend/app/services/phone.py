from __future__ import annotations

import re


_DIGITS_RE = re.compile(r"\D+")


def normalize_sg_phone(phone: str | None) -> str | None:
    if not phone:
        return None

    raw = phone.strip()
    if not raw:
        return None

    if raw.startswith("+"):
        digits = "+" + _DIGITS_RE.sub("", raw[1:])
    else:
        digits = _DIGITS_RE.sub("", raw)

    if digits.startswith("+65") and len(digits) == 11:
        subscriber = digits[3:]
        if subscriber.isdigit():
            return f"+65{subscriber}"
        return None

    if digits.isdigit() and len(digits) == 8:
        return f"+65{digits}"

    return None


def has_valid_phone(phone: str | None) -> bool:
    return normalize_sg_phone(phone) is not None
