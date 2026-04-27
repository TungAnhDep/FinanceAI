from vnstock import Listing  # type: ignore

from database.db import NewsDB


def sync_tickers():
    listing = Listing()

    # Get full universe with exchange + industry
    all_df = listing.symbols_by_exchange()

    # Get index memberships for prioritization
    try:
        vn30 = set(listing.symbols_by_group("VN30").tolist())
    except Exception:
        vn30 = set()
    try:
        vn100 = set(listing.symbols_by_group("VN100").tolist())
    except Exception:
        vn100 = set()

    rows = []
    for _, r in all_df.iterrows():
        symbol = str(r.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        exchange = str(r.get("exchange", "")).upper()
        company_name = r.get("organ_name") or r.get("company_name") or ""
        industry = r.get("icb_name3") or r.get("industry") or ""

        if symbol in vn30:
            priority = 3
        elif symbol in vn100:
            priority = 2
        elif exchange == "HOSE":
            priority = 1
        else:
            priority = 0

        rows.append((symbol, exchange, company_name, industry, priority))

    print(f"Syncing {len(rows)} tickers")

    with NewsDB() as db:
        for row in rows:
            db.cur.execute(
                """
                INSERT INTO tickers (ticker, exchange, company_name, industry, priority, last_synced)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (ticker) DO UPDATE SET
                    exchange = EXCLUDED.exchange,
                    company_name = EXCLUDED.company_name,
                    industry = EXCLUDED.industry,
                    priority = EXCLUDED.priority,
                    last_synced = CURRENT_TIMESTAMP
                """,
                row,
            )
        db.conn.commit()
    print("Done")


if __name__ == "__main__":
    sync_tickers()
