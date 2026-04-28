import json
import os
from typing import List

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

from agent import AgentState, FinancialResponse
from agent import app as agent_workflow

# Resolve `exports/` relative to this file, NOT the process cwd. Otherwise
# launching uvicorn from a different directory breaks /download URLs.
EXPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

app = FastAPI(title="Financial AI Agent API", version="1.0")
app.mount("/download", StaticFiles(directory=EXPORT_DIR), name="download")


class ChatRequest(BaseModel):
    query: str


class ChatResponse(BaseModel):
    query: str
    response: FinancialResponse
    steps: List[dict]


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: Request, chat_request: ChatRequest):
    try:
        base_url = str(request.base_url).rstrip("/")
        config = {"configurable": {"base_url": base_url}}
        input_state: AgentState = {
            "messages": [HumanMessage(content=chat_request.query)]
        }
        steps_log = []

        final_structured_data = FinancialResponse(summary="Đang xử lý...")

        async for event in agent_workflow.astream(
            input_state,
            config=config,
            stream_mode="updates",
        ):
            for node, value in event.items():
                last_msg = value["messages"][-1]

                step_info = {"node": node}

                if node == "summarizer":
                    content = last_msg.content
                    try:
                        data_dict = json.loads(content)
                        final_structured_data = FinancialResponse(**data_dict)
                        step_info["action"] = "Đã cấu trúc hóa dữ liệu thành công"
                    except (json.JSONDecodeError, TypeError, ValidationError) as e:
                        final_structured_data = FinancialResponse(
                            summary=f"Lỗi định dạng dữ liệu: {str(e)}"
                        )
                        step_info["action"] = "Lỗi khi cấu trúc hóa"

                elif (
                    node == "gemini_brain"
                    and hasattr(last_msg, "tool_calls")
                    and last_msg.tool_calls
                ):
                    step_info["action"] = f"Gọi hàm: {last_msg.tool_calls[0]['name']}"

                steps_log.append(step_info)

        return ChatResponse(
            query=chat_request.query, response=final_structured_data, steps=steps_log
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def health_check():
    return {"status": "running", "agent": "Financial Agent v1"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
