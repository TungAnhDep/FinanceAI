import asyncio
import io
from concurrent.futures import ProcessPoolExecutor

import fitz
import httpx
import pytesseract
from PIL import Image
from playwright.async_api import async_playwright

from database.db import NewsDB

# Giới hạn số lượng trang mở cùng lúc để tránh crash/ban
CONCURRENCY_LIMIT = 5
semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)


async def process_article(context, ticker, href, db, executor):
    """Xử lý từng bài viết riêng biệt"""
    async with semaphore:
        full_url = f"https://cafef.vn{href}" if href.startswith("/") else href
        page = await context.new_page()
        try:
            await page.goto(full_url, timeout=60000, wait_until="domcontentloaded")

            # Kiểm tra PDF
            pdf_link = await page.query_selector("a[href$='.pdf']")
            if pdf_link:
                pdf_url = await pdf_link.get_attribute("href")
                # Chạy OCR trong thread pool để không block async loop
                content = await extract_pdf_content(pdf_url, executor)
            else:
                content = await page.eval_on_selector_all(
                    ".contentdetail p",
                    "els => els.map(e => e.innerText).join('\\n')",
                )

            if content.strip():
                title = await page.title()
                is_new = db.insert_news(ticker.upper(), full_url, title, content)
                print(
                    f"[{ticker}] {'Lưu mới' if is_new else 'Bỏ qua'}: {title[:50]}..."
                )
        except Exception as e:
            print(f"Lỗi khi xử lý {full_url}: {e}")
        finally:
            await page.close()


async def crawl_ticker(browser, ticker, db, executor):
    context = await browser.new_context()
    try:
        async with semaphore:
            url = f"https://cafef.vn/du-lieu/tin-doanh-nghiep/{ticker.lower()}/event.chn#tat-ca"
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")

            links = await page.query_selector_all(".docnhanhTitle")
            hrefs = [await link.get_attribute("href") for link in links[:15]]

            await page.close()

        tasks = [process_article(context, ticker, href, db, executor) for href in hrefs]
        await asyncio.gather(*tasks)
    finally:
        await context.close()


def ocr_page_worker(page_data):
    try:
        img = Image.open(io.BytesIO(page_data))
        return pytesseract.image_to_string(img, lang="vie+eng")
    except Exception as e:
        return f"[Lỗi OCR]: {str(e)}"


async def extract_pdf_content(pdf_url, executor):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(pdf_url)

    doc = fitz.open(stream=response.content, filetype="pdf")

    page_images_bytes = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        page_images_bytes.append(pix.tobytes())
    doc.close()

    loop = asyncio.get_event_loop()
    results = await asyncio.gather(
        *(loop.run_in_executor(executor, ocr_page_worker, b) for b in page_images_bytes)
    )

    return "\n\n".join(results)


async def main():
    tickers = ["FPT", "VNM"]
    with NewsDB() as db:
        with ProcessPoolExecutor(max_workers=4) as executor:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)

                ticker_tasks = [crawl_ticker(browser, t, db, executor) for t in tickers]
                await asyncio.gather(*ticker_tasks)

                await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
