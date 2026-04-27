"""Centralized config for crawlers, scheduler, agent tools.

Edit values here instead of hunting through individual files.
Imported by crawlers, scripts, and tools — keep this module dependency-free."""

# ---------------------------------------------------------------------------
# Crawl concurrency
# ---------------------------------------------------------------------------
NEWS_PAGE_CONCURRENCY = 5  # Parallel article pages per ticker (crawl_news).
TICKER_CONCURRENCY = 4  # Parallel tickers (analyst & BCTC crawlers).

# ---------------------------------------------------------------------------
# Crawl horizons
# ---------------------------------------------------------------------------
NEWS_LATEST_LIMIT = 15  # Latest N articles per ticker for crawl_news.
ANALYST_MONTHS_BACK = 12  # How far back analyst reports listing covers.
BCTC_YEARS_BACK = 2  # How far back BCTC crawl goes (each ticker).

# ---------------------------------------------------------------------------
# Ticker selection (used by crawlers via load_tickers)
# ---------------------------------------------------------------------------
DEFAULT_MIN_PRIORITY = 3  # 3=VN30, 2=VN100+, 1=HOSE+, 0=all exchanges.

# ---------------------------------------------------------------------------
# Batch / rate-limit
# ---------------------------------------------------------------------------
EXTRACT_BATCH_SIZE = 50  # Rows per extract_financial_metrics run.
GEMINI_API_DELAY = 1  # Seconds between Gemini calls in batch scripts.

# ---------------------------------------------------------------------------
# Tool output caps (token control on the agent side)
# ---------------------------------------------------------------------------
SUMMARY_MAX_LEN = 250  # Sentiment summary cap.
THESIS_MAX_LEN = 400  # Analyst thesis cap.
RISKS_MAX_LEN = 250  # Analyst risks cap.

# ---------------------------------------------------------------------------
# Tool result message prefixes — keep in sync with the agent's system prompt
# rule: 'tool result starts with Lỗi or Không có dữ liệu → báo user, no retry'.
# ---------------------------------------------------------------------------
ERROR_PREFIX = "Lỗi"
EMPTY_PREFIX = "Không có dữ liệu"
