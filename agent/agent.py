# agent/agent.py
# PALA — LLM Agentic Loop
#
# Implements the Plan → Act → Observe → Critical-Think → Finalize loop
# described in Algorithm 1 of the PALA paper.
#
# The LLM (Llama 3.1 via Ollama) must respond in ONE of three JSON formats:
#
#   {"thought":    "I need to first list available tools..."}
#   {"tool_call":  {"name": "kpi_analyzer", "arguments": {"metric": "memory_utilization"}}}
#   {"final_answer": {"summary": "...", "result": {...}}}
#
# Safety mechanisms implemented (paper Section III-C):
#   1. Assumptions blocking   — refuse tool calls with missing required params
#   2. Goal tracking          — check intent satisfaction before finalising
#   3. Structured validation  — Pydantic-validate all tool arguments
#   4. Safety gatekeeping     — human confirmation for destructive actions

import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Generator

import requests

from config.settings import (
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    LLM_TEMPERATURE, LLM_MAX_TOKENS, MAX_AGENT_STEPS,
    MCP_SERVER_NAME,
)

log = logging.getLogger(__name__)

# Tools that require human confirmation before execution
DANGEROUS_ACTIONS = {"terminate_session", "apply", "schedule", "cancel"}

# ── system prompt (matches paper box "InAgent LLM System Prompt") ────────────
SYSTEM_PROMPT = """You are PALA, an advanced intent agent for 5G network operations.
You have access to a NWDAF (Network Data Analytics Function) system connected to a live Open5GS 5G core network.

RESPONSE FORMAT — you MUST respond with exactly one of these three JSON objects and nothing else:

{"thought": "your reasoning here"}
{"tool_call": {"name": "tool_name", "arguments": {"param": "value"}}}
{"final_answer": {"summary": "clear summary of what was done", "result": {}, "plot_path": null}}

AGENT WORKFLOW (follow in order):
1. Call list_available_tools to understand which tool to use
2. Plan: write a thought with numbered steps before acting
3. Discover Context: use session_manager list or kpi_analyzer to understand current state
4. Feasibility Check: ALWAYS call feasibility_checker before any action tool
5. Follow Your Plan: execute each step, recording observations
6. Explain Observations: after each tool result, write a thought interpreting what you found
7. Finalize Clearly: write a final_answer with a clear summary

CRITICAL RULES:
- Never assume tool parameters — always check first
- Never skip feasibility_checker before policy or session changes
- If a tool returns an error, write a thought explaining the error before retrying
- For ML/prediction tasks: use kpi_analyzer with run_ml=true
- For scheduled policies: use monitoring_manager with sub_action=schedule
- AMBR values are in bps. 1 Gbps = 1000000000. 200 Mbps = 200000000.
- Always respond in valid JSON — no markdown, no prose outside the JSON object
"""

SYSTEM_PROMPT_NATIVE_TOOLS = """You are PALA, an advanced intent agent for 5G network operations.
You have access to a NWDAF (Network Data Analytics Function) system connected to a live Open5GS 5G core network.

AGENT WORKFLOW (follow in order):
1. Call list_available_tools to understand which tool to use
2. Plan your steps before acting
3. Discover Context: use session_manager list or kpi_analyzer to understand current state
4. Feasibility Check: ALWAYS call feasibility_checker before any action tool
5. Execute your plan step by step
6. When complete: call final_answer with a clear summary

CRITICAL RULES:
- Never assume tool parameters — always check first
- Never skip feasibility_checker before policy or session changes
- If a tool returns an error, think about why before retrying
- For ML/prediction tasks: use kpi_analyzer with run_ml=true
- AMBR values are in bps. 1 Gbps = 1000000000. 200 Mbps = 200000000.
"""

# OpenAI function-calling schemas — used by OpenAICompatLLM when native_tools=True.
# Models trained on OpenAI conventions (GPT-OSS 120B, Llama 3.3, Qwen3, etc.)
# use the 'tools' parameter instead of emitting JSON in their text reply.
OPENAI_TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "list_available_tools",
        "description": "List all available NWDAF intent tools. Call this first.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "kpi_analyzer",
        "description": (
            "Fetch, analyse, and optionally forecast a network KPI metric. "
            "Available metrics: memory_utilization, active_ue_count, "
            "total_rx_bytes, total_tx_bytes, session_count, policy_count."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "metric":         {"type": "string",  "description": "Metric name."},
                "n_samples":      {"type": "integer", "description": "Number of samples (10-5000, default 500)."},
                "run_ml":         {"type": "boolean", "description": "Run ML forecast (default true)."},
                "forecast_steps": {"type": "integer", "description": "Future steps to forecast (default 50)."},
            },
            "required": ["metric"],
        },
    }},
    {"type": "function", "function": {
        "name": "feasibility_checker",
        "description": (
            "Pre-flight safety check before any network action. "
            "ALWAYS call before policy_manager, session_manager, or monitoring_manager."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action":       {"type": "string",  "description": "Action planned, e.g. 'increase_ambr'."},
                "target_slice": {"type": "string",  "description": "DNN/slice name."},
                "target_imsi":  {"type": "string",  "description": "Full IMSI if UE-specific."},
                "new_dl_ambr":  {"type": "integer", "description": "Proposed DL AMBR in bps."},
                "new_ul_ambr":  {"type": "integer", "description": "Proposed UL AMBR in bps."},
            },
            "required": ["action"],
        },
    }},
    {"type": "function", "function": {
        "name": "policy_manager",
        "description": (
            "Apply or retrieve slice/UE policies. "
            "Sub-actions: 'apply' (change AMBR), 'get' (read current policy). "
            "AMBR in bps. Always call feasibility_checker first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sub_action":   {"type": "string",  "enum": ["apply", "get"]},
                "target_slice": {"type": "string",  "description": "DNN/slice name."},
                "new_dl_ambr":  {"type": "integer", "description": "New DL AMBR in bps."},
                "new_ul_ambr":  {"type": "integer", "description": "New UL AMBR in bps."},
                "target_imsi":  {"type": "string",  "description": "Specific IMSI (omit for all)."},
                "reason":       {"type": "string",  "description": "Reason for audit log."},
            },
            "required": ["sub_action", "target_slice"],
        },
    }},
    {"type": "function", "function": {
        "name": "session_manager",
        "description": "Manage PDU sessions. Sub-actions: 'list', 'get', 'validate_qos', 'modify_qos', 'terminate'.",
        "parameters": {
            "type": "object",
            "properties": {
                "sub_action":    {"type": "string", "enum": ["list", "get", "validate_qos", "modify_qos", "terminate"]},
                "dnn":           {"type": "string", "description": "DNN filter for 'list'."},
                "imsi":          {"type": "string", "description": "Target IMSI."},
                "new_qos_index": {"type": "integer", "description": "New 5QI index (1-9)."},
                "new_arp":       {"type": "integer", "description": "New ARP priority (1-15)."},
            },
            "required": ["sub_action"],
        },
    }},
    {"type": "function", "function": {
        "name": "monitoring_manager",
        "description": "Schedule time-based policy changes and metric monitors. Sub-actions: 'schedule', 'list', 'cancel', 'monitor_metric'.",
        "parameters": {
            "type": "object",
            "properties": {
                "sub_action":      {"type": "string",  "enum": ["schedule", "list", "cancel", "monitor_metric"]},
                "slice_name":      {"type": "string",  "description": "DNN/slice for 'schedule'."},
                "action":          {"type": "string",  "description": "'increase_ambr' or 'decrease_ambr'."},
                "delta_pct":       {"type": "number",  "description": "Percentage change (e.g. 20 for +20%)."},
                "start_time":      {"type": "string",  "description": "Start time '16:27' or '4:27 PM'."},
                "end_time":        {"type": "string",  "description": "End time."},
                "days":            {"type": "array",   "items": {"type": "string"}, "description": "Days e.g. ['MON','TUE']."},
                "target_imsi":     {"type": "string",  "description": "Specific IMSI (omit for whole slice)."},
                "schedule_doc_id": {"type": "string",  "description": "ID for 'cancel'."},
                "metric":          {"type": "string",  "description": "Metric for 'monitor_metric'."},
                "threshold":       {"type": "number",  "description": "Alert threshold."},
                "interval_s":      {"type": "integer", "description": "Check interval in seconds (default 30)."},
            },
            "required": ["sub_action"],
        },
    }},
    {"type": "function", "function": {
        "name": "final_answer",
        "description": "Signal task completion. Call this when all required steps are done.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What was accomplished."},
                "result":  {"type": "object", "description": "Optional structured result."},
            },
            "required": ["summary"],
        },
    }},
]


# ── MCP client (calls the server subprocess via HTTP JSON-RPC) ────────────────
# In production the MCP server runs as a subprocess connected via stdio.
# For our architecture we run the tools directly (same process) using a
# lightweight in-process dispatcher so we don't need subprocess management.

class InProcessMCPClient:
    """
    Calls the NWDAF tool functions directly in-process.
    This avoids subprocess + stdio complexity while keeping the same
    interface as a real MCP client.
    """

    def __init__(self) -> None:
        # Import the dispatch function from the MCP server module
        from mcp_server.server import _dispatch
        self._dispatch = _dispatch

    def call_tool(self, name: str, arguments: dict) -> dict:
        try:
            result = self._dispatch(name, arguments)
            return result if isinstance(result, dict) else {"result": result}
        except Exception as exc:
            log.error("Tool %s failed: %s", name, exc, exc_info=True)
            return {"error": str(exc)}


# ── LLM backends ─────────────────────────────────────────────────────────────

class OllamaLLM:
    """Thin wrapper around the Ollama /api/chat endpoint."""

    def __init__(self) -> None:
        self.base_url = OLLAMA_BASE_URL
        self.model    = OLLAMA_MODEL

    def chat(self, messages: list[dict]) -> str:
        payload = {
            "model":   self.model,
            "messages": messages,
            "stream":  False,
            "options": {
                "temperature": LLM_TEMPERATURE,
                "num_predict": LLM_MAX_TOKENS,
            },
        }
        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except requests.RequestException as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc


_GEMINI_TOOLS_CACHE = None

def _get_gemini_tools(types):
    """Build (once) and return the Gemini Tool with all NWDAF function declarations."""
    global _GEMINI_TOOLS_CACHE
    if _GEMINI_TOOLS_CACHE is not None:
        return _GEMINI_TOOLS_CACHE
    S = types.Type.STRING; I = types.Type.INTEGER
    B = types.Type.BOOLEAN; N = types.Type.NUMBER; A = types.Type.ARRAY; O = types.Type.OBJECT
    _GEMINI_TOOLS_CACHE = types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="list_available_tools",
            description="List all available NWDAF intent tools. Call this first.",
            parameters=types.Schema(type=O, properties={}, required=[]),
        ),
        types.FunctionDeclaration(
            name="kpi_analyzer",
            description="Fetch, analyse, and optionally forecast a network KPI metric. Available metrics: memory_utilization, active_ue_count, total_rx_bytes, total_tx_bytes, session_count, policy_count.",
            parameters=types.Schema(type=O, properties={
                "metric":         types.Schema(type=S, description="Metric name."),
                "n_samples":      types.Schema(type=I, description="Number of samples (10-5000, default 500)."),
                "run_ml":         types.Schema(type=B, description="Run ML forecast (default true)."),
                "forecast_steps": types.Schema(type=I, description="Future steps to forecast (default 50)."),
            }, required=["metric"]),
        ),
        types.FunctionDeclaration(
            name="feasibility_checker",
            description="Pre-flight safety check before any network action. ALWAYS call before policy_manager, session_manager, or monitoring_manager.",
            parameters=types.Schema(type=O, properties={
                "action":       types.Schema(type=S, description="Action planned, e.g. 'increase_ambr'."),
                "target_slice": types.Schema(type=S, description="DNN/slice name."),
                "target_imsi":  types.Schema(type=S, description="Full IMSI if UE-specific."),
                "new_dl_ambr":  types.Schema(type=I, description="Proposed DL AMBR in bps."),
                "new_ul_ambr":  types.Schema(type=I, description="Proposed UL AMBR in bps."),
            }, required=["action"]),
        ),
        types.FunctionDeclaration(
            name="policy_manager",
            description="Apply or retrieve slice/UE policies. Sub-actions: 'apply' (change AMBR), 'get' (read policy). AMBR in bps. Always call feasibility_checker first.",
            parameters=types.Schema(type=O, properties={
                "sub_action":   types.Schema(type=S, description="'apply' or 'get'."),
                "target_slice": types.Schema(type=S, description="DNN/slice name."),
                "new_dl_ambr":  types.Schema(type=I, description="New DL AMBR in bps."),
                "new_ul_ambr":  types.Schema(type=I, description="New UL AMBR in bps."),
                "target_imsi":  types.Schema(type=S, description="Specific IMSI (omit for all)."),
                "reason":       types.Schema(type=S, description="Reason for audit log."),
            }, required=["sub_action", "target_slice"]),
        ),
        types.FunctionDeclaration(
            name="session_manager",
            description="Manage PDU sessions. Sub-actions: 'list', 'get', 'validate_qos', 'modify_qos', 'terminate'.",
            parameters=types.Schema(type=O, properties={
                "sub_action":    types.Schema(type=S, description="Action to perform."),
                "dnn":           types.Schema(type=S, description="DNN filter for 'list'."),
                "imsi":          types.Schema(type=S, description="Target IMSI."),
                "new_qos_index": types.Schema(type=I, description="New 5QI index (1-9)."),
                "new_arp":       types.Schema(type=I, description="New ARP priority (1-15)."),
            }, required=["sub_action"]),
        ),
        types.FunctionDeclaration(
            name="monitoring_manager",
            description="Schedule time-based policy changes and metric monitors. Sub-actions: 'schedule', 'list', 'cancel', 'monitor_metric'.",
            parameters=types.Schema(type=O, properties={
                "sub_action":      types.Schema(type=S, description="Sub-action to perform."),
                "slice_name":      types.Schema(type=S, description="DNN/slice for 'schedule'."),
                "action":          types.Schema(type=S, description="'increase_ambr' or 'decrease_ambr'."),
                "delta_pct":       types.Schema(type=N, description="Percentage change."),
                "start_time":      types.Schema(type=S, description="Start time."),
                "end_time":        types.Schema(type=S, description="End time."),
                "days":            types.Schema(type=A, items=types.Schema(type=S), description="Days e.g. ['MON','TUE']."),
                "target_imsi":     types.Schema(type=S, description="Specific IMSI."),
                "schedule_doc_id": types.Schema(type=S, description="ID for 'cancel'."),
                "metric":          types.Schema(type=S, description="Metric for 'monitor_metric'."),
                "threshold":       types.Schema(type=N, description="Alert threshold."),
                "interval_s":      types.Schema(type=I, description="Check interval (default 30)."),
            }, required=["sub_action"]),
        ),
        types.FunctionDeclaration(
            name="final_answer",
            description="Signal task completion. Call this when all required steps are done.",
            parameters=types.Schema(type=O, properties={
                "summary": types.Schema(type=S, description="What was accomplished."),
                "result":  types.Schema(type=O, description="Optional result data."),
            }, required=["summary"]),
        ),
    ])
    return _GEMINI_TOOLS_CACHE


def _convert_to_gemini_native(messages: list[dict], types) -> list:
    """Convert PALA message history to Gemini native function-calling format.

    Tool call pairs in PALA history:
        assistant: '{"tool_call": {"name": "X", "arguments": {...}}}'
        user:      'TOOL RESULT (X): {...}'

    become Gemini pairs:
        model:  Content(parts=[Part(function_call=FunctionCall(name, args))])
        user:   Content(parts=[Part(function_response=FunctionResponse(name, response))])

    Thoughts preceding a tool call are merged into the same model Content.
    """
    contents = []
    i = 0
    while i < len(messages):
        m    = messages[i]
        role = m["role"]
        raw  = (m.get("content") or "").strip()

        if role == "system":
            i += 1
            continue  # handled separately as system_instruction

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = {}

        if role == "assistant":
            if "thought" in parsed:
                thought_text = parsed["thought"]
                # Merge with following tool_call if present
                if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                    nxt_raw = (messages[i + 1].get("content") or "").strip()
                    try:
                        nxt = json.loads(nxt_raw)
                    except (json.JSONDecodeError, TypeError):
                        nxt = {}
                    if "tool_call" in nxt:
                        tc = nxt["tool_call"]
                        contents.append(types.Content(role="model", parts=[
                            types.Part(text=thought_text),
                            types.Part(function_call=types.FunctionCall(
                                name=tc.get("name", ""), args=tc.get("arguments", {})
                            )),
                        ]))
                        i += 2
                        # Consume matching tool result
                        if i < len(messages) and messages[i]["role"] == "user":
                            tr = messages[i].get("content", "")
                            m2 = re.match(r"TOOL RESULT \([^)]+\): (.+)$", tr, re.DOTALL)
                            if m2:
                                try:
                                    rd = json.loads(m2.group(1))
                                except (json.JSONDecodeError, TypeError):
                                    rd = {"text": m2.group(1)}
                                contents.append(types.Content(role="user", parts=[
                                    types.Part(function_response=types.FunctionResponse(
                                        name=tc.get("name", ""), response=rd
                                    ))
                                ]))
                                i += 1
                        continue
                # Standalone thought
                contents.append(types.Content(role="model", parts=[types.Part(text=thought_text)]))

            elif "tool_call" in parsed:
                tc = parsed["tool_call"]
                contents.append(types.Content(role="model", parts=[
                    types.Part(function_call=types.FunctionCall(
                        name=tc.get("name", ""), args=tc.get("arguments", {})
                    ))
                ]))
                i += 1
                # Consume matching tool result
                if i < len(messages) and messages[i]["role"] == "user":
                    tr = messages[i].get("content", "")
                    m2 = re.match(r"TOOL RESULT \([^)]+\): (.+)$", tr, re.DOTALL)
                    if m2:
                        try:
                            rd = json.loads(m2.group(1))
                        except (json.JSONDecodeError, TypeError):
                            rd = {"text": m2.group(1)}
                        contents.append(types.Content(role="user", parts=[
                            types.Part(function_response=types.FunctionResponse(
                                name=tc.get("name", ""), response=rd
                            ))
                        ]))
                        i += 1
                continue

            else:
                contents.append(types.Content(role="model", parts=[types.Part(text=raw)]))

        elif role == "user":
            # Skip bare TOOL RESULT messages (consumed above with their tool_call)
            if not raw.startswith("TOOL RESULT ("):
                contents.append(types.Content(role="user", parts=[types.Part(text=raw)]))

        i += 1
    return contents


class GeminiLLM:
    """Google Gemini / Gemma via the generativeai SDK.

    Set GEMINI_API_KEY in environment.  Model examples:
      gemma-4-31b-it            (Gemma 4 31B dense — strongest, 256K ctx, recommended)
      gemma-4-26b-a4b-it        (Gemma 4 26B MoE — 4B active params, faster)
      gemini-2.0-flash          (Gemini Flash — fast, free tier 15 RPM)
      gemini-1.5-pro            (Gemini Pro  — strongest, free tier 2 RPM)
      gemma-3-27b-it            (Gemma 3 27B — previous generation, 128K ctx)

    Free tier rate limits (Google AI Studio):
      Gemma 4:          15 RPM, 1 M TPM, 1500 RPD
      Gemini 2.0 Flash: 15 RPM, 1 M TPM, 1500 RPD
      Gemini 1.5 Pro:    2 RPM, 32 K TPM
    """

    def __init__(self, model: str | None = None, native_tools: bool = True) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")
        self.model_name   = model or os.environ.get("GEMINI_MODEL", "gemma-4-31b-it")
        self.native_tools = native_tools
        self._api_key     = api_key

    def chat(self, messages: list[dict]) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key, http_options={"timeout": 120_000})
        _supports_sysinstruct = not self.model_name.startswith("gemma-3")

        # Extract system text
        system_text = next((m["content"] for m in messages if m["role"] == "system"), "")

        if self.native_tools:
            contents = _convert_to_gemini_native(messages, types)

            # Gemma 3: inject system text into first user content's text part
            if system_text and not _supports_sysinstruct and contents:
                first = contents[0]
                for idx, p in enumerate(first.parts):
                    if hasattr(p, "text") and p.text:
                        preamble = f"[System context]\n{system_text}\n\n[User message]\n"
                        new_parts = [types.Part(text=preamble + p.text)] + list(first.parts[idx + 1:])
                        contents[0] = types.Content(role=first.role, parts=new_parts)
                        break

            config = types.GenerateContentConfig(
                temperature=LLM_TEMPERATURE,
                max_output_tokens=LLM_MAX_TOKENS,
                system_instruction=system_text if (system_text and _supports_sysinstruct) else None,
                tools=[_get_gemini_tools(types)],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode="AUTO")
                ),
            )
            try:
                resp = client.models.generate_content(
                    model=self.model_name, contents=contents, config=config,
                )
                # Translate function_call → PALA JSON format
                for part in resp.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        name = part.function_call.name
                        args = dict(part.function_call.args) if part.function_call.args else {}
                        if name == "final_answer":
                            return json.dumps({"final_answer": args})
                        return json.dumps({"tool_call": {"name": name, "arguments": args}})
                # No function call — text response
                text = (resp.text or "").strip()
                return json.dumps({"thought": text}) if text else json.dumps({"thought": "Processing..."})
            except Exception as exc:
                raise RuntimeError(f"Gemini/{self.model_name} request failed: {exc}") from exc

        else:
            # Original prompt-based JSON mode (kept for non-native fallback)
            contents = []
            for m in messages:
                if m["role"] == "system":
                    continue
                role = "model" if m["role"] == "assistant" else "user"
                contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
            if system_text and not _supports_sysinstruct and contents:
                first = contents[0]
                preamble = f"[System context]\n{system_text}\n\n[User message]\n"
                contents[0] = types.Content(
                    role=first.role, parts=[types.Part(text=preamble + first.parts[0].text)]
                )
            config = types.GenerateContentConfig(
                temperature=LLM_TEMPERATURE,
                max_output_tokens=LLM_MAX_TOKENS,
                system_instruction=system_text if (system_text and _supports_sysinstruct) else None,
            )
            try:
                resp = client.models.generate_content(
                    model=self.model_name, contents=contents, config=config,
                )
                return resp.text
            except Exception as exc:
                raise RuntimeError(f"Gemini/{self.model_name} request failed: {exc}") from exc


def _convert_to_openai_native(messages: list[dict]) -> list[dict]:
    """Convert PALA message history to OpenAI native function-calling format.

    PALA stores tool exchanges as:
        assistant: '{"tool_call": {"name": "X", "arguments": {...}}}'
        user:      'TOOL RESULT (X): {...}'

    OpenAI native format needs:
        assistant: {role, content, tool_calls: [{id, type, function}]}
        tool:      {role, tool_call_id, content}

    Thoughts preceding a tool call are merged into that assistant message so
    there are no consecutive assistant messages (which most APIs reject).
    """
    result: list[dict] = []
    call_counter = 0
    i = 0

    while i < len(messages):
        m    = messages[i]
        role = m["role"]
        raw  = (m.get("content") or "").strip()

        if role != "assistant":
            result.append(m)
            i += 1
            continue

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = {}

        if "thought" in parsed:
            thought_text = parsed["thought"]
            # If immediately followed by a tool_call, merge into one message
            if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                nxt_raw = (messages[i + 1].get("content") or "").strip()
                try:
                    nxt = json.loads(nxt_raw)
                except (json.JSONDecodeError, TypeError):
                    nxt = {}
                if "tool_call" in nxt:
                    tc  = nxt["tool_call"]
                    cid = f"call_{call_counter}"; call_counter += 1
                    result.append({
                        "role":       "assistant",
                        "content":    thought_text,
                        "tool_calls": [{"id": cid, "type": "function", "function": {
                            "name":      tc.get("name", ""),
                            "arguments": json.dumps(tc.get("arguments", {})),
                        }}],
                    })
                    i += 2
                    # Consume the matching tool result if present
                    if i < len(messages) and messages[i]["role"] == "user":
                        tr = messages[i].get("content", "")
                        m2 = re.match(r"TOOL RESULT \([^)]+\): (.+)$", tr, re.DOTALL)
                        if m2:
                            result.append({"role": "tool", "tool_call_id": cid, "content": m2.group(1)})
                            i += 1
                    continue
            # Standalone thought — pass as plain assistant text
            result.append({"role": "assistant", "content": thought_text})

        elif "tool_call" in parsed:
            tc  = parsed["tool_call"]
            cid = f"call_{call_counter}"; call_counter += 1
            result.append({
                "role":       "assistant",
                "content":    None,
                "tool_calls": [{"id": cid, "type": "function", "function": {
                    "name":      tc.get("name", ""),
                    "arguments": json.dumps(tc.get("arguments", {})),
                }}],
            })
            i += 1
            # Consume the matching tool result if present
            if i < len(messages) and messages[i]["role"] == "user":
                tr = messages[i].get("content", "")
                m2 = re.match(r"TOOL RESULT \([^)]+\): (.+)$", tr, re.DOTALL)
                if m2:
                    result.append({"role": "tool", "tool_call_id": cid, "content": m2.group(1)})
                    i += 1
            continue

        else:
            result.append({"role": "assistant", "content": raw})

        i += 1

    return result


class OpenAICompatLLM:
    """Any OpenAI-compatible endpoint (Together AI, Groq, local vLLM, etc.).

    Set OPENAI_COMPAT_KEY and OPENAI_COMPAT_BASE_URL in environment.
    Model set via OPENAI_COMPAT_MODEL env var or constructor arg.

    native_tools=True: pass OPENAI_TOOL_SCHEMAS via the 'tools' parameter and
    translate tool_calls responses back to PALA's JSON format automatically.
    Enables reliable tool use on models trained for OpenAI function calling
    (GPT-OSS 120B, Llama 3.3 70B, Qwen3, etc.) without changing the agent loop.
    """

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 native_tools: bool = False) -> None:
        from openai import OpenAI
        self.model        = model or os.environ.get("OPENAI_COMPAT_MODEL", "google/gemma-3-27b-it")
        self.native_tools = native_tools
        self.client       = OpenAI(
            api_key=os.environ.get("OPENAI_COMPAT_KEY", "dummy"),
            base_url=base_url or os.environ.get("OPENAI_COMPAT_BASE_URL", "https://api.together.xyz/v1"),
        )

    def chat(self, messages: list[dict]) -> str:
        try:
            if self.native_tools:
                native_msgs = _convert_to_openai_native(messages)
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=native_msgs,
                    tools=OPENAI_TOOL_SCHEMAS,
                    tool_choice="auto",
                    temperature=LLM_TEMPERATURE,
                    max_tokens=LLM_MAX_TOKENS,
                )
                msg = resp.choices[0].message
                # Translate native tool_calls → PALA JSON format
                if msg.tool_calls:
                    tc   = msg.tool_calls[0]
                    name = tc.function.name
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    if name == "final_answer":
                        return json.dumps({"final_answer": args})
                    return json.dumps({"tool_call": {"name": name, "arguments": args}})
                # No tool call — treat text as a thought
                text = (msg.content or "").strip()
                return json.dumps({"thought": text}) if text else json.dumps({"thought": "Processing..."})
            else:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=LLM_TEMPERATURE,
                    max_tokens=LLM_MAX_TOKENS,
                )
                return resp.choices[0].message.content
        except Exception as exc:
            raise RuntimeError(f"OpenAI-compat request failed: {exc}") from exc


class AnthropicLLM:
    """Anthropic Messages API backend for the E6 frontier tier.

    Uses the same PALA SYSTEM_PROMPT and the same three-JSON-object response
    contract as every other backend, so the frontier tier is not accidentally
    running a different protocol from the local tiers it is being compared
    against. That comparability is the whole point of E6.

    Set ANTHROPIC_API_KEY in the environment.
    """

    native_tools = False          # use the prompt-JSON contract, like OllamaLLM

    def __init__(self, model: str | None = None) -> None:
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        self.client = anthropic.Anthropic(api_key=key)

    def chat(self, messages: list[dict]) -> str:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [{"role": ("assistant" if m["role"] == "assistant" else "user"),
                  "content": m["content"]}
                 for m in messages if m["role"] != "system"]
        try:
            # temperature goes via extra_body: the installed SDK (anthropic
            # 1.0.0) removed it from the typed signature of messages.create,
            # and passing it directly raises TypeError. It must still be sent —
            # E6 compares capability tiers under IDENTICAL interfaces, and the
            # local tiers all run at LLM_TEMPERATURE, so a frontier tier left at
            # the API default would differ in sampling as well as in model.
            resp = self.client.messages.create(
                model=self.model,
                system=system,
                messages=convo,
                max_tokens=LLM_MAX_TOKENS,
                extra_body={"temperature": LLM_TEMPERATURE},
            )
        except Exception as exc:                                   # noqa: BLE001
            raise RuntimeError(f"Anthropic API error: {exc}") from exc
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def make_llm(backend: str = "ollama", model: str | None = None):
    """Factory — returns the right LLM instance for the given backend name.

    Supported backends:
        ollama       — local Ollama (qwen2.5:72b default)
        gemini       — Google AI Studio (gemma-4-31b-it default)
        gemma4       — alias for gemini with gemma-4-31b-it
        together     — Together AI (google/gemma-4-31b-it default)
        groq         — Groq (gemma2-9b-it default)
        openai_compat — any OpenAI-compatible endpoint via env vars
        anthropic    — Anthropic Messages API (ANTHROPIC_API_KEY); E6 frontier tier
    """
    if backend == "ollama":
        return OllamaLLM()
    elif backend in ("gemini", "gemma4", "gemma3"):
        m = model or (
            "gemma-4-31b-it" if backend == "gemma4" else
            "gemma-3-27b-it" if backend == "gemma3" else None
        )
        # gemma-3 does not support function calling on Google AI Studio
        nt = backend != "gemma3"
        return GeminiLLM(model=m, native_tools=nt)
    elif backend == "together":
        return OpenAICompatLLM(
            model=model or os.environ.get("TOGETHER_MODEL", "google/gemma-4-31b-it"),
            base_url="https://api.together.xyz/v1",
            native_tools=True,   # Together AI models support OpenAI function calling
        )
    elif backend in ("groq", "gpt_oss"):
        return OpenAICompatLLM(
            model=model or ("openai/gpt-oss-120b" if backend == "gpt_oss" else "gemma2-9b-it"),
            base_url="https://api.groq.com/openai/v1",
            native_tools=(backend == "gpt_oss"),  # GPT-OSS uses native tools; gemma2 uses prompt JSON
        )
    elif backend == "anthropic":
        return AnthropicLLM(model=model)
    elif backend == "openai_compat":
        return OpenAICompatLLM(model=model)
    else:
        raise ValueError(
            f"Unknown LLM backend: {backend!r}. "
            "Choose: ollama / gemini / gemma4 / gemma3 / together / groq / "
            "openai_compat / anthropic"
        )


# ── main agent class ──────────────────────────────────────────────────────────

class PALA:
    """
    The PALA agentic loop.
    Runs until goal achieved, max steps reached, or human cancels.
    """

    def __init__(self, human_confirm: bool = True, llm=None) -> None:
        self.llm            = llm if llm is not None else OllamaLLM()
        self.mcp            = InProcessMCPClient()
        self.human_confirm  = human_confirm
        self.history: list[dict] = []
        self.step_count     = 0
        self.goal_achieved  = False

    def run(self, intent: str) -> Generator[dict, None, None]:
        """
        Run the agentic loop for a given intent.
        Yields step dicts so the Streamlit UI can stream updates.

        Each yielded dict has keys:
            type:    "thought" | "tool_call" | "tool_result" | "final_answer" | "error"
            content: the payload
            step:    step number
        """
        log.info("PALA starting. Intent: %s", intent)
        _sys = (SYSTEM_PROMPT_NATIVE_TOOLS if getattr(self.llm, "native_tools", False)
                else SYSTEM_PROMPT)
        self.history = [
            {"role": "system",  "content": _sys},
            {"role": "user",    "content": f"NETWORK OPERATOR INTENT: {intent}"},
        ]
        self.step_count  = 0
        self.goal_achieved = False

        while self.step_count < MAX_AGENT_STEPS and not self.goal_achieved:
            self.step_count += 1
            log.debug("Step %d / %d", self.step_count, MAX_AGENT_STEPS)

            # ── LLM call ─────────────────────────────────────────────────
            try:
                raw_reply = self.llm.chat(self.history)
            except RuntimeError as exc:
                yield {"type": "error", "content": str(exc), "step": self.step_count}
                break

            # ── parse JSON ───────────────────────────────────────────────
            parsed, parse_error = _parse_json(raw_reply)
            if parse_error:
                # LLM gave malformed JSON — give it a nudge
                self.history.append({
                    "role":    "assistant",
                    "content": raw_reply,
                })
                self.history.append({
                    "role":    "user",
                    "content": (
                        "Your last response was not valid JSON. "
                        "Please respond with ONLY a JSON object using one of the three formats: "
                        '{"thought": "..."} or {"tool_call": {...}} or {"final_answer": {...}}'
                    ),
                })
                continue

            # ── thought ──────────────────────────────────────────────────
            if "thought" in parsed:
                thought = parsed["thought"]
                self.history.append({"role": "assistant", "content": raw_reply})
                yield {"type": "thought", "content": thought, "step": self.step_count}

            # ── tool call ────────────────────────────────────────────────
            elif "tool_call" in parsed:
                tc        = parsed["tool_call"]
                tool_name = tc.get("name", "")
                tool_args = tc.get("arguments", {})

                yield {
                    "type":    "tool_call",
                    "content": {"tool": tool_name, "arguments": tool_args},
                    "step":    self.step_count,
                }

                # Validate params before execution
                valid, val_msg = _validate_tool_call(tool_name, tool_args)
                if not valid:
                    obs = {"error": f"Parameter validation failed: {val_msg}"}
                    self.history.append({"role": "assistant", "content": raw_reply})
                    self.history.append({"role": "user",      "content": json.dumps(obs)})
                    yield {"type": "tool_result", "content": obs, "step": self.step_count}
                    continue

                # Safety gate — human confirmation for destructive tools
                if self.human_confirm and _is_dangerous(tool_name, tool_args):
                    approved = _request_human_confirmation(tool_name, tool_args)
                    if not approved:
                        obs = {"error": "Action rejected by human operator."}
                        self.history.append({"role": "assistant", "content": raw_reply})
                        self.history.append({"role": "user",      "content": json.dumps(obs)})
                        yield {"type": "tool_result", "content": obs, "step": self.step_count}
                        continue

                # Execute tool
                tool_result = self.mcp.call_tool(tool_name, tool_args)

                self.history.append({"role": "assistant", "content": raw_reply})
                self.history.append({
                    "role":    "user",
                    "content": f"TOOL RESULT ({tool_name}): {json.dumps(tool_result, default=str)}",
                })

                yield {
                    "type":    "tool_result",
                    "content": {"tool": tool_name, "result": tool_result},
                    "step":    self.step_count,
                }

            # ── final answer ─────────────────────────────────────────────
            elif "final_answer" in parsed:
                self.goal_achieved = True
                answer = parsed["final_answer"]
                self.history.append({"role": "assistant", "content": raw_reply})
                yield {"type": "final_answer", "content": answer, "step": self.step_count}
                log.info("PALA completed in %d steps.", self.step_count)
                break

            else:
                # Unknown structure — ask LLM to fix
                self.history.append({"role": "assistant", "content": raw_reply})
                self.history.append({
                    "role":    "user",
                    "content": (
                        "Response did not match any expected format. "
                        "Use ONLY: "
                        '{"thought": "..."} or '
                        '{"tool_call": {"name": "...", "arguments": {...}}} or '
                        '{"final_answer": {"summary": "..."}}'
                    ),
                })

        if not self.goal_achieved:
            yield {
                "type":    "error",
                "content": f"Agent stopped after {self.step_count} steps without reaching goal.",
                "step":    self.step_count,
            }


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> tuple[dict, str | None]:
    """
    Extract and parse the first JSON object from LLM output.
    Returns (parsed_dict, error_message).
    """
    text = text.strip()

    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass

    # Find first {...} block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0)), None
        except json.JSONDecodeError as exc:
            return {}, str(exc)

    return {}, "No JSON object found in LLM response"


def _validate_tool_call(tool_name: str, args: dict) -> tuple[bool, str]:
    """
    Check required arguments are present before calling a tool.
    Returns (is_valid, error_message).
    """
    required_params = {
        "kpi_analyzer":        ["metric"],
        "feasibility_checker": ["action"],
        "policy_manager":      ["sub_action", "target_slice"],
        "session_manager":     ["sub_action"],
        "monitoring_manager":  ["sub_action"],
    }

    sub_action_required = {
        ("policy_manager",    "apply"):   ["new_dl_ambr", "new_ul_ambr"],
        ("session_manager",   "get"):     ["imsi"],
        ("session_manager",   "validate_qos"): ["imsi", "dnn", "new_qos_index"],
        ("session_manager",   "modify_qos"):   ["imsi", "dnn", "new_qos_index"],
        ("session_manager",   "terminate"):    ["imsi", "dnn"],
        ("monitoring_manager","schedule"):     ["slice_name", "delta_pct", "start_time", "end_time"],
        ("monitoring_manager","cancel"):       ["schedule_doc_id"],
        ("monitoring_manager","monitor_metric"): ["metric", "threshold"],
    }

    for param in required_params.get(tool_name, []):
        if param not in args or args[param] is None:
            return False, f"Missing required parameter '{param}' for tool '{tool_name}'"

    # Reject unknown sub_actions so model gets a corrective error message
    valid_subactions: dict[str, set[str]] = {
        "policy_manager":     {"apply"},
        "session_manager":    {"terminate"},
        "monitoring_manager": {"schedule", "cancel"},
    }

    sub = args.get("sub_action")
    if sub and tool_name in valid_subactions:
        if sub not in valid_subactions[tool_name]:
            allowed = ", ".join(sorted(valid_subactions[tool_name]))
            return False, (
                f"Unknown sub_action '{sub}' for '{tool_name}'. "
                f"Valid sub_actions: {allowed}"
            )

    if sub:
        for param in sub_action_required.get((tool_name, sub), []):
            if param not in args or args[param] is None:
                return False, (
                    f"Missing required parameter '{param}' for "
                    f"'{tool_name}' sub_action='{sub}'"
                )

    return True, ""


def _is_dangerous(tool_name: str, args: dict) -> bool:
    """Return True if this tool call requires human approval."""
    if tool_name == "policy_manager" and args.get("sub_action") == "apply":
        return True
    if tool_name == "session_manager" and args.get("sub_action") == "terminate":
        return True
    if tool_name == "monitoring_manager" and args.get("sub_action") in ("schedule", "cancel"):
        return True
    return False


def _request_human_confirmation(tool_name: str, args: dict) -> bool:
    """
    Prompt the operator for confirmation before a dangerous action.
    In Streamlit the UI handles this; in CLI we use stdin.
    """
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"[SAFETY GATE] PALA wants to execute:", file=sys.stderr)
    print(f"  Tool:      {tool_name}", file=sys.stderr)
    print(f"  Arguments: {json.dumps(args, indent=4)}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    ans = input("Approve? [y/N] ").strip().lower()
    return ans in ("y", "yes")
