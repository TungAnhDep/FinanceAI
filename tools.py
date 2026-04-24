import os
from datetime import datetime, timedelta
from typing import Annotated, Optional  # Thêm import này

import dateparser  # type: ignore
import pandas_ta as ta  # noqa: F401
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool, InjectedToolArg
from vnstock import Company, Quote  # type: ignore

from database.db import NewsDB

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

@tool
def get_stock_data(ticker: str, start_date: Optional[str] = None, end_date: Optional[str] = None, months: Optional[int] = None, config: Annotated[Optional[RunnableConfig], InjectedToolArg] = None):
    """
    Truy xuất dữ liệu giá lịch sử.
    Args:
        ticker: Mã chứng khoán (ví dụ: 'FPT', 'VCB').
        start_date: Ngày bắt đầu (định dạng 'DD-MM-YYYY'). 
        end_date: Ngày kết thúc (định dạng 'DD-MM-YYYY'). Nếu không có, mặc định là hôm nay.
        months: Số tháng gần nhất muốn lấy dữ liệu (ví dụ: 3, 6). Nếu có start_date thì bỏ qua tham số này.
    """
    try:
        quote = Quote(symbol=ticker.upper(), source='KBS')
        
        current_date = datetime.now()
        if not end_date:
            end_date = current_date.strftime('%d-%m-%Y')
            
        if start_date:
            parsed_date = dateparser.parse(start_date, settings={'DATE_ORDER': 'DMY'})
            if parsed_date:
                start_date = parsed_date.strftime('%d-%m-%Y')
            df = quote.history(start=start_date, end=end_date, interval='d')
        elif months:
            # Lấy theo số tháng gần nhất
            start_calc = (current_date - timedelta(days=months * 30)).strftime('%d-%m-%Y')
            df = quote.history(start=start_calc, end=end_date, interval='d')
        else:
            # Mặc định lấy 100 ngày nếu không có yêu cầu cụ thể
            df = quote.history(length='100', interval='d')

        if df is None or df.empty:
            return f"Không có dữ liệu cho mã {ticker} trong khoảng thời gian yêu cầu."
        file_name = f"{ticker}_history_{datetime.now().strftime('%d%m%Y_%H%M%S')}.xlsx"
        file_path = os.path.join(EXPORT_DIR, file_name)
        df_export = df.reset_index()
        df_export.to_excel(file_path, index=False)
        recent_data = df_export.tail(5).to_dict(orient='records')
        base_url = "http://localhost:8000" # Giá trị mặc định
        
        if config and isinstance(config, dict):
            configurable = config.get("configurable", {})
            if isinstance(configurable, dict):
                base_url = configurable.get("base_url", base_url)
        download_link = f"{base_url}/download/{file_name}"
        return {
            "message": f"Đã xuất dữ liệu lịch sử của {ticker} vào file {file_name}.",
            "download_url": download_link,
            "excel_file_path": file_path,
            "recent_data": recent_data
        }
    except Exception as e:
        return f"Lỗi khi xử lý dữ liệu: {str(e)}"


@tool
def get_technical_indicators(ticker: str, days:  str = '100', interval: str = 'd', windows: int = 20):
    """Tính toán các chỉ báo kĩ thuật như SMA và RSI cho một mã chứng khoán.
    Args:        ticker: Mã chứng khoán (ví dụ: 'FPT', 'VCB').
        days: Số ngày lịch sử muốn lấy dữ liệu (mặc định là '100').
        interval: Khoảng thời gian giữa các điểm dữ liệu ('d' cho ngày, 'h' cho giờ, v.v.).
        windows: Số phiên để tính SMA và RSI (mặc định là 20).
    """
    quote = Quote(symbol=ticker, source='KBS')
    df = quote.history(length=days, interval=interval)
    df.ta.sma(length=windows, append=True)
    df.ta.rsi(length=windows, append=True)
    # latest = df.iloc[-1]
    result = {
        "SMA": df[f'SMA_{windows}'].iloc[-1],
        "RSI": df[f'RSI_{windows}'].iloc[-1]
    }
    # result = df.to_dict(orient='records')
    return result

@tool
def get_company_info(ticker: str, category: str, filter_by: str = 'working'):
    """Truy xuất thông tin công ty từ vnstock
    Args:
        ticker: Mã chứng khoán (ví dụ: 'FPT', 'HPG').
        category: Hạng mục thông tin bao gồm:
            - 'profile': Tổng quan công ty
            - 'ownership': Tỷ lệ sở hữu
            - 'shareholders': Danh sách cổ đông
            - 'subsidiaries': Công ty con
            - 'leadership': Ban lãnh đạo/Danh sách cán bộ
            - 'news': Tin tức doanh nghiệp
        filter_by: Chỉ dùng khi category='leadership'.
            - 'working': Lãnh đạo đang đương nhiệm (mặc định).
            - 'resigned': Lãnh đạo đã nghỉ việc.
            - 'all': Tất cả lịch sử lãnh đạo.
    """
    company = Company(symbol=ticker, source='KBS')
    data_map = {
        "profile": company.overview,
        "ownership": company.ownership,
        "shareholders": company.shareholders,
        "subsidiaries": company.subsidiaries,
        "leadership": company.officers,
        "news": company.news,
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
        result = df.to_dict(orient='records')
        return result[:3] # Giới hạn số lượng bản ghi
    except Exception as e:
        return f"Lỗi khi truy xuất dữ liệu: {str(e)}"

@tool
def get_market_sentiment(ticker: str, limit: int = 5):
    """Truy xuất điểm tâm lý và tóm tắt tin tức mới nhất của một mã cổ phiếu từ database."""
    
    with NewsDB() as db:
        query = """
            SELECT title, sentiment_score, summary, created_at 
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
            results.append({
                "title": r[0],
                "sentiment": "Positive" if r[1] > 0.3 else "Negative" if r[1] < -0.3 else "Neutral",
                "summary": r[2],
                "date": str(r[3])
            })
        return results