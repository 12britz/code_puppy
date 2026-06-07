"""/sidebar — live activity panel showing agent/tool/timing info.

Draws a persistent sidebar in the rightmost columns of the terminal
using ANSI cursor positioning. Rich Console output is constrained to
the remaining width so content doesn't collide.

UX:
    /sidebar          toggle on/off
    /sidebar on       enable
    /sidebar off      disable
    /sidebar wide     30 columns
    /sidebar narrow   22 columns

The sidebar refreshes at ~5 Hz while the agent is running and shows:
    - current agent + model
    - elapsed time
    - current tool being executed
    - streaming indicator
    - tool count + avg duration
    - recent tool history (last 4)
"""

from __future__ import annotations

import logging

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info

from . import console_patch
from .renderer import render_once, start_renderer, stop_renderer
from .state import STATE

logger = logging.getLogger(__name__)


# --- Lifecycle hooks --------------------------------------------------------
def _on_startup():
    if STATE.enabled:
        console_patch.install()
        start_renderer()


def _on_shutdown():
    stop_renderer()
    console_patch.uninstall()


# --- Agent hooks ------------------------------------------------------------
def _on_agent_run_start(agent_name, model_name, session_id=None):
    STATE.on_agent_start(agent_name, model_name, session_id)
    if STATE.enabled:
        render_once()


def _on_agent_run_end(
    agent_name,
    model_name,
    session_id=None,
    success=True,
    error=None,
    response_text=None,
    metadata=None,
):
    STATE.on_agent_end(success=success)
    if STATE.enabled:
        render_once()


# --- Tool hooks -------------------------------------------------------------
def _on_pre_tool_call(tool_name, tool_args, context=None):
    STATE.on_tool_start(tool_name)


def _on_post_tool_call(tool_name, tool_args, result, duration_ms, context=None):
    STATE.on_tool_end(tool_name, duration_ms)


# --- Stream hooks -----------------------------------------------------------
def _on_stream_event(event_type, event_data, agent_session_id=None):
    if event_type == "part_delta":
        STATE.on_stream_delta()
    elif event_type == "part_end":
        STATE.on_stream_end()


# --- Command handler --------------------------------------------------------
def _custom_help():
    return [
        ("sidebar", "Toggle the live activity sidebar (/sidebar on|off)"),
    ]


def _handle_sidebar(command: str, name: str):
    if name != "sidebar":
        return None

    parts = command.split()
    sub = parts[1].lower() if len(parts) > 1 else ""

    if sub == "on":
        STATE.enabled = True
        console_patch.install()
        start_renderer()
        render_once()
        emit_info("◧ Sidebar enabled.")
        return True

    if sub == "off":
        STATE.enabled = False
        stop_renderer()
        console_patch.uninstall()
        emit_info("◧ Sidebar disabled.")
        return True

    if sub == "wide":
        STATE.width = 30
        console_patch.install()
        render_once()
        emit_info("◧ Sidebar width → 30.")
        return True

    if sub == "narrow":
        STATE.width = 22
        console_patch.install()
        render_once()
        emit_info("◧ Sidebar width → 22.")
        return True

    # Toggle
    if sub == "":
        STATE.enabled = not STATE.enabled
        if STATE.enabled:
            console_patch.install()
            start_renderer()
            render_once()
            emit_info("◧ Sidebar enabled.")
        else:
            stop_renderer()
            console_patch.uninstall()
            emit_info("◧ Sidebar disabled.")
        return True

    emit_info("Usage: /sidebar [on|off|wide|narrow]")
    return True


# --- Register all hooks -----------------------------------------------------
register_callback("startup", _on_startup)
register_callback("shutdown", _on_shutdown)
register_callback("agent_run_start", _on_agent_run_start)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("post_tool_call", _on_post_tool_call)
register_callback("stream_event", _on_stream_event)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_sidebar)
