import asyncio
import io
from concurrent.futures import ProcessPoolExecutor

import fitz
import pytesseract
import requests
from PIL import Image
from playwright.async_api import async_playwright

from db.db import NewsDB


async def crawl_cafef(ticker, url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0...")
        page = await context.new_page()
        
        await page.goto(url)
        
        # 1. Lấy danh sách bài viết
        links = await page.query_selector_all(".docnhanhTitle")
        max_articles = 20
        links = links[:max_articles] 
        with NewsDB() as db:
            for link in links:
                title = await link.inner_text()
                href = await link.get_attribute("href")
                full_url = f"https://cafef.vn{href}" if href.startswith("/") else href
                
                # Chuyển hướng sang trang chi tiết
                detail_page = await browser.new_page()
                await detail_page.goto(full_url)
                
                # 2. Kiểm tra nếu là trang chứa PDF (Thường có class hoặc text đặc trưng)
                pdf_link_element = await detail_page.query_selector("a[href$='.pdf']")
                
                if pdf_link_element:
                    pdf_url = await pdf_link_element.get_attribute("href")
                    # Xử lý PDF
                    content = extract_pdf_content(pdf_url)
                    print(f"PDF Content from {pdf_url}...")
                else:
                    # Xử lý Text thường
                    paragraphs = await detail_page.query_selector_all("p[dir='ltr']")
                    texts = []

                    for p in paragraphs:
                        text = await p.inner_text()
                        if text.strip():
                            texts.append(text.strip())

                    content = "\n".join(texts)
                    print(f"Text Content: {content[:100]}...")
                if not content.strip(): 
                    continue
                is_new = db.insert_news(ticker.upper(), full_url, title, content)
                if is_new:
                    print(f"Đã lưu tin mới: {title[:50]}...")
                else:
                    print("Tin đã tồn tại, bỏ qua.")
                
                await detail_page.close()
        await browser.close()
def ocr_page_worker(page_data):
    """Hàm worker để xử lý OCR cho duy nhất 1 trang (Chạy trên 1 core CPU)"""
    try:
        img = Image.open(io.BytesIO(page_data))
        text = pytesseract.image_to_string(img, lang='vie+eng')
        return text
    except Exception as e:
        return f"[Lỗi OCR trang]: {str(e)}"        
def extract_pdf_content(pdf_url):
    """Hàm điều phối: Chia nhỏ PDF và đẩy vào các nhân CPU"""
    print(f"--- Đang tải và xử lý PDF: {pdf_url} ---")
    response = requests.get(pdf_url, timeout=20)
    
    # Mở PDF từ bộ nhớ bằng PyMuPDF
    doc = fitz.open(stream=response.content, filetype="pdf")
    page_images_bytes = []

    # Bước 1: Chuyển tất cả trang PDF thành ảnh (Render) - Bước này cực nhanh
    for page in doc:

        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) 
        page_images_bytes.append(pix.tobytes())
    
    doc.close()

    # Bước 2: Sử dụng ProcessPoolExecutor để chạy song song trên CPU
    # max_workers có thể để bằng số nhân CPU của bạn (ví dụ: 4 hoặc 8)
    full_text = []
    with ProcessPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(ocr_page_worker, page_images_bytes))
        full_text = results

    return "\n\n--- KẾT THÚC TRANG ---\n\n".join(full_text)
async def main():
    ticker = 'fpt'
    url = f"https://cafef.vn/du-lieu/tin-doanh-nghiep/{ticker}/event.chn#tat-ca"
    await crawl_cafef(ticker,url)

if __name__ == "__main__":
    asyncio.run(main())