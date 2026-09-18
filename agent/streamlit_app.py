# agent/streamlit_app.py
# Streamlit Web UI for PALA
#
# Run:  streamlit run agent/streamlit_app.py
#       (from the nwdaf-pala project root)
#
# Provides:
#   - Intent input box (matches paper Figure 2)
#   - Live streaming of agent steps (thought / tool call / tool result)
#   - Final answer display with plot rendering
#   - Safety gate confirmation dialog for destructive actions
#   - System status panel (MongoDB, Ollama, Open5GS NF status)

import json
import time
import os
import sys

import streamlit as st
import requests

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PALA — NWDAF Intent Agent",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Streamlit prepends the script's own directory (agent/) to sys.path before
# running the script, which makes 'from agent.agent import ...' resolve to
# agent/agent/ (which doesn't exist). Fix: always put the project root at
# position 0, ahead of whatever Streamlit inserted.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if sys.path and sys.path[0] != ROOT:
    sys.path.insert(0, ROOT)
elif ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.agent import PALA
from config.db   import ping as db_ping
from config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL, NF_ADDRESSES


# ── sidebar: system status ────────────────────────────────────────────────────

def _check_ollama() -> bool:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return any(OLLAMA_MODEL in m for m in models)
    except Exception:
        return False


def _check_nf(url: str) -> bool:
    try:
        r = requests.get(url, timeout=2)
        return r.status_code < 500
    except Exception:
        return False


with st.sidebar:
    st.title("📡 PALA")
    st.caption("NWDAF-Based Intent LLM Agent")
    st.divider()

    st.subheader("System Status")
    mongo_ok  = db_ping()
    ollama_ok = _check_ollama()
    amf_ok    = _check_nf(NF_ADDRESSES["amf"])
    smf_ok    = _check_nf(NF_ADDRESSES["smf"])
    pcf_ok    = _check_nf(NF_ADDRESSES["pcf"])

    def _dot(ok: bool) -> str:
        return "🟢" if ok else "🔴"

    st.markdown(f"{_dot(mongo_ok)}  MongoDB (nwdaf_analytics)")
    st.markdown(f"{_dot(ollama_ok)}  Ollama ({OLLAMA_MODEL})")
    st.markdown(f"{_dot(amf_ok)}  Open5GS AMF")
    st.markdown(f"{_dot(smf_ok)}  Open5GS SMF")
    st.markdown(f"{_dot(pcf_ok)}  Open5GS PCF")

    if st.button("🔄 Refresh status"):
        st.rerun()

    st.divider()

    st.subheader("Example intents")
    examples = [
        "Predict memory utilization % for the internet slice based on 500 recent values.",
        "Increase the data rate for the 'streaming' slice by 20% from 4:27 PM until 4:30 PM on weekdays.",
        "Show me the current session count and any KPI anomalies in the last hour.",
        "What are the active PDU sessions on the internet DNN?",
        "Monitor the active_ue_count metric and alert me if it exceeds 8.",
    ]
    for ex in examples:
        if st.button(ex[:60] + ("…" if len(ex) > 60 else ""), key=ex):
            st.session_state["intent_input"] = ex

    st.divider()
    st.checkbox("Human approval for destructive actions",
                key="human_confirm", value=True)


# ── main area ─────────────────────────────────────────────────────────────────

st.title("NWDAF Intent Agent")
st.caption("Type a network management intent in natural language.")

if not mongo_ok:
    st.warning("⚠️  MongoDB is not reachable. Start the collector first: "
               "`python -m collector.collector`")

if not ollama_ok:
    st.error(f"❌  Ollama is not running or model '{OLLAMA_MODEL}' is not installed. "
             f"Run: `ollama pull {OLLAMA_MODEL}`")

# Intent input
intent = st.text_area(
    "Network Operator Intent",
    value=st.session_state.get("intent_input", ""),
    height=80,
    placeholder="e.g. Predict memory utilization for the internet slice based on 500 values",
    key="intent_area",
)

col1, col2 = st.columns([1, 5])
with col1:
    run_btn = st.button("▶  Run Intent", type="primary", disabled=not (mongo_ok and ollama_ok))
with col2:
    if st.button("🗑  Clear"):
        st.session_state["intent_input"] = ""
        st.rerun()

# ── agent execution ───────────────────────────────────────────────────────────

if run_btn and intent.strip():
    st.divider()
    st.subheader("Agent Execution")

    # Containers for streaming output
    steps_container   = st.container()
    confirm_container = st.empty()   # for safety gate dialog

    agent = PALA(human_confirm=st.session_state.get("human_confirm", True))

    # Monkey-patch human confirm for Streamlit (uses dialog instead of stdin)
    def _streamlit_confirm(tool_name: str, args: dict) -> bool:
        with confirm_container:
            st.warning(
                f"⚠️  **Safety Gate** — PALA wants to execute `{tool_name}`\n\n"
                f"```json\n{json.dumps(args, indent=2)}\n```"
            )
            col_y, col_n = st.columns(2)
            approved = False
            if col_y.button("✅ Approve", key="approve_btn"):
                approved = True
                confirm_container.empty()
            if col_n.button("❌ Reject",  key="reject_btn"):
                confirm_container.empty()
            return approved

    # Override the CLI confirmation with Streamlit dialog
    import agent.agent as _agent_module
    _agent_module._request_human_confirmation = _streamlit_confirm

    final_answer = None
    with steps_container:
        for step in agent.run(intent.strip()):
            step_type    = step["type"]
            step_content = step["content"]
            step_num     = step["step"]

            if step_type == "thought":
                with st.expander(f"💭 Step {step_num} — Thought", expanded=False):
                    st.write(step_content)

            elif step_type == "tool_call":
                tool = step_content["tool"]
                args = step_content["arguments"]
                with st.expander(f"🔧 Step {step_num} — Tool call: `{tool}`", expanded=True):
                    st.json(args)

            elif step_type == "tool_result":
                tool   = step_content.get("tool", "?")
                result = step_content.get("result", {})
                with st.expander(f"📊 Step {step_num} — Result: `{tool}`", expanded=False):
                    # Check if plot path in result
                    plot_path = (
                        result.get("ml", {}).get("plot_path")
                        if isinstance(result.get("ml"), dict)
                        else result.get("plot_path")
                    )
                    if plot_path and os.path.exists(plot_path):
                        st.image(plot_path, caption="Forecast plot", use_column_width=True)
                    else:
                        st.json(result)

            elif step_type == "final_answer":
                final_answer = step_content

            elif step_type == "error":
                st.error(f"❌ {step_content}")

    # Display final answer prominently
    if final_answer:
        st.divider()
        st.subheader("✅ Final Answer")
        summary = final_answer.get("summary", "")
        result  = final_answer.get("result",  {})
        st.success(summary)
        if result:
            st.json(result)

        # Render any plots referenced in the final answer
        plot_path = final_answer.get("plot_path")
        if not plot_path and isinstance(result, dict):
            ml = result.get("ml", {})
            if isinstance(ml, dict):
                plot_path = ml.get("plot_path")
        if plot_path and os.path.exists(plot_path):
            st.image(plot_path, caption="Forecast", use_column_width=True)

elif run_btn and not intent.strip():
    st.warning("Please enter an intent before clicking Run.")
