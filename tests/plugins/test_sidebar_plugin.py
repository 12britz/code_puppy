"""Tests for the /sidebar live activity panel plugin."""

from __future__ import annotations

from unittest.mock import patch


from code_puppy.plugins.sidebar.state import STATE
from code_puppy.plugins.sidebar.renderer import (
    _build_lines,
    _format_duration,
    _format_ms,
    _truncate,
)


# ---------------------------------------------------------------------------
# state.py
# ---------------------------------------------------------------------------
class TestSidebarState:
    def setup_method(self):
        """Reset singleton state before each test."""
        STATE.enabled = True
        STATE.width = 26
        STATE.agent_name = ""
        STATE.model_name = ""
        STATE.session_id = None
        STATE.agent_running = False
        STATE.run_started = 0.0
        STATE.current_tool = None
        STATE.current_tool_started = 0.0
        STATE.tool_history.clear()
        STATE.tool_count = 0
        STATE.tool_total_ms = 0.0
        STATE.tokens_streamed = 0
        STATE.is_streaming = False

    def test_agent_start(self):
        STATE.on_agent_start("puppy", "gpt-4", "s1")
        assert STATE.agent_running
        assert STATE.agent_name == "puppy"
        assert STATE.model_name == "gpt-4"
        assert STATE.session_id == "s1"
        assert STATE.run_started > 0

    def test_agent_end(self):
        STATE.on_agent_start("puppy", "gpt-4")
        STATE.on_agent_end(success=True)
        assert not STATE.agent_running
        assert STATE.current_tool is None

    def test_tool_lifecycle(self):
        STATE.on_agent_start("puppy", "gpt-4")
        STATE.on_tool_start("read_file")
        assert STATE.current_tool == "read_file"

        STATE.on_tool_end("read_file", 200.0, True)
        assert STATE.current_tool is None
        assert STATE.tool_count == 1
        assert STATE.tool_total_ms == 200.0
        assert len(STATE.tool_history) == 1
        assert STATE.tool_history[0].name == "read_file"
        assert STATE.tool_history[0].success

    def test_multiple_tools(self):
        STATE.on_agent_start("puppy", "gpt-4")
        for i in range(5):
            STATE.on_tool_start(f"tool_{i}")
            STATE.on_tool_end(f"tool_{i}", 100.0)
        assert STATE.tool_count == 5
        assert STATE.tool_total_ms == 500.0
        assert len(STATE.tool_history) == 5

    def test_tool_history_maxlen(self):
        STATE.on_agent_start("puppy", "gpt-4")
        for i in range(15):
            STATE.on_tool_start(f"tool_{i}")
            STATE.on_tool_end(f"tool_{i}", 10.0)
        assert len(STATE.tool_history) == 8  # maxlen=8

    def test_stream_events(self):
        STATE.on_stream_delta()
        STATE.on_stream_delta()
        STATE.on_stream_delta()
        assert STATE.tokens_streamed == 3
        assert STATE.is_streaming

        STATE.on_stream_end()
        assert not STATE.is_streaming

    def test_agent_start_resets_counters(self):
        STATE.on_agent_start("puppy", "gpt-4")
        STATE.on_tool_start("x")
        STATE.on_tool_end("x", 100.0)
        STATE.on_stream_delta()

        STATE.on_agent_start("puppy2", "claude")
        assert STATE.agent_name == "puppy2"
        assert STATE.model_name == "claude"
        assert STATE.tool_count == 0
        assert STATE.tokens_streamed == 0
        assert STATE.current_tool is None

    def test_snapshot_returns_dict(self):
        STATE.on_agent_start("puppy", "gpt-4")
        STATE.on_tool_start("grep")
        snap = STATE.snapshot()
        assert isinstance(snap, dict)
        assert snap["agent_name"] == "puppy"
        assert snap["current_tool"] == "grep"
        assert snap["agent_running"]
        assert snap["elapsed"] >= 0
        assert snap["tool_elapsed"] >= 0

    def test_snapshot_idle(self):
        snap = STATE.snapshot()
        assert not snap["agent_running"]
        assert snap["agent_name"] == ""


# ---------------------------------------------------------------------------
# renderer.py — helper functions
# ---------------------------------------------------------------------------
class TestRendererHelpers:
    def test_truncate_short(self):
        assert _truncate("hi", 10) == "hi"

    def test_truncate_exact(self):
        assert _truncate("hello", 5) == "hello"

    def test_truncate_long(self):
        assert _truncate("hello world", 6) == "hello…"

    def test_format_duration_seconds(self):
        assert _format_duration(3.7) == "3.7s"

    def test_format_duration_minutes(self):
        assert _format_duration(125.5) == "2m6s"

    def test_format_ms_small(self):
        assert _format_ms(450) == "450ms"

    def test_format_ms_large(self):
        assert _format_ms(2500) == "2.5s"


class TestBuildLines:
    def setup_method(self):
        STATE.enabled = True
        STATE.agent_name = ""
        STATE.model_name = ""
        STATE.agent_running = False
        STATE.tool_history.clear()
        STATE.tool_count = 0
        STATE.tool_total_ms = 0.0
        STATE.tokens_streamed = 0
        STATE.is_streaming = False
        STATE.current_tool = None

    def test_idle_state(self):
        snap = STATE.snapshot()
        lines = _build_lines(snap, 24)
        assert len(lines) >= 2  # header + divider + idle
        content = "".join(lines)
        assert "idle" in content.lower() or "SIDEBAR" in content

    def test_running_agent(self):
        STATE.on_agent_start("code-puppy", "gpt-4o")
        snap = STATE.snapshot()
        lines = _build_lines(snap, 24)
        content = "".join(lines)
        assert "code-puppy" in content
        assert "gpt-4o" in content

    def test_running_with_tool(self):
        STATE.on_agent_start("code-puppy", "gpt-4o")
        STATE.on_tool_start("read_file")
        snap = STATE.snapshot()
        lines = _build_lines(snap, 24)
        content = "".join(lines)
        assert "read_file" in content

    def test_streaming(self):
        STATE.on_agent_start("code-puppy", "gpt-4o")
        STATE.on_stream_delta()
        snap = STATE.snapshot()
        lines = _build_lines(snap, 24)
        content = "".join(lines)
        assert "streaming" in content.lower() or "chunk" in content.lower()

    def test_with_tool_history(self):
        STATE.on_agent_start("code-puppy", "gpt-4o")
        STATE.on_tool_start("grep")
        STATE.on_tool_end("grep", 50.0)
        STATE.on_tool_start("read_file")
        STATE.on_tool_end("read_file", 120.0)
        snap = STATE.snapshot()
        lines = _build_lines(snap, 24)
        content = "".join(lines)
        assert "2 tools" in content
        assert "recent" in content.lower()

    def test_done_state(self):
        STATE.on_agent_start("code-puppy", "gpt-4o")
        STATE.on_agent_end()
        snap = STATE.snapshot()
        lines = _build_lines(snap, 24)
        content = "".join(lines)
        assert "done" in content.lower()


# ---------------------------------------------------------------------------
# console_patch.py
# ---------------------------------------------------------------------------
class TestConsolePatch:
    def test_effective_width(self):
        from code_puppy.plugins.sidebar.console_patch import _effective_width

        w = _effective_width()
        assert w >= 40

    def test_install_uninstall_roundtrip(self):
        from rich.console import Console

        from code_puppy.plugins.sidebar.console_patch import (
            _original_init,
            install,
            uninstall,
        )

        install()
        assert Console.__init__ is not _original_init
        uninstall()
        assert Console.__init__ is _original_init


# ---------------------------------------------------------------------------
# register_callbacks.py — command handler
# ---------------------------------------------------------------------------
class TestCommandHandler:
    def setup_method(self):
        STATE.enabled = True
        STATE.width = 26

    def test_ignores_other_commands(self):
        from code_puppy.plugins.sidebar.register_callbacks import _handle_sidebar

        assert _handle_sidebar("/theme ocean", "theme") is None

    def test_toggle_off(self):
        from code_puppy.plugins.sidebar.register_callbacks import _handle_sidebar

        STATE.enabled = True
        with (
            patch("code_puppy.plugins.sidebar.register_callbacks.stop_renderer"),
            patch("code_puppy.plugins.sidebar.register_callbacks.console_patch"),
            patch("code_puppy.plugins.sidebar.register_callbacks.emit_info"),
        ):
            result = _handle_sidebar("/sidebar", "sidebar")
        assert result is True
        assert not STATE.enabled

    def test_toggle_on(self):
        from code_puppy.plugins.sidebar.register_callbacks import _handle_sidebar

        STATE.enabled = False
        with (
            patch("code_puppy.plugins.sidebar.register_callbacks.start_renderer"),
            patch("code_puppy.plugins.sidebar.register_callbacks.render_once"),
            patch("code_puppy.plugins.sidebar.register_callbacks.console_patch"),
            patch("code_puppy.plugins.sidebar.register_callbacks.emit_info"),
        ):
            result = _handle_sidebar("/sidebar", "sidebar")
        assert result is True
        assert STATE.enabled

    def test_explicit_on(self):
        from code_puppy.plugins.sidebar.register_callbacks import _handle_sidebar

        STATE.enabled = False
        with (
            patch("code_puppy.plugins.sidebar.register_callbacks.start_renderer"),
            patch("code_puppy.plugins.sidebar.register_callbacks.render_once"),
            patch("code_puppy.plugins.sidebar.register_callbacks.console_patch"),
            patch("code_puppy.plugins.sidebar.register_callbacks.emit_info"),
        ):
            result = _handle_sidebar("/sidebar on", "sidebar")
        assert result is True
        assert STATE.enabled

    def test_explicit_off(self):
        from code_puppy.plugins.sidebar.register_callbacks import _handle_sidebar

        with (
            patch("code_puppy.plugins.sidebar.register_callbacks.stop_renderer"),
            patch("code_puppy.plugins.sidebar.register_callbacks.console_patch"),
            patch("code_puppy.plugins.sidebar.register_callbacks.emit_info"),
        ):
            result = _handle_sidebar("/sidebar off", "sidebar")
        assert result is True
        assert not STATE.enabled

    def test_wide(self):
        from code_puppy.plugins.sidebar.register_callbacks import _handle_sidebar

        with (
            patch("code_puppy.plugins.sidebar.register_callbacks.render_once"),
            patch("code_puppy.plugins.sidebar.register_callbacks.console_patch"),
            patch("code_puppy.plugins.sidebar.register_callbacks.emit_info"),
        ):
            result = _handle_sidebar("/sidebar wide", "sidebar")
        assert result is True
        assert STATE.width == 30

    def test_narrow(self):
        from code_puppy.plugins.sidebar.register_callbacks import _handle_sidebar

        with (
            patch("code_puppy.plugins.sidebar.register_callbacks.render_once"),
            patch("code_puppy.plugins.sidebar.register_callbacks.console_patch"),
            patch("code_puppy.plugins.sidebar.register_callbacks.emit_info"),
        ):
            result = _handle_sidebar("/sidebar narrow", "sidebar")
        assert result is True
        assert STATE.width == 22

    def test_unknown_subcommand(self):
        from code_puppy.plugins.sidebar.register_callbacks import _handle_sidebar

        with patch("code_puppy.plugins.sidebar.register_callbacks.emit_info"):
            result = _handle_sidebar("/sidebar bogus", "sidebar")
        assert result is True

    def test_help_entry(self):
        from code_puppy.plugins.sidebar.register_callbacks import _custom_help

        entries = dict(_custom_help())
        assert "sidebar" in entries
