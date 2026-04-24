
import json
import operator
import os
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig # Thêm import
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from tools import (
    get_company_info,
    get_market_sentiment,
    get_stock_data,
    get_technical_indicators,
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

class FinancialResponse(BaseModel):
    """Cấu trúc phản hồi cuối cùng cho người dùng"""
    summary: str = Field(description="Tóm tắt ngắn gọn câu trả lời")
    company_profile: Optional[List[Dict[str, Any]]] = None
    historical_data: Optional[List[StockPriceRow]] = None
    technical_indicators: Optional[List[TechnicalAnalysis]] = None
    download_url: Optional[str] = None

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
load_dotenv()
api_key = os.getenv("GOOGLE_API")
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0, api_key = api_key)
tools = [get_stock_data, get_company_info, get_market_sentiment, get_technical_indicators]
llm_with_tools = llm.bind_tools(tools)
structured_llm = llm.with_structured_output(FinancialResponse)
def call_gemini(state: AgentState):
    current_date = datetime.now().strftime("%d/%m/%Y")
    system_instruction = SystemMessage(content=(
        f"Hôm nay là ngày {current_date}. Bạn là một trợ lý phân tích tài chính chuyên nghiệp. "
        "Khi người dùng yêu cầu dữ liệu, hãy kiểm tra ngày hiện tại để xác định xem đó là quá khứ hay tương lai. "
        "Nếu ngày yêu cầu nhỏ hơn ngày hiện tại, hãy sử dụng tool để truy xuất dữ liệu."
    ))
    messages = [system_instruction] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

def execute_tool_calls(state: AgentState, config: RunnableConfig):
    last_msg = state["messages"][-1]
    tool_outputs = []
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return {"messages": []}
    # Duyệt qua các function_call mà Gemini yêu cầu
    for tool_call in last_msg.tool_calls:
        selected_tool = {
            "get_stock_data": get_stock_data,
            "get_company_info": get_company_info,
            "get_market_sentiment": get_market_sentiment,
            "get_technical_indicators": get_technical_indicators
        }[tool_call["name"]]

        output = selected_tool.invoke(tool_call["args"], config = config)
        tool_outputs.append(ToolMessage(tool_call_id=tool_call["id"], content=str(output)))

    return {"messages": tool_outputs}
def format_output(state: AgentState):
    messages = state["messages"]
    # Yêu cầu LLM tổng hợp toàn bộ kết quả từ các ToolMessage trước đó
    response = structured_llm.invoke(messages) 
    
    if hasattr(response, "model_dump"):
        # Nếu là BaseModel (Pydantic v2)
        data_dict = response.model_dump()
    elif isinstance(response, dict):
        # Nếu đã là dict
        data_dict = response
    else:
        # Trường hợp dự phòng nếu AI trả về chuỗi hoặc kiểu khác
        data_dict = {"summary": str(response)}
    
    json_content = json.dumps(data_dict) 
    
    return {"messages": [AIMessage(content=json_content)]}
def route_after_brain(state):
    if state["messages"][-1].tool_calls:
        return "tool_hands"
    return "summarizer" # Nếu không gọi tool nữa thì đi vào node định dạng
workflow = StateGraph(AgentState)
workflow.add_node("gemini_brain", call_gemini)
workflow.add_node("tool_hands", execute_tool_calls)
workflow.add_node("summarizer", format_output) # Node mới
workflow.set_entry_point("gemini_brain")
workflow.add_conditional_edges("gemini_brain", route_after_brain)
workflow.add_edge("tool_hands", "gemini_brain")
workflow.add_edge("summarizer", END)

app = workflow.compile()

# def run_financial_agent(query: str):
#     print(f"User Request: {query}")
#     for event in app.stream({"messages": [HumanMessage(content=query)]}):
#         for node, value in event.items():
#             last_msg = value["messages"][-1]
#             if node == "gemini_brain":
#                 if last_msg.tool_calls:
#                     print(f"--- AI quyết định gọi hàm: {last_msg.tool_calls[0]['name']} ---")
#                 else:
#                     print(f"--- AI trả lời: {last_msg.content} ---")
#             elif node == "tool_hands":
#                 print(f"--- Hệ thống đã lấy dữ liệu: {last_msg.content} ---")

# if __name__ == "__main__":
#     user_query = "Cho tôi biết giá lịch sử FPT trong vòng 30 ngày và thông tin về lãnh đạo công ty này."
#     run_financial_agent(user_query)