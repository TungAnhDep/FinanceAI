
import operator
import os
from typing import Annotated, List, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from tools import get_company_info, get_stock_data, get_market_sentiment


class AgentState(TypedDict):
    messages: Annotated[List, operator.add]
load_dotenv()
api_key = os.getenv("GOOGLE_API")
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0, api_key = api_key)
tools = [get_stock_data, get_company_info, get_market_sentiment]
llm_with_tools = llm.bind_tools(tools)

def call_gemini(state: AgentState):
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

def execute_tool_calls(state: AgentState):
    last_msg = state["messages"][-1]
    tool_outputs = []

    # Duyệt qua các function_call mà Gemini yêu cầu
    for tool_call in last_msg.tool_calls:
        selected_tool = {
            "get_stock_data": get_stock_data,
            "get_company_info": get_company_info,
            "get_market_sentiment": get_market_sentiment

        }[tool_call["name"]]

        output = selected_tool.invoke(tool_call["args"])
        tool_outputs.append(ToolMessage(tool_call_id=tool_call["id"], content=str(output)))

    return {"messages": tool_outputs}
workflow = StateGraph(AgentState)
workflow.add_node("gemini_brain", call_gemini)
workflow.add_node("tool_hands", execute_tool_calls)

workflow.set_entry_point("gemini_brain")
workflow.add_conditional_edges("gemini_brain", lambda x: "tool_hands" if x["messages"][-1].tool_calls else END)
workflow.add_edge("tool_hands", "gemini_brain")

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