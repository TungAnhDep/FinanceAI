import os
import re
import time
from typing import Optional

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from config import EXTRACT_BATCH_SIZE, GEMINI_API_DELAY
from database.db import NewsDB

# Hint markers that anchor the actual financial-statement tables in BCTC PDFs.
# Cover pages + auditor letters often consume the first ~10k chars.
TABLE_MARKERS = re.compile(
    r"(BÁO CÁO KẾT QUẢ|BẢNG CÂN ĐỐI|LƯU CHUYỂN TIỀN TỆ|"
    r"KẾT QUẢ KINH DOANH|DOANH THU THUẦN)",
    re.IGNORECASE,
)
WINDOW_BEFORE = 500
WINDOW_AFTER = 18000  # generous — Gemini Flash handles 1M context easily


def slice_relevant(raw: str) -> str:
    """Return a content slice anchored at the first finance-table marker.
    Falls back to a larger head slice if no marker found (better than the
    old 12k cap that often missed the tables entirely)."""
    if not raw:
        return ""
    m = TABLE_MARKERS.search(raw)
    if not m:
        return raw[:25000]
    start = max(0, m.start() - WINDOW_BEFORE)
    return raw[start : start + WINDOW_AFTER]

load_dotenv()
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    api_key=os.getenv("GOOGLE_API"),
)


class Metric(BaseModel):
    metric: str = Field(
        description="Tên chỉ tiêu chuẩn hóa: revenue, gross_profit, "
        "operating_profit, npat, eps, total_assets, "
        "total_equity, total_liabilities, operating_cash_flow"
    )
    value: Optional[float] = Field(description="Giá trị (số nguyên, không có đơn vị)")
    unit: str = Field(
        description="'VND' nếu số nguyên đồng, 'million_VND' nếu triệu đồng, "
        "'VND/share' cho EPS"
    )


class ExtractedReport(BaseModel):
    statement_scope: str = Field(
        description="'consolidated' nếu là BCTC hợp nhất, "
        "'parent' nếu là BCTC công ty mẹ"
    )
    metrics: list[Metric]


extractor = llm.with_structured_output(ExtractedReport)

PROMPT = """Bạn là kế toán viên. Đọc BÁO CÁO TÀI CHÍNH sau và trích xuất các chỉ tiêu chính.

QUY TẮC:
- Chỉ trích xuất các chỉ tiêu sau khi xuất hiện rõ ràng:
  revenue (Doanh thu thuần), gross_profit (Lợi nhuận gộp),
  operating_profit (LN thuần từ hoạt động kinh doanh), npat (Lợi nhuận sau thuế),
  eps (Lãi cơ bản trên cổ phiếu), total_assets (Tổng tài sản),
  total_equity (Vốn chủ sở hữu), total_liabilities (Nợ phải trả),
  operating_cash_flow (Lưu chuyển tiền thuần từ HĐKD).
- Nếu một chỉ tiêu không xuất hiện hoặc không rõ → bỏ qua, KHÔNG bịa.
- Lấy giá trị KỲ HIỆN TẠI (cột mới nhất), không lấy kỳ so sánh.
- Đơn vị: nếu số liệu ghi 'triệu đồng' → unit='million_VND'.
  Nếu ghi 'đồng' → unit='VND'. EPS → unit='VND/share'.
- statement_scope: 'consolidated' nếu tiêu đề có 'hợp nhất',
  'parent' nếu có 'công ty mẹ' hoặc 'riêng'.

BÁO CÁO:
{content}
"""


def process_pending(batch_size: int = EXTRACT_BATCH_SIZE):
    """Batch script — commits per row so one bad PDF doesn't lose other progress.
    NOTE: this script intentionally bypasses the commit-on-exit semantics of
    NewsDB — long-running batch jobs need per-row durability."""
    with NewsDB() as db:
        db.cur.execute(
            """
            SELECT fr.id, fr.ticker, fr.period, fr.pdf_url, fr.raw_content, fr.report_type
            FROM financial_reports fr
            LEFT JOIN financial_metrics fm ON fm.source_pdf = fr.pdf_url
            WHERE fr.raw_content IS NOT NULL
              AND fm.source_pdf IS NULL
            ORDER BY fr.publish_date DESC NULLS LAST
            LIMIT %s
            """,
            (batch_size,),
        )
        rows = db.cur.fetchall()
        print(f"Found {len(rows)} report(s) pending extraction")

        for row_id, ticker, period, pdf_url, raw, _report_type in rows:
            if not raw or len(raw) < 200:
                continue
            try:
                content = slice_relevant(raw)
                result = extractor.invoke(PROMPT.format(content=content))
                inserted = 0
                for m in result.metrics:
                    if m.value is None:
                        continue
                    db.cur.execute(
                        """
                        INSERT INTO financial_metrics
                            (ticker, period, statement_scope, metric, value, unit, source_pdf)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (ticker, period, statement_scope, metric)
                        DO UPDATE SET value = EXCLUDED.value,
                                      unit = EXCLUDED.unit,
                                      source_pdf = EXCLUDED.source_pdf,
                                      extracted_at = CURRENT_TIMESTAMP
                        """,
                        (
                            ticker,
                            period,
                            result.statement_scope,
                            m.metric,
                            m.value,
                            m.unit,
                            pdf_url,
                        ),
                    )
                    inserted += 1
                db.conn.commit()
                print(
                    f"[{ticker}] {period} {result.statement_scope}: {inserted} metrics"
                )
                time.sleep(GEMINI_API_DELAY)
            except Exception as e:
                db.conn.rollback()
                print(f"[{ticker}] err id={row_id}: {e}")


if __name__ == "__main__":
    process_pending()
