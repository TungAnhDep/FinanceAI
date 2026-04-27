import hashlib
import os

import psycopg2
from dotenv import load_dotenv

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(CURRENT_DIR, "schema.sql")
load_dotenv()


class NewsDB:
    """Postgres connection wrapper. Use as a context manager:
        with NewsDB() as db:
            db.cur.execute(...)
    Commit happens automatically on clean exit; rollback happens on exception.
    Helper methods (insert_*) DO NOT commit individually — they rely on __exit__."""

    def __init__(self):
        self.db_config = {
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "host": os.getenv("DB_HOST"),
        }
        self.conn = None
        self.cur = None

    def __enter__(self):
        self.conn = psycopg2.connect(**self.db_config)
        self.cur = self.conn.cursor()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.conn:
            return
        try:
            if exc_type:
                self.conn.rollback()
                print(f"Transaction rolled back due to: {exc_val}")
            else:
                self.conn.commit()
        finally:
            self.cur.close()
            self.conn.close()

    def ensure_schema(self):
        """Apply schema.sql once (call from a setup script, NOT per request)."""
        if not os.path.exists(SCHEMA_PATH):
            return
        try:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                self.cur.execute(f.read())
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f"Lỗi khi chạy schema: {e}")

    def compute_hash(self, text):
        """Tạo mã SHA-256 cho nội dung tin tức."""
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    def is_exists(self, url, content_hash):
        query = "SELECT id FROM financial_news WHERE url = %s OR content_hash = %s"
        self.cur.execute(query, (url, content_hash))
        return self.cur.fetchone() is not None

    def insert_news(self, ticker, url, title, content):
        content_hash = self.compute_hash(content)
        if self.is_exists(url, content_hash):
            return False
        query = """
            INSERT INTO financial_news (ticker, url, title, content, content_hash)
            VALUES (%s, %s, %s, %s, %s)
        """
        self.cur.execute(query, (ticker, url, title, content, content_hash))
        return True

    def analyst_report_exists(self, pdf_url: str) -> bool:
        self.cur.execute("SELECT 1 FROM analyst_reports WHERE pdf_url = %s", (pdf_url,))
        return self.cur.fetchone() is not None

    def insert_analyst_report(
        self, ticker: str, item: dict, pdf_url: str, content: str
    ):
        self.cur.execute(
            """
            INSERT INTO analyst_reports
                (ticker, broker, report_type, title, pdf_url, raw_content, publish_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (pdf_url) DO NOTHING
            """,
            (
                ticker.upper(),
                item.get("broker"),
                item.get("report_type"),
                item.get("title"),
                pdf_url,
                content,
                item.get("publish_date"),
            ),
        )

    def financial_report_exists(self, pdf_url: str) -> bool:
        self.cur.execute(
            "SELECT 1 FROM financial_reports WHERE pdf_url = %s", (pdf_url,)
        )
        return self.cur.fetchone() is not None

    def insert_financial_report(self, ticker: str, item: dict, content: str):
        self.cur.execute(
            """
            INSERT INTO financial_reports
                (ticker, report_type, period, audit_status, pdf_url, raw_content, publish_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (pdf_url) DO NOTHING
            """,
            (
                ticker.upper(),
                item.get("report_type"),
                item.get("period"),
                item.get("audit_status"),
                item["pdf_url"],
                content,
                item.get("publish_date"),
            ),
        )
