"""Detect personal data from the *values* in a column (not only from its name).

Used when building previews: columns whose values look like emails, phone numbers, Aadhaar / PAN numbers,
payment cards, IBANs, SSNs or IP addresses are tagged ``pii`` + ``pii:<kind>`` and masked.
Detection is deliberately conservative: a column must have several values and (almost) all of them must match,
and checksummed formats (Aadhaar, cards, IBAN) must pass their checksum, so ordinary IDs are not flagged.
"""
import re
from typing import Any, Callable, Dict, Iterable, List, Optional

MIN_VALUES = 2          # need at least this many non-empty values to decide
MATCH_RATIO = 0.8       # share of non-empty values that must match

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_SSN = re.compile(r"^\d{3}-\d{2}-\d{4}$")
_IPV4 = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
_PHONE_CHARS = re.compile(r"^\+?[\d\s\-().]{10,18}$")

# Verhoeff tables (Aadhaar checksum)
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_ok(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def _luhn_ok(num: str) -> bool:
    total, alt = 0, False
    for ch in reversed(num):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _digits(s: str) -> str:
    return re.sub(r"[\s\-]", "", s)


def _is_aadhaar(s: str) -> bool:
    d = _digits(s)
    return bool(re.fullmatch(r"[2-9]\d{11}", d)) and _verhoeff_ok(d)


def _is_card(s: str) -> bool:
    if not re.fullmatch(r"[\d\s\-]{13,23}", s):
        return False
    d = _digits(s)
    return d.isdigit() and 13 <= len(d) <= 19 and _luhn_ok(d)


def _is_iban(s: str) -> bool:
    v = s.replace(" ", "").upper()
    if not _IBAN.match(v):
        return False
    moved = v[4:] + v[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def _is_phone(s: str) -> bool:
    if not _PHONE_CHARS.match(s):
        return False
    digits = re.sub(r"\D", "", s)
    if not 10 <= len(digits) <= 15:
        return False
    # a bare run of digits is far more likely an ID: require a + or separators, or an Indian-style mobile number
    return s.startswith("+") or bool(re.search(r"[\s\-().]", s)) or (len(digits) == 10 and digits[0] in "6789")


_DETECTORS: Dict[str, Callable[[str], bool]] = {
    # most specific first so e.g. a card number is not reported as a phone number
    "aadhaar": _is_aadhaar,
    "card": _is_card,
    "iban": _is_iban,
    "pan": lambda s: bool(_PAN.match(s.upper())),
    "email": lambda s: bool(_EMAIL.match(s)),
    "ssn": lambda s: bool(_SSN.match(s)),
    "ipv4": lambda s: bool(_IPV4.match(s)),
    "phone": _is_phone,
}


def detect_kind(values: Iterable[Any]) -> Optional[str]:
    """Return the PII kind the values look like (e.g. ``email``), or None."""
    vals: List[str] = []
    for v in values:
        if v is None or isinstance(v, bool):
            continue
        s = str(v).strip()
        if s:
            vals.append(s)
    if len(vals) < MIN_VALUES:
        return None
    for kind, check in _DETECTORS.items():
        hits = 0
        for s in vals:
            try:
                hits += 1 if check(s) else 0
            except (ValueError, OverflowError):
                pass
        if hits / len(vals) >= MATCH_RATIO:
            return kind
    return None
