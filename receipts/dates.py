"""Partial dates.

Career memories are rarely precise, so dates are stored as partial ISO strings:
"2019", "2019-06" or "2019-06-14". Quarters ("2021-Q3") are accepted and stored as
the first month of the quarter. An entry's `approximate` flag covers "around then".
"""

from __future__ import annotations

import calendar
import re

_PARTIAL = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_QUARTER = re.compile(r"^(\d{4})-?Q([1-4])$", re.IGNORECASE)
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def normalise(value: str | None) -> str | None:
    """Validate a partial date and return its canonical form, or None if empty."""
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() in {"present", "now", "current"}:
        return None
    quarter = _QUARTER.match(value)
    if quarter:
        year, q = quarter.groups()
        return f"{year}-{(int(q) - 1) * 3 + 1:02d}"
    match = _PARTIAL.match(value)
    if not match:
        raise ValueError(f"Date '{value}' should look like 2019, 2019-06, 2019-06-14 or 2019-Q2")
    year, month, day = match.groups()
    if month and not 1 <= int(month) <= 12:
        raise ValueError(f"Date '{value}' has an invalid month")
    if day:
        last = calendar.monthrange(int(year), int(month))[1]
        if not 1 <= int(day) <= last:
            raise ValueError(f"Date '{value}' has an invalid day")
    return value


def lower_bound(value: str) -> str:
    """Earliest full date a partial date could mean."""
    parts = value.split("-")
    return "-".join(parts + ["01"] * (3 - len(parts)))


def upper_bound(value: str) -> str:
    """Latest full date a partial date could mean."""
    parts = value.split("-")
    if len(parts) == 1:
        return f"{parts[0]}-12-31"
    if len(parts) == 2:
        last = calendar.monthrange(int(parts[0]), int(parts[1]))[1]
        return f"{parts[0]}-{parts[1]}-{last:02d}"
    return value


def label(value: str | None) -> str:
    if not value:
        return ""
    parts = value.split("-")
    if len(parts) == 1:
        return parts[0]
    month = _MONTHS[int(parts[1]) - 1]
    if len(parts) == 2:
        return f"{month} {parts[0]}"
    return f"{int(parts[2])} {month} {parts[0]}"


def span_label(start: str | None, end: str | None, approximate: bool = False, open_ended: str = "") -> str:
    """Human label for a range, e.g. 'Jun 2018 – Jan 2019' or 'c. 2021'."""
    if not start:
        return ""
    prefix = "c. " if approximate else ""
    if end and end != start:
        return f"{prefix}{label(start)} – {label(end)}"
    if open_ended:
        return f"{prefix}{label(start)} – {open_ended}"
    return prefix + label(start)
