# Vietnamese Stock Analysis AI Agent

A LangGraph agent that answers investment questions about Vietnamese-listed stocks. Combines real-time prices, news sentiment, analyst reports, and audited financial statements into structured advice via Gemini 2.5 Flash.

## What it does

Ask in natural language (Vietnamese or English) — the agent picks the right tools, gathers data, and returns a structured response.

```
User:  "Tư vấn FPT trong 1 tháng tới, có nên đầu tư không?"

Agent: → fetches price + SMA/RSI (3-month window)
       → fetches recent news sentiment
       → fetches recent analyst target prices
       → returns FinancialResponse JSON with:
           - summary (3-5 câu kết luận)
           - technical_indicators
           - sentimental
           - analyst_views
           - download_url (Excel of price history)
```

## Features

- **6 specialized tools** the agent can call in parallel:
  - `get_stock_data` — historical OHLCV + SMA/RSI from vnstock
  - `get_company_info` — profile, leadership, shareholders, subsidiaries
  - `get_market_sentiment` — pre-analyzed news from PhoBERT + Gemini summaries
  - `get_analyst_reports` — broker target prices, recommendations, theses
  - `get_financial_reports` — BCTC PDFs (audited annual + quarterly)
  - `get_financial_metrics` — structured numbers (revenue, NPAT, EPS) extracted from BCTC
- **Three crawlers** keeping the data warehouse fresh from CafeF
- **Scheduler** automating the full pipeline (news every 30 min, analyst/BCTC daily)
- **Structured Pydantic output** so frontends get a stable schema
- **FastAPI HTTP API** at `/chat` for integration

## Architecture

```
                    ┌───────────────────┐
                    │   FastAPI /chat   │
                    └────────┬──────────┘
                             │
                ┌────────────▼─────────────┐
                │  LangGraph workflow      │
                │  ┌─────────────────────┐ │
                │  │ gemini_brain        │ │  ← decides tools to call
                │  └──────┬──────────────┘ │
                │         │                │
                │  ┌──────▼──────────────┐ │
                │  │ tool_hands (async)  │ │  ← parallel tool calls
                │  └──────┬──────────────┘ │
                │         │                │
                │  ┌──────▼──────────────┐ │
                │  │ summarizer          │ │  ← structured output
                │  └─────────────────────┘ │
                └─────┬─────────────┬──────┘
                      │             │
              ┌───────▼─────┐ ┌─────▼────────┐
              │ vnstock API │ │  Postgres    │
              │ (live data) │ │  (warehouse) │
              └─────────────┘ └──────▲───────┘
                                     │
                            ┌────────┴─────────┐
                            │  Crawlers + LLM  │
                            │  extractors      │
                            │  (scheduled)     │
                            └──────────────────┘
```

## Prerequisites

- **Python 3.10+** (uses PEP 604 union syntax)
- **PostgreSQL 13+**
- **Tesseract OCR** with Vietnamese + English language packs
- **Playwright browsers** (Chromium)
- **A Google AI Studio API key** for Gemini

### Install Tesseract

- **Windows**: download from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and install both `vie.traineddata` and `eng.traineddata` language packs.
- **macOS**: `brew install tesseract tesseract-lang`
- **Linux**: `apt-get install tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng`

## Setup

```bash
git clone <repo-url>
cd <repo>

# 1. Python deps
pip install -r requirements.txt

# 2. Playwright browsers
playwright install chromium

# 3. Environment variables — copy and fill in:
cp .env.example .env
# Edit .env with your Gemini key and Postgres credentials
```

`.env` template (do **not** commit this file):

```
GOOGLE_API=your_gemini_api_key_here
DB_NAME=Sentiment
DB_USER=postgres
DB_PASSWORD=your_db_password
DB_HOST=localhost
```

```bash
# 4. Initialize Postgres schema
python -m scripts.init_db

# 5. Sync the ticker universe (HOSE/HNX/UPCOM via vnstock)
python -m scripts.sync_tickers
```

## Running

### Start the agent server

```bash
python main.py                      # production-ish
DEV=1 python main.py                # with auto-reload for development
```

API available at `http://localhost:8000`. Test with:

```bash
curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"query": "Tư vấn FPT trong 3 tháng tới"}'
```

### Run the scheduler (automated daily crawls)

```bash
python -m scripts.scheduler
```

The scheduler runs:

| Job | Cadence | What it does |
|---|---|---|
| `crawl_news` | every 30 min | Latest CafeF news per ticker |
| `crawl_analyst` | daily 8:00 | Broker analyst report PDFs |
| `crawl_bctc` | daily 6:00 | BCTC (financial statements) PDFs |
| `analyze_sentiment` | every 15 min | PhoBERT + Gemini summaries on new rows |
| `extract_metrics` | every hour | Structured numbers from BCTC raw text |

For production, register the scheduler with your OS service manager (systemd / Windows Task Scheduler) so it survives reboots.

### Run crawlers / processors manually (one-shot)

```bash
python -m crawl.crawl_news
python -m crawl.crawl_analyst_reports
python -m crawl.crawl_financial_reports

python -m scripts.analyze_sentiment
python -m scripts.extract_financial_metrics
```

## Project structure

```
.
├── agent.py                  # LangGraph workflow + Pydantic response schema
├── tools.py                  # 6 tools the agent calls
├── main.py                   # FastAPI server
├── config.py                 # All concurrency/horizon/output-cap constants
├── requirements.txt
├── pytest.ini
│
├── crawl/
│   ├── crawl_news.py                # CafeF news (Playwright + OCR)
│   ├── crawl_analyst_reports.py     # CafeF analyst reports (Playwright)
│   └── crawl_financial_reports.py   # CafeF BCTC API (httpx)
│
├── scripts/
│   ├── init_db.py                  # Apply schema.sql once
│   ├── sync_tickers.py             # Refresh ticker universe from vnstock
│   ├── load_tickers.py             # Read tickers filtered by priority
│   ├── analyze_sentiment.py        # PhoBERT sentiment + Gemini summaries
│   ├── extract_financial_metrics.py # Structured BCTC numbers
│   └── scheduler.py                # APScheduler driver
│
├── database/
│   ├── db.py                # NewsDB context manager
│   ├── period.py            # Q4/2025 ↔ ISO date helpers
│   └── schema.sql           # Postgres schema (5 tables + indexes)
│
├── tests/
│   ├── test_period.py       # Period parsing
│   ├── test_helpers.py      # Pure helpers in tools/crawl
│   └── test_config.py       # Config sanity bounds
│
└── exports/                 # Excel files served via /download/...
```

## Configuration

All tunable values live in [`config.py`](config.py). Common knobs:

| Setting | Default | Effect |
|---|---|---|
| `NEWS_PAGE_CONCURRENCY` | 5 | Parallel article pages per ticker |
| `TICKER_CONCURRENCY` | 4 | Parallel tickers in analyst/BCTC crawl |
| `BCTC_YEARS_BACK` | 2 | How far back BCTC crawler goes |
| `ANALYST_MONTHS_BACK` | 12 | How far back analyst crawler goes |
| `DEFAULT_MIN_PRIORITY` | 3 | 3=VN30, 2=VN100, 1=HOSE+, 0=all |
| `EXTRACT_BATCH_SIZE` | 50 | Rows per `extract_financial_metrics` run |

Edit and restart the scheduler — no code changes elsewhere needed.

## Data sources

| Source | Method | What we get |
|---|---|---|
| **vnstock** (KBS) | Python lib | OHLCV, company info, leadership |
| **CafeF news** (`cafef.vn/du-lieu/tin-doanh-nghiep/...`) | Playwright + OCR | Per-ticker news + corporate disclosures |
| **CafeF analyst reports** (`cafef.vn/du-lieu/phan-tich-bao-cao/...`) | Playwright + click intercept | Broker target prices, recommendations |
| **CafeF BCTC API** (`cafef.vn/du-lieu/Ajax/PageNew/FileBCTC.ashx`) | httpx + JSON | Audited and quarterly financial statements |

## Database schema

Five tables, all keyed by `ticker`:

- `tickers` — universe, with priority for crawl ordering
- `financial_news` — raw + sentiment-analyzed news
- `analyst_reports` — broker reports + LLM-extracted target prices
- `financial_reports` — BCTC PDFs + raw OCR text
- `financial_metrics` — structured numbers (revenue, NPAT, EPS, etc.) extracted by LLM

See [`database/schema.sql`](database/schema.sql).

## Testing

```bash
pip install pytest
pytest                              # all tests
pytest tests/test_period.py -v      # one file
pytest -k sort                       # by pattern
```

Current coverage focuses on pure helpers — period parsing, NaN guards, CDN URL swap, audit-status detection, config bounds. I/O-heavy modules (DB, crawlers, agent) are not yet under test.

## Performance notes

The agent uses several optimizations to keep latency reasonable:

- **Parallel tool calls** — when the brain needs price + sentiment + analyst views, all three fetch concurrently via `asyncio.gather`.
- **Output caps** — analyst thesis/risks and news summaries are truncated before reaching the LLM context.
- **Atomic Excel writes** — `get_stock_data` writes to a `.part.xlsx` then renames, so StaticFiles never serves a partial file.
- **Connection-per-write** in async crawlers — psycopg2 cursors aren't safe to share across `asyncio.gather`, so each task opens its own short-lived connection.
- **Schema applied once** — not on every DB connection (Fix: run `python -m scripts.init_db`).

A typical 3-tool query takes ~3-5s end-to-end. The summarizer is the biggest single cost (~1.5s).

## Known limitations

- **vnstock free tier rate limits.** Heavy concurrent crawls may get throttled. Their banner advertises a paid tier with 5x rate limits.
- **OCR quality** on older scanned BCTC PDFs is variable. Some pre-2018 reports return garbled text.
- **`langchain_google_genai` schema bug** prevents using `with_structured_output` via `bind_tools` together — the agent uses a separate summarizer node as a workaround. See agent.py comments.

## License

MIT (or whatever you prefer — add a LICENSE file).

## Contributing

Issues and PRs welcome. For substantial changes, open an issue first to discuss the direction.
