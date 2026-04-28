"""Sanity tests for config.py — guard against accidental edits that break
downstream assumptions (e.g. setting concurrency to 0, blanking the message
prefixes the agent prompt depends on).
"""

import config


class TestConcurrencyDefaults:
    def test_news_page_concurrency_is_positive(self):
        assert config.NEWS_PAGE_CONCURRENCY > 0

    def test_ticker_concurrency_is_positive(self):
        assert config.TICKER_CONCURRENCY > 0

    def test_concurrency_within_reasonable_bounds(self):
        # Sanity ceiling — too high and we get rate-limited by CafeF.
        assert config.NEWS_PAGE_CONCURRENCY <= 20
        assert config.TICKER_CONCURRENCY <= 20


class TestHorizonDefaults:
    def test_news_limit_positive(self):
        assert config.NEWS_LATEST_LIMIT > 0

    def test_analyst_months_back_reasonable(self):
        assert 1 <= config.ANALYST_MONTHS_BACK <= 60

    def test_bctc_years_back_reasonable(self):
        assert 1 <= config.BCTC_YEARS_BACK <= 30


class TestPriorityRange:
    def test_default_priority_in_range(self):
        # 0=all, 1=HOSE, 2=VN100, 3=VN30 per scripts/load_tickers semantics.
        assert 0 <= config.DEFAULT_MIN_PRIORITY <= 3


class TestBatchAndRateLimit:
    def test_extract_batch_positive(self):
        assert config.EXTRACT_BATCH_SIZE > 0

    def test_gemini_delay_non_negative(self):
        assert config.GEMINI_API_DELAY >= 0


class TestOutputCaps:
    def test_caps_are_positive(self):
        assert config.SUMMARY_MAX_LEN > 0
        assert config.THESIS_MAX_LEN > 0
        assert config.RISKS_MAX_LEN > 0

    def test_caps_within_token_safety(self):
        # Each cap is a per-character slice; agent context budget caps at
        # several thousand chars per tool call. 2000 is a generous ceiling.
        assert config.SUMMARY_MAX_LEN <= 2000
        assert config.THESIS_MAX_LEN <= 2000
        assert config.RISKS_MAX_LEN <= 2000


class TestMessagePrefixes:
    def test_error_prefix_starts_with_loi(self):
        # The agent's system prompt explicitly checks for tool result strings
        # starting with 'Lỗi'. Don't rename without updating the prompt too.
        assert config.ERROR_PREFIX == "Lỗi"

    def test_empty_prefix_starts_with_khong_co_du_lieu(self):
        # Same contract — the prompt rule for empty results.
        assert config.EMPTY_PREFIX == "Không có dữ liệu"

    def test_prefixes_are_non_empty_strings(self):
        assert isinstance(config.ERROR_PREFIX, str) and config.ERROR_PREFIX
        assert isinstance(config.EMPTY_PREFIX, str) and config.EMPTY_PREFIX
