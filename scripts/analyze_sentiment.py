from datetime import time
import os

from dotenv import load_dotenv
from langchain_core.output_parsers.json import JsonOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI

from db.db import NewsDB

load_dotenv()
api_key = os.getenv("GOOGLE_API")

# Initialize the Google Generative AI model
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", google_api_key=api_key)
def process_pending_news():
    with NewsDB() as db:
        # Lấy các tin chưa phân tích
        db.cur.execute("SELECT id, title, content FROM financial_news WHERE is_analyzed = FALSE")
        rows = db.cur.fetchall()
        
        for row_id, title, content in rows:
            prompt = f"Phân tích tin tức chứng khoán sau:\nTiêu đề: {title}\nNội dung: {content}\n\nTrả về định dạng JSON: {{'sentiment_score': float từ -1 đến 1, 'summary': 'tóm tắt ngắn'}}"
            response = llm.invoke(prompt)
          
            data = JsonOutputParser().parse(response.content)
            
            db.cur.execute("""
                UPDATE financial_news 
                SET sentiment_score = %s, summary = %s, is_analyzed = TRUE 
                WHERE id = %s
            """, (data["sentiment_score"], data["summary"], row_id)) 
            print(f"Đã phân tích xong tin ID: {row_id}")
            time.sleep(10)
if __name__ == "__main__":
    
    process_pending_news()