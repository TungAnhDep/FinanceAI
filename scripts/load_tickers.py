from database.db import NewsDB


def load_tickers(min_priority: int = 2, limit: int | None = None) -> list[str]:
    """Load active tickers from DB, ordered by priority desc.
    min_priority: 3=VN30 only, 2=VN100+, 1=HOSE+, 0=all exchanges.
    """
    with NewsDB() as db:
        sql = """
            SELECT ticker FROM tickers
            WHERE is_active = TRUE AND priority >= %s
            ORDER BY priority DESC, ticker
        """
        params: list = [min_priority]
        if limit:
            sql += " LIMIT %s"
            params.append(limit)
        db.cur.execute(sql, tuple(params))
        return [r[0] for r in db.cur.fetchall()]
