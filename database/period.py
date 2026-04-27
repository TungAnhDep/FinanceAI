"""Period parsing helpers for Vietnamese financial reporting periods.

Periods come in two shapes:
- String form: 'Q4/2025' or 'CN/2025' (CN = "Cả năm" / annual)
- Tuple form: separate `quarter` (1-5) and `year` integers from the CafeF BCTC API.
  Quarter 5 means annual.

Both forms convert to the period-end date as ISO 'YYYY-MM-DD'. That value
is suitable for both DB storage (DATE column) and chronological sort keys
(string sort matches date order)."""

from typing import Optional

QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def period_to_date(period: Optional[str]) -> Optional[str]:
    """'Q4/2025' → '2025-12-31', 'CN/2025' → '2025-12-31'.
    Returns None if the input is missing or malformed."""
    if not period or "/" not in period:
        return None
    head, year_str = period.split("/", 1)
    try:
        year = int(year_str)
    except ValueError:
        return None
    if head == "CN":
        return f"{year:04d}-12-31"
    if head.startswith("Q"):
        try:
            quarter = int(head[1:])
        except ValueError:
            return None
        day = QUARTER_END.get(quarter)
        return f"{year:04d}-{day}" if day else None
    return None


def quarter_to_date(quarter: int, year: int) -> Optional[str]:
    """For API payloads that hand quarter and year separately.
    Quarter 5 = annual ('CN' in the string form)."""
    if not year:
        return None
    if quarter == 5:
        return f"{year}-12-31"
    day = QUARTER_END.get(quarter)
    return f"{year}-{day}" if day else None
