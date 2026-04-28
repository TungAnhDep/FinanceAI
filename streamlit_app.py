"""Minimal Streamlit frontend for the Vietnamese Stock AI Agent.

Run with:
    streamlit run streamlit_app.py

Requires the FastAPI agent to be running on AGENT_URL (default http://localhost:8000).
Override with: AGENT_URL=http://my-host:8000 streamlit run streamlit_app.py
"""

import os

import requests
import streamlit as st

AGENT_URL = os.getenv(
    "AGENT_URL", "http://localhost:8000"
)  # Replace with your agent's URL
TIMEOUT_SECONDS = 120


st.set_page_config(
    page_title="Vietnamese Stock AI Agent",
    page_icon="📈",
    layout="wide",
)


def call_agent(query: str) -> dict:
    """POST to /chat. Raises on HTTP error."""
    resp = requests.post(
        f"{AGENT_URL}/chat",
        json={"query": query},
        timeout=TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def render_response(payload: dict) -> None:
    """Render a single agent response (summary + structured tabs + steps)."""
    response = payload.get("response", {}) or {}

    summary = response.get("summary") or ""
    if summary:
        st.markdown(summary)

    download_url = response.get("download_url")
    if download_url:
        st.link_button("📥 Tải dữ liệu Excel", download_url)

    sections = [
        ("Kỹ thuật", "technical_indicators", _render_technical),
        ("Tâm lý", "sentimental", _render_sentiment),
        ("CTCK", "analyst_views", _render_analyst),
        ("Chỉ tiêu", "financial_metrics", _render_metrics),
        ("BCTC", "financial_reports", _render_reports),
        ("Hồ sơ", "company_profile", _render_profile),
    ]
    active = [(label, key, fn) for label, key, fn in sections if response.get(key)]
    if active:
        tabs = st.tabs([label for label, _, _ in active])
        for tab, (_, key, render_fn) in zip(tabs, active):
            with tab:
                render_fn(response[key])

    steps = payload.get("steps") or []
    if steps:
        with st.expander("🔍 Các bước thực hiện"):
            for step in steps:
                node = step.get("node", "?")
                action = step.get("action", "")
                st.markdown(f"- **{node}**" + (f" — {action}" if action else ""))


def _render_technical(data: list) -> None:
    cols = st.columns(min(len(data), 4) or 1)
    for i, ind in enumerate(data):
        with cols[i % len(cols)]:
            window = ind.get("window_size")
            label = f"{ind.get('indicator', '?')}" + (f" ({window})" if window else "")
            st.metric(label, ind.get("value", "—"))


def _render_sentiment(data: list) -> None:
    color_map = {"Positive": "🟢", "Negative": "🔴", "Neutral": "⚪"}
    for s in data:
        label = s.get("label") or s.get("sentiment") or ""
        marker = color_map.get(label, "•")
        st.markdown(f"{marker} **{s.get('title', '')}**")
        meta = " — ".join(filter(None, [s.get("date"), label]))
        if meta:
            st.caption(meta)
        if s.get("summary"):
            st.write(s["summary"])
        st.divider()


def _render_analyst(data: list) -> None:
    for v in data:
        broker = v.get("broker", "—")
        rec = v.get("recommendation", "")
        target = v.get("target_price")
        st.markdown(f"**{broker}** — {rec or 'N/A'}")
        if target:
            st.caption(f"Giá mục tiêu: {target:,.0f} VND")
        if v.get("thesis"):
            st.write(v["thesis"])
        if v.get("risks"):
            st.markdown(f"_Rủi ro: {v['risks']}_")
        if v.get("pdf_url"):
            st.link_button("📄 PDF", v["pdf_url"])
        st.divider()


def _render_metrics(data: list) -> None:
    """Pivot list of {period, metrics:{name:{value, unit}}} into a table."""
    rows = []
    for snapshot in data:
        period = snapshot.get("period", "")
        metrics = snapshot.get("metrics") or {}
        row = {"Kỳ": period}
        for name, info in metrics.items():
            if isinstance(info, dict):
                row[name] = info.get("value")
            else:
                row[name] = info
        rows.append(row)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_reports(data: list) -> None:
    for r in data:
        st.markdown(f"**{r.get('report_type', '')}** — {r.get('period', '')}")
        meta_bits = []
        if r.get("audit_status"):
            meta_bits.append(r["audit_status"])
        if r.get("publish_date"):
            meta_bits.append(r["publish_date"])
        if meta_bits:
            st.caption(" • ".join(meta_bits))
        if r.get("pdf_url"):
            st.link_button("📄 PDF", r["pdf_url"])
        st.divider()


def _render_profile(data: list) -> None:
    st.json(data)


# ─── Page layout ────────────────────────────────────────────────────────────

st.title("📈 Vietnamese Stock AI Agent")

with st.sidebar:
    st.markdown("### Ví dụ")
    examples = [
        "Tư vấn FPT trong 1 tháng tới",
        "Doanh thu công ty mẹ FPT năm 2025",
        "FPT có nên mua không? Giá mục tiêu CTCK là bao nhiêu?",
        "Ai là CEO của FPT?",
        "RSI và SMA của VNM 3 tháng qua",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state["pending_query"] = ex
            st.rerun()

    st.divider()
    if st.button("🗑️ Xoá lịch sử", use_container_width=True):
        st.session_state["messages"] = []
        st.rerun()


if "messages" not in st.session_state:
    st.session_state["messages"] = []

# Replay history
for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.markdown(msg["content"])
        else:
            render_response(msg["content"])

# Input — either a fresh chat input or a queued example from the sidebar
query = st.chat_input("Hỏi về cổ phiếu Việt Nam...")
if not query and "pending_query" in st.session_state:
    query = st.session_state.pop("pending_query")

if query:
    st.session_state["messages"].append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        with st.spinner("Đang phân tích..."):
            try:
                payload = call_agent(query)
                st.session_state["messages"].append(
                    {"role": "assistant", "content": payload}
                )
                render_response(payload)
            except requests.HTTPError as e:
                st.error(f"Agent lỗi {e.response.status_code}: {e.response.text}")
            except requests.RequestException as e:
                st.error(f"Không kết nối được agent ({AGENT_URL}): {e}")
            except Exception as e:
                st.error(f"Lỗi: {e}")
