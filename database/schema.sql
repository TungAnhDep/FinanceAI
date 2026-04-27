CREATE TABLE IF NOT EXISTS financial_news (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE,               -- Ngăn crawl cùng 1 link nhiều lần
    ticker VARCHAR(20),            -- Mã cổ phiếu (ví dụ: FPT)
    title TEXT,
    content TEXT,
    content_hash VARCHAR(64) UNIQUE, -- SHA-256 để kiểm tra nội dung trùng
    publish_date TIMESTAMP,
    is_analyzed BOOLEAN DEFAULT FALSE, -- Cờ để Agent quét
    sentiment_score FLOAT,      
    sentiment_label VARCHAR(20),
    summary TEXT,   -- Kết quả sau khi LLM phân tích
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Hot path: get_market_sentiment filters (ticker, is_analyzed, created_at DESC).
CREATE INDEX IF NOT EXISTS idx_news_ticker_analyzed_created
    ON financial_news(ticker, is_analyzed, created_at DESC);
-- Partial index for analyze_sentiment.py scanning unprocessed rows.
CREATE INDEX IF NOT EXISTS idx_news_pending_analysis
    ON financial_news(id) WHERE is_analyzed = FALSE;

CREATE TABLE IF NOT EXISTS analyst_reports (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20),
    broker VARCHAR(150),
    report_type VARCHAR(150),
    title TEXT,
    pdf_url TEXT UNIQUE,
    target_price NUMERIC,
    recommendation VARCHAR(20),
    thesis TEXT,
    risks TEXT,
    raw_content TEXT,
    publish_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_analyst_ticker
    ON analyst_reports(ticker, publish_date DESC);

CREATE TABLE IF NOT EXISTS financial_reports (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20),
    report_type TEXT,                -- "Báo cáo tài chính công ty mẹ năm 2025 (đã kiểm toán)"
    period VARCHAR(20),              -- "Q4/2025", "CN/2025"
    audit_status VARCHAR(20),        -- 'audited' | 'reviewed' | NULL
    pdf_url TEXT UNIQUE,             -- canonical (working) URL after CDN swap
    raw_content TEXT,                -- text/OCR extraction
    publish_date DATE,               -- inferred from period
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_financial_reports_ticker
    ON financial_reports(ticker, publish_date DESC);

CREATE TABLE IF NOT EXISTS financial_metrics (
    ticker VARCHAR(20),
    period VARCHAR(20),
    statement_scope VARCHAR(20),    -- 'consolidated' | 'parent'
    metric VARCHAR(50),             -- 'revenue', 'gross_profit', 'npat', 'eps', 'total_assets', ...
    value NUMERIC,
    unit VARCHAR(20),               -- 'VND', 'million_VND', 'VND/share'
    source_pdf TEXT,                -- pdf_url it came from
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, period, statement_scope, metric)
);

CREATE TABLE IF NOT EXISTS tickers (
    ticker VARCHAR(20) PRIMARY KEY,
    exchange VARCHAR(10),                -- 'HOSE' | 'HNX' | 'UPCOM'
    company_name TEXT,
    industry VARCHAR(150),
    is_active BOOLEAN DEFAULT TRUE,      -- soft-delete flag
    priority INT DEFAULT 0,              -- 1=VN30, 2=VN100, 0=other; controls crawl order
    last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- load_tickers filters is_active=TRUE then orders by priority DESC.
CREATE INDEX IF NOT EXISTS idx_tickers_active_priority
    ON tickers(is_active, priority DESC, ticker);
