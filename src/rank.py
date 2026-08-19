from __future__ import annotations

import re

from divar import Listing

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_FAKE_KM = {0, 11111, 111111, 12345, 123456, 1111111}


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    normalized = text.translate(_DIGIT_MAP)
    digits = re.sub(r"[^\d]", "", normalized)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def listing_year(title: str) -> int:
    text = title.translate(_DIGIT_MAP)
    match = re.search(r"13[7-9]\d|14[0-1]\d", text)
    if match:
        return int(match.group(0))
    match = re.search(r"(?:مدل\s*)?(\d{2,4})", text)
    if not match:
        return 0
    value = int(match.group(1))
    if 70 <= value <= 99:
        return 1300 + value
    if 0 <= value <= 20:
        return 1400 + value
    return 0


def _km(listing: Listing) -> int:
    km = parse_int(listing.mileage)
    if km is None or km in _FAKE_KM:
        return 900_000
    return km


def pick_best(listings: list[Listing], count: int = 5) -> list[Listing]:
    ranked = sorted(
        listings,
        key=lambda item: (
            0 if item.image_url else 1,
            -listing_year(item.title),
            _km(item),
            parse_int(item.price) or 10**12,
        ),
    )
    return ranked[: max(1, count)]
