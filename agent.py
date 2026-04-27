import asyncio
import json
import operator
import os
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from tools import (
    get_analyst_reports,
    get_company_info,
    get_financial_metrics,
    get_financial_reports,
    get_market_sentiment,
    get_stock_data,
)


FORMAT_INSTRUCTION = SystemMessage(
    content=(
        "Bạn là trình tổng hợp. Đọc transcript của agent và điền FinancialResponse.\n"
        "Quy tắc map tool result → field:\n"
        "- summary: 3-5 câu tiếng Việt tổng hợp insight chính, kết thúc bằng "
        "'Đây là thông tin tham khảo, không phải lời khuyên tài chính.'\n"
        "- historical_data: từ trường recent_data của get_stock_data.\n"
        "- technical_indicators: từ SMA + RSI của get_stock_data — mỗi chỉ báo "
        "là 1 phần tử {indicator, value, window_size}.\n"
        "- sentimental: từ get_market_sentiment (giữ nguyên title/label/score/summary/date).\n"
        "- analyst_views: từ get_analyst_reports (giữ nguyên broker/report_type/"
        "target_price/recommendation/thesis/risks/publish_date/pdf_url).\n"
        "- financial_reports: từ get_financial_reports (report_type/period/"
        "audit_status/publish_date/pdf_url).\n"
        "- financial_metrics: từ get_financial_metrics — mỗi phần tử có "
        "period và metrics (dict tên_chỉ_tiêu → {value, unit}).\n"
        "- company_profile: từ get_company_info.\n"
        "- download_url: từ trường download_url của get_stock_data.\n"
        "Field nào không có dữ liệu trong transcript → để trống ([] hoặc None). "
        "TUYỆT ĐỐI không bịa số liệu hay diễn giải ngoài transcript."
    )
)


class TechnicalAnalysis(BaseModel):
    indicator: str = Field(description="Tên chỉ số (SMA, RSI...)")
    value: float = Field(description="Giá trị của chỉ số")
    window_size: int = Field(description="Chu kỳ tính toán")


class StockPriceRow(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class Sentimental(BaseModel):
    title: str
    label: str
    score: Optional[float] = None
    summary: Optional[str] = None
    date: Optional[str] = None


class AnalystView(BaseModel):
    broker: Optional[str] = None
    report_type: Optional[str] = None
    title: Optional[str] = None
    target_price: Optional[float] = None
    recommendation: Optional[str] = None
    thesis: Optional[str] = None
    risks: Optional[str] = None
    publish_date: Optional[str] = None
    pdf_url: Optional[str] = None


class FinancialReport(BaseModel):
    report_type: Optional[str] = None
    period: Optional[str] = None
    audit_status: Optional[str] = None
    publish_date: Optional[str] = None
    pdf_url: Optional[str] = None


class FinancialMetricSnapshot(BaseModel):
    period: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None


class FinancialResponse(BaseModel):
    """Cấu trúc phản hồi cuối cùng cho người dùng"""

    summary: str = Field(description="Tóm tắt ngắn gọn câu trả lời")
    sentimental: List[Sentimental] = Field(default_factory=list)
    company_profile: List[Dict[str, Any]] = Field(default_factory=list)
    historical_data: List[StockPriceRow] = Field(default_factory=list)
    technical_indicators: List[TechnicalAnalysis] = Field(default_factory=list)
    analyst_views: List[AnalystView] = Field(default_factory=list)
    financial_reports: List[FinancialReport] = Field(default_factory=list)
    financial_metrics: List[FinancialMetricSnapshot] = Field(default_factory=list)
    download_url: Optional[str] = None


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]


load_dotenv()
api_key = os.getenv("GOOGLE_API")
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0, api_key=api_key)
structured_llm = llm.with_structured_output(FinancialResponse)

tools = [
    get_stock_data,
    get_company_info,
    get_market_sentiment,
    get_analyst_reports,
    get_financial_reports,
    get_financial_metrics,
]
llm_with_tools = llm.bind_tools(tools)


def call_gemini(state: AgentState):
    current_date = datetime.now().strftime("%d/%m/%Y")
    system_instruction = SystemMessage(
        content=(
            f"Hôm nay {current_date}. Bạn là chuyên gia phân tích cổ phiếu Việt Nam.\n\n"
            "TOOL ROUTING:\n"
            "- Giá/SMA/RSI → get_stock_data (sma_window: 20 ngắn / 50 trung / 200 dài).\n"
            "- Sentiment đã phân tích → get_market_sentiment.\n"
            "- View CTCK / target price → get_analyst_reports.\n"
            "- Số liệu tài chính (doanh thu, NPAT, EPS) → get_financial_metrics. "
            "Empty → fallback get_financial_reports.\n"
            "- Hồ sơ/lãnh đạo/cổ đông → get_company_info.\n\n"
            "HORIZON:\n"
            "- ≤3 tháng: stock + sentiment + analyst. KHÔNG gọi metrics/BCTC.\n"
            "- 3-12 tháng: thêm metrics(['revenue','npat','eps']).\n"
            "- >1 năm: thêm company_info + metrics(n_periods=8).\n\n"
            "PHÂN TÍCH:\n"
            "- RSI<30 cơ hội, >70 rủi ro. Giá > SMA: tăng.\n"
            "- Đồng thuận sentiment + kỹ thuật → tin cậy cao.\n"
            "- Summary cuối phải có 'thông tin tham khảo'.\n"
            "Không bịa số. Tool 'Lỗi' → báo user, không retry."
            "GỌI TOOL SONG SONG: Khi cần nhiều tool để trả lời, gọi TẤT CẢ trong "
            "MỘT lượt. Ví dụ câu 'tư vấn FPT 1 tháng' cần stock + sentiment + analyst → "
            "gọi cả 3 cùng lúc, KHÔNG đợi tool này xong rồi mới gọi tool kia.\n"
        )
    )
    messages = [system_instruction] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


async def execute_tool_calls(state, config):
    last_msg = state["messages"][-1]
    print(f"[brain turn] {len(last_msg.tool_calls)} tool(s) in parallel")

    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return {"messages": []}

    tool_map = {
        "get_stock_data": get_stock_data,
        "get_company_info": get_company_info,
        "get_market_sentiment": get_market_sentiment,
        "get_analyst_reports": get_analyst_reports,
        "get_financial_reports": get_financial_reports,
        "get_financial_metrics": get_financial_metrics,
    }

    async def run_one(tc):
        tool = tool_map[tc["name"]]
        output = await asyncio.to_thread(tool.invoke, tc["args"], config=config)
        return ToolMessage(tool_call_id=tc["id"], content=str(output))

    outputs = await asyncio.gather(*(run_one(tc) for tc in last_msg.tool_calls))
    return {"messages": list(outputs)}


def format_output(state: AgentState):
    response = structured_llm.invoke([FORMAT_INSTRUCTION] + state["messages"])
    data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    return {"messages": [AIMessage(content=json.dumps(data, ensure_ascii=False))]}


def route_after_brain(state):
    last = state["messages"][-1]
    if last.tool_calls:
        return "tool_hands"
    return "summarizer"


workflow = StateGraph(AgentState)
workflow.add_node("gemini_brain", call_gemini)
workflow.add_node("tool_hands", execute_tool_calls)
workflow.add_node("summarizer", format_output)
workflow.set_entry_point("gemini_brain")
workflow.add_conditional_edges("gemini_brain", route_after_brain)
workflow.add_edge("tool_hands", "gemini_brain")
workflow.add_edge("summarizer", END)

app = workflow.compile()
