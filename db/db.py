import hashlib
import os

import psycopg2
from dotenv import load_dotenv
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(CURRENT_DIR, "schema.sql")
load_dotenv()

class NewsDB:
    def __init__(self):
        self.db_config = {
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "host": os.getenv("DB_HOST")
        }
        self.conn = None
        self.cur = None

    def __enter__(self):
        self.conn = psycopg2.connect(**self.db_config)
        self.cur = self.conn.cursor()
        
        if os.path.exists(SCHEMA_PATH):
            try:
                with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                    self.cur.execute(f.read())
                self.conn.commit()
            except Exception as e:
                self.conn.rollback()
                print(f"Lỗi khi chạy schema: {e}")
        
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type:
                self.conn.rollback() 
                print(f"Transaction rolled back due to: {exc_val}")
            else:
                self.conn.commit() 
            
            self.cur.close()
            self.conn.close()

    def compute_hash(self, text):
        """Tạo mã SHA-256 cho nội dung tin tức."""
        return hashlib.sha256(text.strip().encode('utf-8')).hexdigest()

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