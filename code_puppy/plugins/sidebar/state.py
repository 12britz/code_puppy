"""Shared mutable state for the sidebar plugin.

Thread-safe via a simple lock. All hook callbacks write here;
the renderer reads on its refresh tick.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ToolRecord:
    name: str
    started: float
    finished: float | None = None
    duration_ms: float | None = None
    success: bool = True


@dataclass
class SidebarState:
    enabled: bool = True
    width: int = 26

    # Agent
    agent_name: str = ""
    model_name: str = ""
    session_id: str | None = None
    agent_running: bool = False
    run_started: float = 0.0

    # Current tool
    current_tool: str | None = None
    current_tool_started: float = 0.0

    # Tool history (last N)
    tool_history: deque[ToolRecord] = field(default_factory=lambda: deque(maxlen=8))
    tool_count: int = 0
    tool_total_ms: float = 0.0

    # Streaming
    tokens_streamed: int = 0
    is_streaming: bool = False

    # Lock
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def on_agent_start(
        self, agent_name: str, model_name: str, session_id: str | None = None
    ):
        with self._lock:
            self.agent_name = agent_name
            self.model_name = model_name
            self.session_id = session_id
            self.agent_running = True
            self.run_started = time.monotonic()
            self.current_tool = None
            self.tool_count = 0
            self.tool_total_ms = 0.0
            self.tokens_streamed = 0
            self.is_streaming = False

    def on_agent_end(self, success: bool = True):
        with self._lock:
            self.agent_running = False
            self.current_tool = None
            self.is_streaming = False

    def on_tool_start(self, tool_name: str):
        with self._lock:
            self.current_tool = tool_name
            self.current_tool_started = time.monotonic()

    def on_tool_end(self, tool_name: str, duration_ms: float, success: bool = True):
        with self._lock:
            rec = ToolRecord(
                name=tool_name,
                started=self.current_tool_started,
                finished=time.monotonic(),
                duration_ms=duration_ms,
                success=success,
            )
            self.tool_history.append(rec)
            self.tool_count += 1
            self.tool_total_ms += duration_ms
            self.current_tool = None

    def on_stream_delta(self):
        with self._lock:
            self.tokens_streamed += 1
            self.is_streaming = True

    def on_stream_end(self):
        with self._lock:
            self.is_streaming = False

    def snapshot(self) -> dict:
        """Return a copy of all fields for the renderer (avoids holding lock)."""
        with self._lock:
            elapsed = time.monotonic() - self.run_started if self.agent_running else 0.0
            tool_elapsed = (
                time.monotonic() - self.current_tool_started
                if self.current_tool
                else 0.0
            )
            return {
                "enabled": self.enabled,
                "width": self.width,
                "agent_name": self.agent_name,
                "model_name": self.model_name,
                "agent_running": self.agent_running,
                "elapsed": elapsed,
                "current_tool": self.current_tool,
                "tool_elapsed": tool_elapsed,
                "tool_history": list(self.tool_history),
                "tool_count": self.tool_count,
                "tool_total_ms": self.tool_total_ms,
                "tokens_streamed": self.tokens_streamed,
                "is_streaming": self.is_streaming,
            }


STATE = SidebarState()
