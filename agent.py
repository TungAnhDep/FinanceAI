import json
import operator
import os
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig  # Thêm import
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from tools import (
    get_company_info,
    get_market_sentiment,
    get_stock_data,
)

FORMAT_INSTRUCTION = SystemMessage(
    content=(
        "Bạn là trình tổng hợp. Đọc transcript của agent và điền FinancialResponse:\n"
        "- summary: 3-5 câu tiếng Việt, kết thúc bằng câu cảnh báo tham khảo.\n"
        "- historical_data: từ trường `recent_data` trong tool result của get_stock_data.\n"
        "- technical_indicators: từ trường SMA, RSI trong tool result get_stock_data "
        "(mỗi chỉ báo là 1 phần tử với indicator, value, window_size).\n"
        "- sentimental: từ tool result get_market_sentiment (giữ nguyên title/label/score/summary/date).\n"
        "- company_profile: từ tool result get_company_info.\n"
        "- download_url: từ trường `download_url` trong tool result get_stock_data.\n"
        "Field nào không có dữ liệu trong transcript thì để None — KHÔNG bịa."
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


class FinancialResponse(BaseModel):
    """Cấu trúc phản hồi cuối cùng cho người dùng"""

    summary: str = Field(description="Tóm tắt ngắn gọn câu trả lời")
    sentimental: Optional[List[Sentimental]] = None
    company_profile: Optional[List[Dict[str, Any]]] = None
    historical_data: Optional[List[StockPriceRow]] = None
    technical_indicators: Optional[List[TechnicalAnalysis]] = None
    download_url: Optional[str] = None


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]


load_dotenv()
api_key = os.getenv("GOOGLE_API")
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0, api_key=api_key)
tools = [get_stock_data, get_company_info, get_market_sentiment]
llm_with_tools = llm.bind_tools(tools)
structured_llm = llm.with_structured_output(FinancialResponse)


def call_gemini(state: AgentState):
    current_date = datetime.now().strftime("%d/%m/%Y")
    system_instruction = SystemMessage(
        content=(
            f"Hôm nay là {current_date}. Bạn là Giám đốc phân tích đầu tư chứng khoán Việt Nam.\n\n"
            "## QUY TẮC GỌI TOOL\n"
            "- Giá lịch sử / OHLCV / SMA / RSI → `get_stock_data`. "
            "Đặt indicator=False nếu user chỉ hỏi giá thuần."
            "- Khi gọi get_stock_data, chọn sma_window theo horizon:"
            "Ngắn hạn (≤ 3 tháng) → sma_window=20"
            "Trung hạn (3-12 tháng) → sma_window=50"
            "Dài hạn (> 1 năm) → sma_window=200"
            "- rsi_window mặc định 14, không đổi trừ khi user yêu cầu.\n"
            "- Tâm lý thị trường, sentiment, đánh giá tin tức → LUÔN ưu tiên "
            "`get_market_sentiment` (đã có label/score được phân tích sẵn). "
            "- Hồ sơ, ban lãnh đạo, cổ đông, công ty con → `get_company_info` với category tương ứng.\n"
            "- Tuyệt đối KHÔNG bịa số liệu. Thiếu dữ liệu thì gọi tool — không trả lời từ kiến thức nội tại.\n"
            "- Nếu tool trả về chuỗi bắt đầu bằng 'Lỗi' hoặc 'Không có dữ liệu', "
            "báo lại cho user thay vì gọi lại tool đó nhiều lần.\n\n"
            "## KHUNG PHÂN TÍCH\n"
            "1. Kỹ thuật: RSI < 30 quá bán (Cơ hội), RSI > 70 quá mua (Rủi ro). "
            "Giá trên SMA → xu hướng tăng, dưới SMA → xu hướng giảm.\n"
            "2. Tâm lý: đối chiếu sentiment label/score. Đồng thuận với kỹ thuật → độ tin cậy cao hơn.\n"
            "3. Cơ bản: ban lãnh đạo, cơ cấu cổ đông để đánh giá uy tín dài hạn.\n\n"
            "## ĐỊNH DẠNG CÂU TRẢ LỜI\n"
            "Trả lời tiếng Việt, gồm 3 phần:\n"
            "(1) Kết luận ngắn — Cơ hội / Trung lập / Rủi ro.\n"
            "(2) Bằng chứng: 1-2 câu cho mỗi mảng kỹ thuật / tâm lý / cơ bản.\n"
            "(3) Cảnh báo: 'Đây là thông tin tham khảo, không phải lời khuyên tài chính.'"
        )
    )
    messages = [system_instruction] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def execute_tool_calls(state: AgentState, config: RunnableConfig):
    last_msg = state["messages"][-1]
    tool_outputs = []
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return {"messages": []}
    for tool_call in last_msg.tool_calls:
        selected_tool = {
            "get_stock_data": get_stock_data,
            "get_company_info": get_company_info,
            "get_market_sentiment": get_market_sentiment,
        }[tool_call["name"]]

        output = selected_tool.invoke(tool_call["args"], config=config)
        tool_outputs.append(
            ToolMessage(tool_call_id=tool_call["id"], content=str(output))
        )

    return {"messages": tool_outputs}


def format_output(state: AgentState):
    response = structured_llm.invoke([FORMAT_INSTRUCTION] + state["messages"])

    if hasattr(response, "model_dump"):
        data_dict = response.model_dump()
    elif isinstance(response, dict):
        data_dict = response
    else:
        data_dict = {"summary": str(response)}

    return {"messages": [AIMessage(content=json.dumps(data_dict, ensure_ascii=False))]}


def route_after_brain(state):
    if state["messages"][-1].tool_calls:
        return "tool_hands"
    return "summarizer"


workflow = StateGraph(AgentState)
workflow.add_node("gemini_brain", call_gemini)
workflow.add_node("tool_hands", execute_tool_calls)
workflow.add_node("summarizer", format_output)  # Node mới
workflow.set_entry_point("gemini_brain")
workflow.add_conditional_edges("gemini_brain", route_after_brain)
workflow.add_edge("tool_hands", "gemini_brain")
workflow.add_edge("summarizer", END)

app = workflow.compile()
