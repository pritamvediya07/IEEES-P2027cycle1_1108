#!/usr/bin/env python3
# mcp_server/server.py
# NWDAF Intent Tools MCP Server
#
# Exposes all 5 PALA tools as MCP-callable functions.
# The PALA LLM connects to this server as an MCP client and discovers
# all available tools automatically via list_tools().
#
# Run:  python -m mcp_server.server
#       (or start it from the agent which uses stdio transport)
#
# Protocol: stdio MCP (Anthropic standard — same as used in Claude Desktop)
# Each tool call:
#   LLM → JSON request  → MCP server → tool function → JSON result → LLM
#
# MCP tool annotations used:
#   readOnlyHint=True   → safe for agent to call without human confirmation
#   readOnlyHint=False  → may modify network state → triggers safety check

import asyncio
import json
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool, TextContent, CallToolResult,
    ListToolsResult,
)
from pydantic import ValidationError

from tools.kpi_analyzer       import KPIAnalyzer
from tools.feasibility_checker import FeasibilityChecker
from tools.policy_manager      import PolicyManager
from tools.session_manager     import SessionManager
from tools.monitoring_manager  import MonitoringManager
from config.settings           import MCP_SERVER_NAME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MCP] %(levelname)s  %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# ── tool instances (module-level singletons) ──────────────────────────────────
kpi       = KPIAnalyzer()
feascheck = FeasibilityChecker()
policy    = PolicyManager()
session   = SessionManager()
monitor   = MonitoringManager()

# ── MCP server ────────────────────────────────────────────────────────────────
app = Server(MCP_SERVER_NAME)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Advertise all available NWDAF tools to the LLM."""
    return [

        # ── Tool 0: list available tools (agent always calls this first) ──
        Tool(
            name="list_available_tools",
            description=(
                "List all available NWDAF intent tools with their descriptions. "
                "Call this first to understand what capabilities are available."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
            annotations={"readOnlyHint": True},
        ),

        # ── Tool 1: KPI Analyzer ──────────────────────────────────────────
        Tool(
            name="kpi_analyzer",
            description=(
                "Fetch, analyse, and optionally forecast a network KPI metric. "
                "Use for intents like 'predict memory utilization', 'show throughput trend', "
                "'detect anomalies in session count'. "
                "Available metrics: memory_utilization, active_ue_count, "
                "total_rx_bytes, total_tx_bytes, session_count, policy_count."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "metric": {
                        "type":        "string",
                        "description": "Metric name. One of: memory_utilization, active_ue_count, "
                                       "total_rx_bytes, total_tx_bytes, session_count, policy_count.",
                    },
                    "n_samples": {
                        "type":        "integer",
                        "description": "Number of recent samples to analyse (10-5000, default 500).",
                        "default":     500,
                    },
                    "run_ml": {
                        "type":        "boolean",
                        "description": "Train a Random Forest and produce a forecast (default true).",
                        "default":     True,
                    },
                    "forecast_steps": {
                        "type":        "integer",
                        "description": "How many future steps to forecast (default 50).",
                        "default":     50,
                    },
                },
                "required": ["metric"],
            },
            annotations={"readOnlyHint": True},
        ),

        # ── Tool 2: Feasibility Checker ───────────────────────────────────
        Tool(
            name="feasibility_checker",
            description=(
                "Pre-flight safety check before any network-modifying action. "
                "ALWAYS call this before policy_manager, session_manager actions, "
                "or monitoring_manager schedule changes. "
                "Returns allowed=true/false with a reason."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type":        "string",
                        "description": "Action you plan to take, e.g. 'increase_ambr', 'terminate_session'.",
                    },
                    "target_slice": {
                        "type":        "string",
                        "description": "DNN/slice name, e.g. 'internet', 'streaming'.",
                    },
                    "target_imsi": {
                        "type":        "string",
                        "description": "Full IMSI if targeting a specific UE.",
                    },
                    "new_dl_ambr": {
                        "type":        "integer",
                        "description": "Proposed new DL AMBR in bps.",
                    },
                    "new_ul_ambr": {
                        "type":        "integer",
                        "description": "Proposed new UL AMBR in bps.",
                    },
                },
                "required": ["action"],
            },
            annotations={"readOnlyHint": True},
        ),

        # ── Tool 3: Policy Manager ────────────────────────────────────────
        Tool(
            name="policy_manager",
            description=(
                "Apply or retrieve slice/UE policies. "
                "Sub-actions: 'apply' to change AMBR, 'get' to read current policy. "
                "AMBR values in bps (1 Gbps = 1000000000). "
                "Always call feasibility_checker first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sub_action": {
                        "type":        "string",
                        "enum":        ["apply", "get"],
                        "description": "'apply' to change policy, 'get' to read current policy.",
                    },
                    "target_slice": {
                        "type":        "string",
                        "description": "DNN/slice name.",
                    },
                    "new_dl_ambr": {
                        "type":        "integer",
                        "description": "New DL AMBR in bps. Required for 'apply'.",
                    },
                    "new_ul_ambr": {
                        "type":        "integer",
                        "description": "New UL AMBR in bps. Required for 'apply'.",
                    },
                    "target_imsi": {
                        "type":        "string",
                        "description": "Specific IMSI, or omit for all subscribers on the slice.",
                    },
                    "reason": {
                        "type":        "string",
                        "description": "Human-readable reason for this change (audit log).",
                    },
                },
                "required": ["sub_action", "target_slice"],
            },
            annotations={"readOnlyHint": False},
        ),

        # ── Tool 4: Session Manager ───────────────────────────────────────
        Tool(
            name="session_manager",
            description=(
                "Manage PDU session lifecycles and QoS. "
                "Sub-actions: 'list' (all sessions), 'get' (specific IMSI), "
                "'validate_qos' (check proposed QoS change), "
                "'modify_qos' (apply QoS change), 'terminate' (end a session)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sub_action": {
                        "type":        "string",
                        "enum":        ["list", "get", "validate_qos", "modify_qos", "terminate"],
                        "description": "Action to perform.",
                    },
                    "dnn": {
                        "type":        "string",
                        "description": "DNN/slice filter for 'list' sub-action.",
                    },
                    "imsi": {
                        "type":        "string",
                        "description": "Target IMSI for get/modify_qos/terminate.",
                    },
                    "new_qos_index": {
                        "type":        "integer",
                        "description": "New 5QI index (1-9) for validate_qos / modify_qos.",
                    },
                    "new_arp": {
                        "type":        "integer",
                        "description": "New ARP priority (1-15) for validate_qos / modify_qos.",
                    },
                },
                "required": ["sub_action"],
            },
            annotations={"readOnlyHint": False},
        ),

        # ── Tool 5: Monitoring Manager ────────────────────────────────────
        Tool(
            name="monitoring_manager",
            description=(
                "Schedule time-based policy changes and set up metric monitors. "
                "Sub-actions: 'schedule' (time-windowed AMBR change), "
                "'list' (show active schedules), 'cancel' (remove a schedule), "
                "'monitor_metric' (alert when metric crosses threshold). "
                "Use 'schedule' for intents like "
                "'increase streaming slice by 20% from 4:27 PM to 4:30 PM on weekdays'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sub_action": {
                        "type":        "string",
                        "enum":        ["schedule", "list", "cancel", "monitor_metric"],
                        "description": "Sub-action to perform.",
                    },
                    "slice_name": {
                        "type":        "string",
                        "description": "DNN/slice name for 'schedule'.",
                    },
                    "action": {
                        "type":        "string",
                        "description": "Policy action: 'increase_ambr' or 'decrease_ambr'.",
                    },
                    "delta_pct": {
                        "type":        "number",
                        "description": "Percentage change (e.g. 20 for +20%).",
                    },
                    "start_time": {
                        "type":        "string",
                        "description": "Start time: '16:27' or '4:27 PM'.",
                    },
                    "end_time": {
                        "type":        "string",
                        "description": "End time: '16:30' or '4:30 PM'.",
                    },
                    "days": {
                        "type":        "array",
                        "items":       {"type": "string"},
                        "description": "Days: ['MON','TUE','WED','THU','FRI'] or 'WEEKDAYS'.",
                    },
                    "target_imsi": {
                        "type":        "string",
                        "description": "Specific IMSI, or omit for whole slice.",
                    },
                    "schedule_doc_id": {
                        "type":        "string",
                        "description": "ID returned by 'schedule' — needed for 'cancel'.",
                    },
                    "metric": {
                        "type":        "string",
                        "description": "Metric name for 'monitor_metric'.",
                    },
                    "threshold": {
                        "type":        "number",
                        "description": "Alert threshold for 'monitor_metric'.",
                    },
                    "interval_s": {
                        "type":        "integer",
                        "description": "Check interval in seconds for 'monitor_metric' (default 30).",
                        "default":     30,
                    },
                },
                "required": ["sub_action"],
            },
            annotations={"readOnlyHint": False},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch an MCP tool call to the appropriate handler."""
    log.info("Tool call: %s  args=%s", name, arguments)

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _dispatch, name, arguments
        )
    except Exception as exc:
        log.error("Tool %s raised: %s", name, exc, exc_info=True)
        result = {"error": str(exc), "tool": name}

    return [TextContent(type="text", text=json.dumps(result, default=str))]


# ── dispatcher ────────────────────────────────────────────────────────────────

def _dispatch(name: str, args: dict) -> dict:
    if name == "list_available_tools":
        return {
            "tools": [
                {"name": "kpi_analyzer",        "hint": "read-only analytics + ML forecast"},
                {"name": "feasibility_checker",  "hint": "always call before any action"},
                {"name": "policy_manager",       "hint": "apply / read slice AMBR policies"},
                {"name": "session_manager",      "hint": "list / modify / terminate PDU sessions"},
                {"name": "monitoring_manager",   "hint": "schedule time-based policy changes"},
            ]
        }

    elif name == "kpi_analyzer":
        return kpi.analyze(
            metric=args["metric"],
            n_samples=args.get("n_samples", 500),
            run_ml=args.get("run_ml", True),
            forecast_steps=args.get("forecast_steps", 50),
        )

    elif name == "feasibility_checker":
        return feascheck.check(
            action=args["action"],
            target_slice=args.get("target_slice"),
            target_imsi=args.get("target_imsi"),
            new_dl_ambr=args.get("new_dl_ambr"),
            new_ul_ambr=args.get("new_ul_ambr"),
            extra_params=args.get("extra_params", {}),
        )

    elif name == "policy_manager":
        sub = args.get("sub_action", "get")
        if sub == "apply":
            return policy.apply_policy(
                target_slice=args["target_slice"],
                new_dl_ambr=args["new_dl_ambr"],
                new_ul_ambr=args["new_ul_ambr"],
                target_imsi=args.get("target_imsi"),
                reason=args.get("reason", "PALA policy change"),
            )
        else:  # get
            return policy.get_current_policy(args["target_slice"])

    elif name == "session_manager":
        sub = args.get("sub_action", "list")
        if sub == "list":
            return session.list_sessions(args.get("dnn"))
        elif sub == "get":
            return session.get_session(args["imsi"], args.get("dnn"))
        elif sub == "validate_qos":
            return session.validate_qos_change(
                imsi=args["imsi"],
                dnn=args["dnn"],
                new_qos_index=args["new_qos_index"],
                new_arp=args.get("new_arp"),
            )
        elif sub == "modify_qos":
            return session.modify_session_qos(
                imsi=args["imsi"],
                dnn=args["dnn"],
                new_qos_index=args["new_qos_index"],
                new_arp=args.get("new_arp"),
            )
        elif sub == "terminate":
            return session.terminate_session(args["imsi"], args["dnn"])
        else:
            return {"error": f"Unknown session sub_action: {sub}"}

    elif name == "monitoring_manager":
        sub = args.get("sub_action")
        if sub == "schedule":
            return monitor.schedule_policy_change(
                slice_name=args["slice_name"],
                action=args.get("action", "increase_ambr"),
                delta_pct=args["delta_pct"],
                start_time=args["start_time"],
                end_time=args["end_time"],
                days=args.get("days"),
                target_imsi=args.get("target_imsi"),
            )
        elif sub == "list":
            return monitor.list_schedules()
        elif sub == "cancel":
            return monitor.cancel_schedule(args["schedule_doc_id"])
        elif sub == "monitor_metric":
            return monitor.monitor_metric(
                metric=args["metric"],
                threshold=args["threshold"],
                interval_s=args.get("interval_s", 30),
                action=args.get("action", "alert"),
            )
        else:
            return {"error": f"Unknown monitoring sub_action: {sub}"}

    else:
        return {"error": f"Unknown tool: {name}"}


# ── entry-point ───────────────────────────────────────────────────────────────

async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
