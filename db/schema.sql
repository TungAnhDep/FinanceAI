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
    summary TEXT,   -- Kết quả sau khi LLM phân tích
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);