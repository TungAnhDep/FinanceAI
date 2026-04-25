import os
from datetime import datetime, timedelta
from typing import Annotated, Optional

import dateparser  # type: ignore
import pandas_ta as ta  # noqa: F401
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool
from vnstock import Company, Quote  # type: ignore

from database.db import NewsDB

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)


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
        quote = Quote(symbol=ticker.upper(), source="KBS")

        current_date = datetime.now()
        if not end_date:
            end_date = current_date.strftime("%d-%m-%Y")

        if start_date:
            parsed_date = dateparser.parse(start_date, settings={"DATE_ORDER": "DMY"})
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
            return f"Không có dữ liệu cho mã {ticker} trong khoảng thời gian yêu cầu."
        file_name = f"{ticker}_history_{datetime.now().strftime('%d%m%Y_%H%M%S')}.xlsx"
        file_path = os.path.join(EXPORT_DIR, file_name)
        df_export = df.reset_index()
        df_export.to_excel(file_path, index=False)
        recent_data = df_export.tail(5).to_dict(orient="records")
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
                "excel_file_path": file_path,
                "recent_data": recent_data,
            }
        df.ta.sma(length=sma_window, append=True)
        df.ta.rsi(length=rsi_window, append=True)
        return {
            "message": f"Đã xuất dữ liệu lịch sử của {ticker} vào file {file_name}.",
            "download_url": download_link,
            "excel_file_path": file_path,
            "recent_data": recent_data,
            "SMA": round(float(df[f"SMA_{sma_window}"].iloc[-1]), 2),
            "RSI": round(float(df[f"RSI_{rsi_window}"].iloc[-1]), 2),
        }
    except Exception as e:
        return f"Lỗi khi xử lý dữ liệu: {str(e)}"


@tool
def get_company_info(ticker: str, category: str, filter_by: str = "working"):
    """Truy xuất thông tin công ty từ vnstock
    Args:
        ticker: Mã chứng khoán (ví dụ: 'FPT', 'HPG').
        category: Hạng mục thông tin bao gồm:
            - 'profile': Tổng quan công ty
            - 'ownership': Tỷ lệ sở hữu
            - 'shareholders': Danh sách cổ đông
            - 'subsidiaries': Công ty con
            - 'leadership': Ban lãnh đạo/Danh sách cán bộ
        filter_by: Chỉ dùng khi category='leadership'.
            - 'working': Lãnh đạo đang đương nhiệm (mặc định).
            - 'resigned': Lãnh đạo đã nghỉ việc.
            - 'all': Tất cả lịch sử lãnh đạo.
         LƯU Ý: với category='news' bạn nhận tin gốc chưa phân tích sentiment.
        Nếu cần đánh giá tâm lý thị trường, hãy dùng `get_market_sentiment` thay vì tool này.
    """
    company = Company(symbol=ticker, source="KBS")
    data_map = {
        "profile": company.overview,
        "ownership": company.ownership,
        "shareholders": company.shareholders,
        "subsidiaries": company.subsidiaries,
        "leadership": company.officers,
        # "news": company.news,
        # "earnings": company.earnings(),
        # "financials": company.financials(),
    }
    try:
        data_func = data_map.get(category)
        if not data_func:
            return f"Hạng mục {category} không được hỗ trợ."

        if category == "leadership":
            df = data_func(filter_by=filter_by)
        else:
            df = data_func()
        result = df.to_dict(orient="records")
        return result[:3]  # Giới hạn số lượng bản ghi
    except Exception as e:
        return f"Lỗi khi truy xuất dữ liệu: {str(e)}"


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
            return f"Không tìm thấy dữ liệu tâm lý gần đây cho mã {ticker}."

        results = []
        for r in rows:
            results.append(
                {
                    "title": r[0],
                    "sentiment": r[1],
                    "summary": r[2],
                    "date": str(r[3]),
                }
            )
        return results
