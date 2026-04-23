import os
import time

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from transformers import pipeline

from database.db import NewsDB

load_dotenv()
api_key = os.getenv("GOOGLE_API")

# Initialize the Google Generative AI model
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key)
sentiment_pipeline = pipeline("text-classification", model="mnguyn11/phobert-stock-sentiment-PTDLW")
def get_local_sentiment(text):
    truncated_text = text[:500] 
    result = sentiment_pipeline(truncated_text)[0]
    
    # Map kết quả nhãn về thang điểm từ -1 đến 1
    label = result['label']
    score = result['score']
    mapping = {
        "POS": ("Positive", score),
        "NEG": ("Negative", -score),
        "NEU": ("Neutral", score)
    }
    return mapping.get(label, ("Neutral", 0.0))                        # Trung lập
def process_pending_news():
    with NewsDB() as db:
        # Lấy các tin chưa phân tích
        db.cur.execute("SELECT id, title, content FROM financial_news WHERE is_analyzed = FALSE")
        rows = db.cur.fetchall()
        
        for row_id, title, content in rows:
            label, score = get_local_sentiment(content if content else title)
            prompt = f"Tóm tắt tin tức sau trong tối đa 2 câu: {content[:2000]}"
            try:

                response = llm.invoke(prompt)
            
                data = response.content.strip()
                
                db.cur.execute("""
                    UPDATE financial_news 
                    SET sentiment_score = %s, sentiment_label = %s,summary = %s, is_analyzed = TRUE 
                    WHERE id = %s
                """, (score,label, data, row_id)) 
                print(f"Đã phân tích xong tin ID: {row_id}")
                time.sleep(10)
            except Exception as e:
                print(f"Error at ID {row_id}: {e}")
                continue
if __name__ == "__main__":
    
    process_pending_news()