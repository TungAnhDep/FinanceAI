import asyncio
import io
from concurrent.futures import ProcessPoolExecutor

import fitz
import httpx
import pytesseract
from PIL import Image
from playwright.async_api import async_playwright

from config import DEFAULT_MIN_PRIORITY, NEWS_LATEST_LIMIT, NEWS_PAGE_CONCURRENCY
from database.db import NewsDB
from scripts.load_tickers import load_tickers

# Giới hạn số lượng trang mở cùng lúc để tránh crash/ban.
semaphore = asyncio.Semaphore(NEWS_PAGE_CONCURRENCY)


async def process_article(context, ticker, href, executor):
    """Xử lý từng bài viết riêng biệt. Opens its own DB connection so
    concurrent articles don't share a psycopg2 cursor (NOT thread-safe)."""
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

            stripped = content.strip()
            # Skip empty bodies and synthetic error markers from extract_pdf_content / OCR.
            if stripped and not stripped.startswith("["):
                title = await page.title()
                with NewsDB() as db:
                    is_new = db.insert_news(ticker.upper(), full_url, title, content)
                print(
                    f"[{ticker}] {'Lưu mới' if is_new else 'Bỏ qua'}: {title[:50]}..."
                )
            elif stripped.startswith("["):
                print(f"[{ticker}] Bỏ qua (lỗi): {full_url}")
        except Exception as e:
            print(f"Lỗi khi xử lý {full_url}: {e}")
        finally:
            await page.close()


async def crawl_ticker(browser, ticker, executor):
    """Fetch the ticker's listing page (once, no semaphore needed — small),
    then dispatch articles. Per-page concurrency is enforced by the semaphore
    inside `process_article`, not here."""
    context = await browser.new_context()
    try:
        url = f"https://cafef.vn/du-lieu/tin-doanh-nghiep/{ticker.lower()}/event.chn#tat-ca"
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")
            links = await page.query_selector_all(".docnhanhTitle")
            hrefs = [
                await link.get_attribute("href")
                for link in links[:NEWS_LATEST_LIMIT]
            ]
        finally:
            await page.close()

        tasks = [process_article(context, ticker, href, executor) for href in hrefs]
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
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(pdf_url)

    if response.status_code != 200:
        return f"[Lỗi HTTP {response.status_code}: {pdf_url}]"

    content = response.content
    if not content.startswith(b"%PDF"):
        ct = response.headers.get("content-type", "?")
        return f"[Response không phải PDF (content-type={ct}, bytes={len(content)})]"

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        return f"[Lỗi mở PDF: {e}]"

    direct_text = "\n\n".join(page.get_text("text") for page in doc).strip()
    if len(direct_text) >= 200:
        doc.close()
        return direct_text

    page_images_bytes = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
        page_images_bytes.append(pix.tobytes())
    doc.close()

    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        *(loop.run_in_executor(executor, ocr_page_worker, b) for b in page_images_bytes)
    )
    return "\n\n".join(results)


async def main():
    tickers = load_tickers(min_priority=DEFAULT_MIN_PRIORITY)
    with ProcessPoolExecutor(max_workers=4) as executor:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                ticker_tasks = [crawl_ticker(browser, t, executor) for t in tickers]
                await asyncio.gather(*ticker_tasks)
            finally:
                await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
