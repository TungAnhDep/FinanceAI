import contextlib
import os
import sys
import threading

from datetime import datetime, timedelta
from typing import Annotated, Optional

import dateparser  # type: ignore
import pandas_ta as ta  # noqa: F401
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool
from vnstock import Company, Quote  # type: ignore

from config import (
    EMPTY_PREFIX,
    ERROR_PREFIX,
    RISKS_MAX_LEN,
    SUMMARY_MAX_LEN,
    THESIS_MAX_LEN,
)
from database.db import NewsDB
from database.period import period_to_date


@contextlib.contextmanager
def _quiet_stdout():
    """Silence vnstock's promotional banner and other stdout noise within this block."""
    saved = sys.stdout
    devnull = open(os.devnull, "w")
    try:
        sys.stdout = devnull
        yield
    finally:
        sys.stdout = saved
        devnull.close()


EXPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)


def _write_excel_atomic(file_path: str, df):
    """Write Excel to a .tmp sibling, then atomic-rename. Avoids races with
    StaticFiles serving a partial XLSX. Runs in a thread so callers don't block.

    Engine is named explicitly because pandas otherwise infers it from the
    file extension, and '.tmp' isn't a known Excel suffix."""

    def _worker():
        # Suffix ends in .xlsx so pandas accepts it; os.replace is still
        # atomic on Windows + POSIX.
        tmp = file_path + ".part.xlsx"
        try:
            df.to_excel(tmp, index=False, engine="openpyxl")
            os.replace(tmp, file_path)
        except Exception as e:
            print(f"[excel] write failed for {file_path}: {e}")
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    threading.Thread(target=_worker, daemon=True).start()


def _safe_round(value, ndigits: int = 2):
    """Return None instead of NaN so JSON serialization stays valid."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN check (NaN != NaN)
        return None
    return round(v, ndigits)


def _period_sort_key(period: Optional[str]) -> str:
    """Sort key for periods like 'Q4/2025', 'CN/2025'. Falls back to a
    minimum string for malformed/missing periods so they sort to the end
    when used with reverse=True."""
    return period_to_date(period) or "0000-00-00"


@tool
def get_stock_data(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    months: Optional[int] = None,
    indicator: bool = True,
    config: Annotated[Optional[RunnableConfig], InjectedToolArg] = None,
    rsi_window: int = 14,
    sma_window: int = 20,
):
    """
    Truy xuất dữ liệu giá lịch sử.
    Args:
        ticker: Mã chứng khoán (ví dụ: 'FPT', 'VCB').
        start_date: Ngày bắt đầu (định dạng 'DD-MM-YYYY').
        end_date: Ngày kết thúc (định dạng 'DD-MM-YYYY'). Nếu không có, mặc định là hôm nay.
        months: Số tháng gần nhất muốn lấy dữ liệu (ví dụ: 3, 6). Nếu có start_date thì bỏ qua tham số này.
        indicator: True nếu câu hỏi liên quan đến phân tích kỹ thuật, xu hướng, đánh giá. False khi user chỉ hỏi giá / OHLCV thuần.
         rsi_window: Chu kỳ RSI. Mặc định 14 (chuẩn Wilder).
            Chỉ đổi khi user nói rõ (ví dụ "RSI 9 ngày").
        sma_window: Chu kỳ SMA. Mặc định 20 (ngắn hạn).
            Đề xuất: 20 cho ngắn hạn (≤3 tháng), 50 cho trung hạn,
            200 cho dài hạn. Đổi theo horizon của câu hỏi."""
    try:
        with _quiet_stdout():
            quote = Quote(symbol=ticker.upper(), source="KBS")

            current_date = datetime.now()
            if not end_date:
                end_date = current_date.strftime("%d-%m-%Y")

            if start_date:
                parsed_date = dateparser.parse(
                    start_date, settings={"DATE_ORDER": "DMY"}
                )
                if parsed_date:
                    start_date = parsed_date.strftime("%d-%m-%Y")
                df = quote.history(start=start_date, end=end_date, interval="d")
            elif months:
                start_calc = (current_date - timedelta(days=months * 30)).strftime(
                    "%d-%m-%Y"
                )
                df = quote.history(start=start_calc, end=end_date, interval="d")
            else:
                df = quote.history(length="100", interval="d")

        if df is None or df.empty:
            return (
                f"{EMPTY_PREFIX}: giá cho mã {ticker} trong khoảng thời gian yêu cầu."
            )
        file_name = f"{ticker}_history_{datetime.now().strftime('%d%m%Y_%H%M%S')}.xlsx"
        file_path = os.path.join(EXPORT_DIR, file_name)
        df_export = df.reset_index()
        _write_excel_atomic(file_path, df_export)
        # recent_data = df_export.tail(5).to_dict(orient="records")
        base_url = "http://localhost:8000"
        if config and isinstance(config, dict):
            configurable = config.get("configurable", {})
            if isinstance(configurable, dict):
                base_url = configurable.get("base_url", base_url)
        download_link = f"{base_url}/download/{file_name}"
        if not indicator:
            return {
                "message": f"Đã xuất dữ liệu lịch sử của {ticker} vào file {file_name}.",
                "download_url": download_link,
                # "excel_file_path": file_path,
                # "recent_data": recent_data,
                "stats": {
                    "latest_close": float(df["close"].iloc[-1]),
                    "period_high": float(df["high"].max()),
                    "period_low": float(df["low"].min()),
                    "rows_count": len(df),
                },
            }
        df.ta.sma(length=sma_window, append=True)
        df.ta.rsi(length=rsi_window, append=True)
        return {
            "message": f"Đã xuất dữ liệu lịch sử của {ticker} vào file {file_name}.",
            "download_url": download_link,
            "stats": {
                "latest_close": float(df["close"].iloc[-1]),
                "period_high": float(df["high"].max()),
                "period_low": float(df["low"].min()),
                "rows_count": len(df),
            },
            "SMA": _safe_round(df[f"SMA_{sma_window}"].iloc[-1]),
            "RSI": _safe_round(df[f"RSI_{rsi_window}"].iloc[-1]),
            "sma_window": sma_window,
            "rsi_window": rsi_window,
        }
    except Exception as e:
        return f"{ERROR_PREFIX}: get_stock_data {ticker} — {e}"


@tool
def get_company_info(ticker: str, category: str, filter_by: str = "working"):
    """Truy xuất thông tin công ty từ vnstock
    Args:
        ticker: Mã chứng khoán (ví dụ: 'FPT', 'HPG').
         category: Hạng mục thông tin bao gồm:
            - 'profile': Tổng quan công ty
            - 'shareholders': Danh sách cổ đông
            - 'subsidiaries': Công ty con
            - 'affiliates': Công ty liên kết
            - 'leadership': Ban lãnh đạo (dùng kèm filter_by)
        filter_by: Chỉ dùng khi category='leadership'.
            - 'working': Lãnh đạo đang đương nhiệm (mặc định).
            - 'resigned': Lãnh đạo đã nghỉ việc.
            - 'all': Tất cả lịch sử lãnh đạo.
         LƯU Ý: với category='news' bạn nhận tin gốc chưa phân tích sentiment.
        Nếu cần đánh giá tâm lý thị trường, hãy dùng `get_market_sentiment` thay vì tool này.
    """

    try:
        with _quiet_stdout():
            company = Company(symbol=ticker, source="KBS")
            data_map = {
                "profile": company.overview,
                "shareholders": company.shareholders,
                "subsidiaries": company.subsidiaries,
                "affiliates": company.affiliates,
                "leadership": company.officers,
            }
            data_func = data_map.get(category)
            if not data_func:
                return f"{ERROR_PREFIX}: hạng mục {category} không được hỗ trợ."

            if category == "leadership":
                df = data_func(filter_by=filter_by)
            else:
                df = data_func()
        result = df.to_dict(orient="records")
        return result[:3]  # Giới hạn số lượng bản ghi
    except Exception as e:
        return f"{ERROR_PREFIX}: get_company_info {ticker}/{category} — {e}"


@tool
def get_market_sentiment(ticker: str, limit: int = 5):
    """Truy xuất điểm tâm lý và tóm tắt tin tức mới nhất của một mã cổ phiếu từ database."""

    with NewsDB() as db:
        query = """
            SELECT title, sentiment_label, summary, created_at
            FROM financial_news
            WHERE ticker = %s AND is_analyzed = TRUE
            ORDER BY created_at DESC LIMIT %s
        """
        db.cur.execute(query, (ticker.upper(), limit))
        rows = db.cur.fetchall()

        if not rows:
            return f"{EMPTY_PREFIX}: tâm lý gần đây cho mã {ticker}."

        results = []
        for r in rows:
            results.append(
                {
                    "title": r[0],
                    "sentiment": r[1],
                    "summary": (r[2] or "")[:SUMMARY_MAX_LEN],
                    "date": str(r[3]),
                }
            )
        return results


@tool
def get_analyst_reports(ticker: str, limit: int = 3):
    """Truy xuất báo cáo phân tích gần nhất từ các công ty chứng khoán (SSI, HSC, VNDirect, ACBS, VPBANKS...).
    Trả về giá mục tiêu, khuyến nghị (MUA/GIỮ/BÁN), luận điểm đầu tư, rủi ro chính.
    Dùng cho câu hỏi về định giá, target price, fundamentals, view của giới phân tích.
    Args:
        ticker: Mã chứng khoán (ví dụ: 'FPT', 'VNM').
        limit: Số báo cáo gần nhất muốn lấy (mặc định 3).
    """
    with NewsDB() as db:
        query = """
            SELECT broker, report_type, title, target_price, recommendation,
                   thesis, risks, publish_date, pdf_url
            FROM analyst_reports
            WHERE ticker = %s
            ORDER BY publish_date DESC NULLS LAST, created_at DESC
            LIMIT %s
        """
        db.cur.execute(query, (ticker.upper(), limit))
        rows = db.cur.fetchall()

        if not rows:
            return f"{EMPTY_PREFIX}: báo cáo phân tích cho mã {ticker}."

        results = []
        for r in rows:
            results.append(
                {
                    "broker": r[0],
                    "report_type": r[1],
                    "title": r[2],
                    "target_price": float(r[3]) if r[3] is not None else None,
                    "recommendation": r[4],
                    "thesis": (r[5] or "")[:THESIS_MAX_LEN],
                    "risks": (r[6] or "")[:RISKS_MAX_LEN],
                    "publish_date": str(r[7]) if r[7] else None,
                    "pdf_url": r[8],
                }
            )
        return results


@tool
def get_financial_reports(
    ticker: str,
    period: Optional[str] = None,
    statement_filter: Optional[str] = None,
    limit: int = 4,
):
    """Truy xuất báo cáo tài chính (BCTC) đã công bố của doanh nghiệp:
    KQKD, CĐKT, LCTT theo quý/năm, có hoặc chưa kiểm toán.
    Dùng cho câu hỏi về doanh thu, lợi nhuận, tài sản, dòng tiền, kết quả kinh doanh.
    Args:
        ticker: Mã chứng khoán (ví dụ: 'FPT').
        statement_filter: Lọc loại báo cáo. Tùy chọn:
            - 'consolidated': chỉ BCTC hợp nhất.
            - 'parent': chỉ BCTC công ty mẹ (riêng).
            - 'audited': chỉ báo cáo đã kiểm toán.
            - None: tất cả (mặc định).
        period: Lọc theo kỳ báo cáo. Ví dụ: 'Q4/2025', 'CN/2025', 'Q1/2024'. Nếu None, trả về các kỳ gần nhất.
        limit: Số báo cáo gần nhất muốn lấy (mặc định 4 — đủ 4 quý gần nhất).
    """
    with NewsDB() as db:
        base_query = """
            SELECT report_type, period, audit_status, publish_date, pdf_url
            FROM financial_reports
            WHERE ticker = %s
        """
        params: list = [ticker.upper()]
        if period:
            base_query += " AND period = %s"
            params.append(period)
        if statement_filter == "consolidated":
            base_query += " AND report_type ILIKE %s"
            params.append("%hợp nhất%")
        elif statement_filter == "parent":
            base_query += " AND report_type ILIKE %s"
            params.append("%công ty mẹ%")
        elif statement_filter == "audited":
            base_query += " AND audit_status = 'audited'"

        base_query += " ORDER BY publish_date DESC NULLS LAST, created_at DESC LIMIT %s"
        params.append(limit)

        db.cur.execute(base_query, tuple(params))
        rows = db.cur.fetchall()

        if not rows:
            return f"{EMPTY_PREFIX}: báo cáo tài chính cho mã {ticker}."

        results = []
        for r in rows:
            results.append(
                {
                    "report_type": r[0],
                    "period": r[1],
                    "audit_status": r[2],
                    "publish_date": str(r[3]) if r[3] else None,
                    "pdf_url": r[4],
                }
            )
        return results


@tool
def get_financial_metrics(
    ticker: str,
    metrics: Optional[list[str]] = None,
    n_periods: int = 4,
    scope: str = "consolidated",
):
    """Truy xuất các chỉ tiêu tài chính (doanh thu, LNST, EPS, ROE, tổng tài sản...) đã trích xuất từ BCTC.
    Args:
        ticker: Mã chứng khoán.
        metrics: Danh sách chỉ tiêu muốn lấy (revenue, npat, eps, total_assets...). None = tất cả.
        n_periods: Số kỳ gần nhất (mặc định 4 = 4 quý).
        scope: 'consolidated' (hợp nhất, mặc định) hoặc 'parent' (công ty mẹ).
    """
    with NewsDB() as db:
        sql = """
            SELECT period, metric, value, unit
            FROM financial_metrics
            WHERE ticker = %s AND statement_scope = %s
        """
        params: list = [ticker.upper(), scope]
        if metrics:
            sql += " AND metric = ANY(%s)"
            params.append(metrics)
        # No SQL ORDER BY here — `period` is text ('Q4/2025', 'CN/2024'),
        # lexicographic sort is wrong. We sort chronologically in Python.
        db.cur.execute(sql, tuple(params))
        rows = db.cur.fetchall()

        by_period: dict = {}
        for period, metric, value, unit in rows:
            by_period.setdefault(period, {})[metric] = {
                "value": float(value),
                "unit": unit,
            }

        # Sort by chronological key (most recent first), then take n_periods
        ordered_keys = sorted(by_period.keys(), key=_period_sort_key, reverse=True)
        ordered = [(k, by_period[k]) for k in ordered_keys[:n_periods]]
        if not ordered:
            return f"{EMPTY_PREFIX}: chỉ tiêu tài chính cho {ticker}."
        return [{"period": p, "metrics": ms} for p, ms in ordered]
