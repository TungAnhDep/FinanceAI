"Tests for database/period.py — period parsing helpers."

import pytest

from database.period import period_to_date, quarter_to_date


# period_to_date — string form like 'Q4/2025' / 'CN/2025'


class TestPeriodToDate:
    @pytest.mark.parametrize(
        "period, expected",
        [
            ("Q1/2025", "2025-03-31"),
            ("Q2/2025", "2025-06-30"),
            ("Q3/2025", "2025-09-30"),
            ("Q4/2025", "2025-12-31"),
            ("CN/2025", "2025-12-31"),
            ("CN/2020", "2020-12-31"),
            ("Q1/1999", "1999-03-31"),
        ],
    )
    def test_valid_periods(self, period, expected):
        assert period_to_date(period) == expected

    @pytest.mark.parametrize(
        "bad_input",
        [
            None,
            "",
            "Q4-2025",  # wrong separator
            "Q4/abc",  # non-numeric year
            "Q5/2025",  # invalid quarter (5 in string form is reserved for CN)
            "Q0/2025",  # quarter must be 1-4
            "X1/2025",  # not Q or CN prefix
            "garbage",
            "/2025",  # missing head
            "Q1",  # missing year
            "Q/2025",  # empty quarter number
        ],
    )
    def test_invalid_returns_none(self, bad_input):
        assert period_to_date(bad_input) is None

    def test_dates_are_iso_sortable(self):
        """Critical property: ISO-date strings sort chronologically the same way
        the underlying dates do. This is the bug the lex-sort fix relied on."""
        periods = ["Q4/2024", "CN/2025", "Q1/2025", "Q4/2025", "Q2/2024"]
        keys = [period_to_date(p) for p in periods]
        sorted_pairs = sorted(zip(keys, periods), reverse=True)
        ordered_periods = [p for _, p in sorted_pairs]
        # 2025-12-31 (CN/2025 == Q4/2025), then Q1/2025, then Q4/2024, then Q2/2024
        assert ordered_periods[0] in ("CN/2025", "Q4/2025")
        assert ordered_periods[1] in ("CN/2025", "Q4/2025")
        assert ordered_periods[2] == "Q1/2025"
        assert ordered_periods[3] == "Q4/2024"
        assert ordered_periods[4] == "Q2/2024"


# ---------------------------------------------------------------------------
# quarter_to_date — separate-int form from the BCTC API
# ---------------------------------------------------------------------------


class TestQuarterToDate:
    @pytest.mark.parametrize(
        "quarter, year, expected",
        [
            (1, 2025, "2025-03-31"),
            (2, 2025, "2025-06-30"),
            (3, 2025, "2025-09-30"),
            (4, 2025, "2025-12-31"),
            (5, 2025, "2025-12-31"),  # 5 = annual
            (1, 2018, "2018-03-31"),
        ],
    )
    def test_valid_quarter_year(self, quarter, year, expected):
        assert quarter_to_date(quarter, year) == expected

    @pytest.mark.parametrize("year", [0, None])
    def test_zero_or_missing_year_returns_none(self, year):
        assert quarter_to_date(1, year) is None
        assert quarter_to_date(5, year) is None

    @pytest.mark.parametrize("invalid_quarter", [0, 6, 7, -1, 99])
    def test_invalid_quarter_returns_none(self, invalid_quarter):
        # Quarter must be 1-5; everything else is None
        assert quarter_to_date(invalid_quarter, 2025) is None


# ---------------------------------------------------------------------------
# Cross-check: both functions agree for matching inputs
# ---------------------------------------------------------------------------


class TestConsistency:
    @pytest.mark.parametrize(
        "string_period, quarter, year",
        [
            ("Q1/2025", 1, 2025),
            ("Q2/2024", 2, 2024),
            ("Q4/2023", 4, 2023),
            ("CN/2025", 5, 2025),
        ],
    )
    def test_two_forms_produce_same_date(self, string_period, quarter, year):
        assert period_to_date(string_period) == quarter_to_date(quarter, year)
