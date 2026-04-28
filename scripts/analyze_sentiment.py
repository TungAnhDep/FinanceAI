import os
import time

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from transformers import pipeline

from config import GEMINI_API_DELAY
from database.db import NewsDB

load_dotenv()
api_key = os.getenv("GOOGLE_API")

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key)
sentiment_pipeline = pipeline(
    "text-classification",
    model="mnguyn11/phobert-stock-sentiment-PTDLW",
    truncation=True,
    max_length=256,
)


def get_local_sentiment(title, content):
    text = f"{title}. {content[:500]}" if content else title
    result = sentiment_pipeline(text)[0]
    label = result["label"]
    score = result["score"]
    mapping = {
        "POS": ("Positive", score),
        "NEG": ("Negative", -score),
        "NEU": ("Neutral", score),
    }
    return mapping.get(label, ("Neutral", 0.0))


def process_pending_news():
    with NewsDB() as db:
        db.cur.execute(
            "SELECT id, title, content FROM financial_news WHERE is_analyzed = FALSE"
        )
        rows = db.cur.fetchall()

        for row_id, title, content in rows:
            label, score = get_local_sentiment(title, content)
            prompt = (
                "Tóm tắt tin tài chính sau trong đúng 2 câu tiếng Việt. "
                "Tập trung vào: (1) sự kiện/hành động chính, (2) tác động tiềm tàng đến giá cổ phiếu. "
                "Không lặp lại tiêu đề. Không dùng từ ngữ chung chung.\n\n"
                f"Tiêu đề: {title}\nNội dung: {(content or '')[:2000]}"
            )
            try:
                response = llm.invoke(prompt)

                data = response.content.strip()

                db.cur.execute(
                    """
                    UPDATE financial_news 
                    SET sentiment_score = %s, sentiment_label = %s,summary = %s, is_analyzed = TRUE 
                    WHERE id = %s
                """,
                    (score, label, data, row_id),
                )
                db.conn.commit()
                print(f"Đã phân tích xong tin ID: {row_id}")
                time.sleep(GEMINI_API_DELAY)
            except Exception as e:
                print(f"Error at ID {row_id}: {e}")
                continue


if __name__ == "__main__":
    process_pending_news()
