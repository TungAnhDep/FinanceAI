"""Tests for pure helpers in tools.py and crawl/crawl_financial_reports.py.

Run with: `pytest tests/test_helpers.py -v`
"""

import math

import pytest

from crawl.crawl_financial_reports import detect_audit_status, to_working_url
from tools import _period_sort_key, _safe_round


# ---------------------------------------------------------------------------
# _safe_round — guards JSON serialization against NaN
# ---------------------------------------------------------------------------


class TestSafeRound:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (1.234, 1.23),
            (1.235, 1.24),  # rounds half-to-even or up depending on float repr
            (0, 0.0),
            (-3.567, -3.57),
            ("4.5", 4.5),  # strings that float() can parse
        ],
    )
    def test_normal_values(self, value, expected):
        result = _safe_round(value)
        assert result is not None
        assert result == pytest.approx(expected, abs=0.01)

    def test_nan_returns_none(self):
        assert _safe_round(float("nan")) is None

    def test_none_returns_none(self):
        assert _safe_round(None) is None

    def test_unparseable_string_returns_none(self):
        assert _safe_round("not a number") is None

    def test_inf_passes_through(self):
        # inf isn't NaN, so _safe_round currently lets it through; document the behavior.
        result = _safe_round(float("inf"))
        assert result == float("inf") or math.isinf(result)

    def test_custom_ndigits(self):
        assert _safe_round(3.14159, ndigits=4) == 3.1416


# ---------------------------------------------------------------------------
# _period_sort_key — wraps period_to_date with a fallback for malformed input
# ---------------------------------------------------------------------------


class TestPeriodSortKey:
    def test_known_periods_sort_chronologically(self):
        periods = ["Q4/2024", "CN/2025", "Q1/2025", "Q4/2025"]
        keys = [_period_sort_key(p) for p in periods]
        # Sorted descending should put 2025-12-31 (Q4/2025 ≡ CN/2025) on top.
        sorted_keys = sorted(keys, reverse=True)
        assert sorted_keys[0] == "2025-12-31"
        assert sorted_keys[-1] == "2024-12-31"

    def test_malformed_period_sorts_to_bottom(self):
        """A None or garbage period should rank below any real date so it
        ends up at the bottom of a reverse-sorted list."""
        keys = [_period_sort_key("Q1/2025"), _period_sort_key(None)]
        # Reverse-sort puts the real date first, garbage last.
        assert sorted(keys, reverse=True)[-1] == "0000-00-00"

    @pytest.mark.parametrize("bad", [None, "", "garbage", "Q5/2025"])
    def test_fallback_string(self, bad):
        assert _period_sort_key(bad) == "0000-00-00"


# ---------------------------------------------------------------------------
# to_working_url — CDN host swap
# ---------------------------------------------------------------------------


class TestToWorkingUrl:
    def test_swaps_new_to_old_cdn(self):
        url = "https://cafefnew.mediacdn.vn/path/file.pdf"
        assert to_working_url(url) == "https://cafef1.mediacdn.vn/path/file.pdf"

    def test_passes_through_unrelated_urls(self):
        url = "https://other.example.com/path/file.pdf"
        assert to_working_url(url) == url

    def test_handles_already_working_url(self):
        url = "https://cafef1.mediacdn.vn/path/file.pdf"
        assert to_working_url(url) == url

    def test_replaces_only_host_substring(self):
        # If 'cafefnew.mediacdn.vn' appears more than once (unusual), swap all.
        url = "https://cafefnew.mediacdn.vn/cafefnew.mediacdn.vn-suffix.pdf"
        result = to_working_url(url)
        assert result.count("cafefnew.mediacdn.vn") == 0
        assert result.count("cafef1.mediacdn.vn") == 2

    def test_empty_string_safe(self):
        assert to_working_url("") == ""


# ---------------------------------------------------------------------------
# detect_audit_status — Vietnamese phrase matching
# ---------------------------------------------------------------------------


class TestDetectAuditStatus:
    @pytest.mark.parametrize(
        "report_type",
        [
            "Báo cáo tài chính hợp nhất năm 2025 (đã kiểm toán)",
            "Báo cáo tài chính công ty mẹ năm 2024 (đã kiểm toán)",
            "ĐÃ KIỂM TOÁN",  # case-insensitive
        ],
    )
    def test_audited_phrases(self, report_type):
        assert detect_audit_status(report_type) == "audited"

    @pytest.mark.parametrize(
        "report_type",
        [
            "Báo cáo tài chính hợp nhất quý 2 năm 2024 (đã soát xét)",
            "Đã Soát Xét",  # case-insensitive
        ],
    )
    def test_reviewed_phrases(self, report_type):
        assert detect_audit_status(report_type) == "reviewed"

    @pytest.mark.parametrize(
        "report_type",
        [
            "Báo cáo tài chính quý 4 năm 2024",  # plain quarterly, no audit tag
            "",
            None,
        ],
    )
    def test_no_audit_status(self, report_type):
        assert detect_audit_status(report_type) is None

    def test_audited_takes_precedence_over_reviewed(self):
        # Should not happen in real CafeF data, but document the precedence.
        weird = "Báo cáo đã kiểm toán và đã soát xét"
        assert detect_audit_status(weird) == "audited"
