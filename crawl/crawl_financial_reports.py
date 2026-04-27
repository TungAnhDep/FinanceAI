import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

import httpx

from config import BCTC_YEARS_BACK, DEFAULT_MIN_PRIORITY, TICKER_CONCURRENCY
from crawl.crawl_news import extract_pdf_content
from database.db import NewsDB
from database.period import quarter_to_date
from scripts.load_tickers import load_tickers

API = "https://cafef.vn/du-lieu/Ajax/PageNew/FileBCTC.ashx"

BASE = "https://cafef.vn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}
NEW_CDN = "cafefnew.mediacdn.vn"
OLD_CDN = "cafef1.mediacdn.vn"


def to_working_url(url: str) -> str:
    """The 'new' CDN reliably 404s for BCTC PDFs; the page's own JS falls back to cafef1."""
    return url.replace(NEW_CDN, OLD_CDN)


def detect_audit_status(report_type: str | None) -> str | None:
    rt = (report_type or "").lower()
    if "đã kiểm toán" in rt:
        return "audited"
    if "đã soát xét" in rt:
        return "reviewed"
    return None


async def crawl_bctc_for_ticker(
    ticker: str,
    executor,
    sem: asyncio.Semaphore,
    years_back: int = BCTC_YEARS_BACK,
):
    """Crawl BCTC for a single ticker. Runs concurrently with other tickers
    under `sem`. Opens a fresh DB connection only per insert (psycopg2 cursors
    aren't safe across asyncio.gather)."""
    async with sem:
        cutoff_year = datetime.now().year - years_back
        listing_url = (
            f"https://cafef.vn/du-lieu/hose/{ticker.lower()}-bao-cao-tai-chinh.chn"
        )

        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers=HEADERS
        ) as client:
            # Warm-up: load the listing page to obtain ASP.NET_SessionId.
            try:
                await client.get(listing_url)
            except Exception:
                try:
                    await client.get("https://cafef.vn/du-lieu/")
                except Exception:
                    pass

            try:
                resp = await client.get(
                    API,
                    params={"Symbol": ticker.lower(), "Type": 1, "Year": 0},
                    headers={"Referer": listing_url},
                )
                resp.raise_for_status()
            except Exception as e:
                print(f"[{ticker}] BCTC API err: {e}")
                return
            items = (resp.json() or {}).get("Data") or []

        items = [x for x in items if x.get("Year", 0) >= cutoff_year]
        print(f"[{ticker}] {len(items)} reports (Year >= {cutoff_year})")

        for item in items:
            pdf_url = to_working_url(item.get("Link") or "")
            if not pdf_url.endswith(".pdf"):
                continue

            with NewsDB() as db:
                if db.financial_report_exists(pdf_url):
                    continue

            row = {
                "report_type": item.get("Name"),
                "period": item.get("Time"),
                "audit_status": detect_audit_status(item.get("Name")),
                "publish_date": quarter_to_date(
                    item.get("Quarter", 0), item.get("Year", 0)
                ),
                "pdf_url": pdf_url,
            }
            try:
                content = await extract_pdf_content(pdf_url, executor)
                with NewsDB() as db:
                    db.insert_financial_report(ticker, row, content)
                print(f"[{ticker}] saved: {row['report_type'][:60]} ({row['period']})")
            except Exception as e:
                print(f"[{ticker}] err {pdf_url}: {e}")
            await asyncio.sleep(0.4)


async def main():
    tickers = load_tickers(min_priority=DEFAULT_MIN_PRIORITY)
    sem = asyncio.Semaphore(TICKER_CONCURRENCY)
    with ProcessPoolExecutor(max_workers=4) as executor:
        tasks = [crawl_bctc_for_ticker(t, executor, sem) for t in tickers]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
