import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urljoin

import httpx
from playwright.async_api import async_playwright
from selectolax.parser import HTMLParser

from config import ANALYST_MONTHS_BACK, DEFAULT_MIN_PRIORITY, TICKER_CONCURRENCY
from crawl.crawl_news import extract_pdf_content
from database.db import NewsDB
from scripts.load_tickers import load_tickers

BASE = "https://cafef.vn"
PDF_BASE = "https://cafefnew.mediacdn.vn/Images/Uploaded/DuLieuDownload/PhanTichBaoCao/"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def build_listing_url(ticker: str, from_date: str, to_date: str) -> str:
    return (
        f"{BASE}/du-lieu/phan-tich-bao-cao/{ticker.upper()}.chn"
        f"?source=0&indexSource=0&fromDate={from_date}&toDate={to_date}"
    )


def parse_date(s):
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def parse_listing(html: str) -> list[dict]:
    tree = HTMLParser(html)
    items = []

    first = tree.css_first(".item-first")
    if first:
        a = first.css_first(".item-first-content-title a")
        d = first.css_first(".item-first-content-footer-left-time")
        s = first.css_first(".item-first-content-footer-left-source")
        if a:
            items.append(
                {
                    "title": a.text(strip=True),
                    "detail_url": urljoin(BASE, a.attributes.get("href", "")),
                    "publish_date": parse_date(d.text(strip=True) if d else None),
                    "broker": (
                        s.text(strip=True).replace("Nguồn:", "").strip() if s else None
                    ),
                }
            )

    for child in tree.css(".item-child"):
        a = child.css_first(".item-child-content-title a")
        d = child.css_first(".item-child-content-time-link-time")
        if not a:
            continue
        items.append(
            {
                "title": a.text(strip=True),
                "detail_url": urljoin(BASE, a.attributes.get("href", "")),
                "publish_date": parse_date(d.text(strip=True) if d else None),
                "broker": None,
            }
        )
    return items


async def resolve_detail(page, detail_url: str) -> dict:
    """Visit detail page, click Tải về, intercept track-download to grab fileName.
    Also pulls broker / report_type from the rendered DOM."""
    captured = {"file_name": None}

    def on_request(req):
        if "track-download" not in req.url or req.method != "POST":
            return
        try:
            body = req.post_data_json or {}
            fn = body.get("fileName")
            if fn:
                captured["file_name"] = fn
        except Exception:
            pass

    page.on("request", on_request)
    try:
        await page.goto(detail_url, wait_until="networkidle", timeout=30000)

        meta = await page.evaluate("""() => {
            const grab = (label) => {
                const all = [...document.querySelectorAll('div')];
                const node = all.find(el => el.children.length === 0
                    && el.innerText.trim() === label);
                if (!node) return null;
                const sib = node.nextElementSibling;
                return sib ? sib.innerText.trim() : null;
            };
            return {
                broker: grab('Nguồn báo cáo:'),
                report_type: grab('Loại báo cáo:'),
            };
        }""")

        try:
            await page.click(".bcpt-tai-ve-btn", timeout=5000)
            await page.wait_for_request(
                lambda r: "track-download" in r.url, timeout=8000
            )
        except Exception:
            pass
    finally:
        page.remove_listener("request", on_request)

    return {**meta, "file_name": captured["file_name"]}


async def crawl_analyst_reports(
    ticker: str,
    context,
    executor,
    sem: asyncio.Semaphore,
    months_back: int = ANALYST_MONTHS_BACK,
):
    """Crawl a single ticker's analyst reports. Reuses an externally-owned
    browser context. Open its own DB connection per insert (psycopg2 cursors
    aren't safe to share across asyncio.gather)."""
    async with sem:
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=months_back * 30)).strftime(
            "%Y-%m-%d"
        )

        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers=HEADERS
        ) as client:
            try:
                resp = await client.get(build_listing_url(ticker, from_date, to_date))
                resp.raise_for_status()
            except Exception as e:
                print(f"[{ticker}] listing err: {e}")
                return
            items = parse_listing(resp.text)
            print(f"[{ticker}] {len(items)} reports listed")

        if not items:
            return

        page = await context.new_page()
        try:
            for item in items:
                try:
                    meta = await resolve_detail(page, item["detail_url"])
                except Exception as e:
                    print(f"[{ticker}] detail err: {e}")
                    continue

                if not meta.get("file_name"):
                    print(f"[{ticker}] no fileName: {item['title'][:60]}")
                    continue

                pdf_url = PDF_BASE + meta["file_name"]

                with NewsDB() as db:
                    if db.analyst_report_exists(pdf_url):
                        continue

                merged = {**item, **{k: v for k, v in meta.items() if v}}
                try:
                    content = await extract_pdf_content(pdf_url, executor)
                    with NewsDB() as db:
                        db.insert_analyst_report(ticker, merged, pdf_url, content)
                    print(f"[{ticker}] saved: {merged['title'][:60]}")
                except Exception as e:
                    print(f"[{ticker}] err {pdf_url}: {e}")

                await asyncio.sleep(0.4)
        finally:
            await page.close()


async def main():
    tickers = load_tickers(min_priority=DEFAULT_MIN_PRIORITY)
    sem = asyncio.Semaphore(TICKER_CONCURRENCY)
    with ProcessPoolExecutor(max_workers=4) as executor:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            try:
                tasks = [
                    crawl_analyst_reports(t, context, executor, sem) for t in tickers
                ]
                await asyncio.gather(*tasks)
            finally:
                await context.close()
                await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
