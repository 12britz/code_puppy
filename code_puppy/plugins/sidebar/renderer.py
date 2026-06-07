"""ANSI-escape sidebar renderer.

Draws a fixed-width panel in the rightmost columns of the terminal using
absolute cursor positioning. A background thread redraws at ~5 Hz while
the agent is running, and once on idle transitions.

Terminal escape sequences used:
    ESC 7           save cursor
    ESC 8           restore cursor
    ESC[{r};{c}H    move to row, col
    ESC[K            clear to end of line (NOT used — we overwrite precisely)

Works in iTerm2, Terminal.app, Alacritty, kitty, VS Code, GNOME Terminal,
Windows Terminal. Unsupported terminals silently ignore the sequences.
"""

from __future__ import annotations

import shutil
import sys
import threading

from .state import STATE

ESC = "\033"
_refresh_thread: threading.Thread | None = None
_stop_event = threading.Event()

# Box-drawing characters
BOX_V = "│"
BOX_H = "─"
BOX_TL = "┌"
BOX_TR = "┐"
BOX_BL = "└"
BOX_BR = "┘"

# ANSI color helpers
DIM = f"{ESC}[2m"
BOLD = f"{ESC}[1m"
RESET = f"{ESC}[0m"
CYAN = f"{ESC}[36m"
GREEN = f"{ESC}[32m"
YELLOW = f"{ESC}[33m"
RED = f"{ESC}[31m"
MAGENTA = f"{ESC}[35m"
WHITE = f"{ESC}[37m"
DIM_WHITE = f"{ESC}[2;37m"


def _term_size() -> tuple[int, int]:
    """Return (columns, rows) of the terminal."""
    try:
        cols, rows = shutil.get_terminal_size()
        return cols, rows
    except Exception:
        return 80, 24


def _move(row: int, col: int) -> str:
    return f"{ESC}[{row};{col}H"


def _save_cursor() -> str:
    return f"{ESC}7"


def _restore_cursor() -> str:
    return f"{ESC}8"


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds) // 60
    secs = seconds - (minutes * 60)
    return f"{minutes}m{secs:.0f}s"


def _format_ms(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def _build_lines(snap: dict, inner_w: int) -> list[str]:
    """Build the sidebar content lines (plain text, will be padded by caller)."""
    lines: list[str] = []

    # Header
    lines.append(f"{BOLD}{CYAN} ◧ SIDEBAR{RESET}")
    lines.append(f"{DIM_WHITE}{'─' * inner_w}{RESET}")

    if not snap["agent_running"] and not snap["agent_name"]:
        lines.append(f"{DIM_WHITE} idle{RESET}")
        return lines

    # Agent + Model
    agent = _truncate(snap["agent_name"] or "?", inner_w - 2)
    model = _truncate(snap["model_name"] or "?", inner_w - 2)
    lines.append(f"{BOLD}{WHITE} 🤖 {agent}{RESET}")
    lines.append(f"{DIM_WHITE} ⚙  {model}{RESET}")
    lines.append(f"{DIM_WHITE}{'─' * inner_w}{RESET}")

    if snap["agent_running"]:
        # Elapsed time
        elapsed_str = _format_duration(snap["elapsed"])
        lines.append(f"{GREEN} ⏱  {elapsed_str}{RESET}")

        # Current tool
        if snap["current_tool"]:
            tool = _truncate(snap["current_tool"], inner_w - 5)
            tool_elapsed = _format_duration(snap["tool_elapsed"])
            lines.append(f"{YELLOW} 🔧 {tool}{RESET}")
            lines.append(f"{DIM_WHITE}    {tool_elapsed}{RESET}")
        elif snap["is_streaming"]:
            lines.append(f"{CYAN} ✦  streaming…{RESET}")
        else:
            lines.append(f"{DIM_WHITE} …  waiting{RESET}")

        # Token count
        if snap["tokens_streamed"] > 0:
            lines.append(f"{DIM_WHITE} 📝 ~{snap['tokens_streamed']} chunks{RESET}")
    else:
        lines.append(f"{DIM_WHITE} ✓  done{RESET}")

    # Tool stats
    if snap["tool_count"] > 0:
        lines.append(f"{DIM_WHITE}{'─' * inner_w}{RESET}")
        lines.append(f"{MAGENTA} 🔨 {snap['tool_count']} tools{RESET}")
        avg = snap["tool_total_ms"] / snap["tool_count"]
        lines.append(f"{DIM_WHITE}    avg {_format_ms(avg)}{RESET}")

    # Recent tool history
    history = snap["tool_history"]
    if history:
        lines.append(f"{DIM_WHITE}{'─' * inner_w}{RESET}")
        lines.append(f"{DIM_WHITE} recent:{RESET}")
        for rec in reversed(history[-4:]):
            icon = f"{GREEN}✓{RESET}" if rec.success else f"{RED}✗{RESET}"
            name = _truncate(rec.name, inner_w - 7)
            dur = _format_ms(rec.duration_ms or 0)
            lines.append(f" {icon} {DIM_WHITE}{name}{RESET}")
            lines.append(f"   {DIM_WHITE}{dur}{RESET}")

    return lines


def render_once() -> None:
    """Draw the sidebar at the right edge of the terminal."""
    snap = STATE.snapshot()
    if not snap["enabled"]:
        return

    cols, rows = _term_size()
    sw = snap["width"]
    if cols < sw + 40:
        return  # terminal too narrow

    inner_w = sw - 2  # inside the box borders
    start_col = cols - sw + 1
    content_lines = _build_lines(snap, inner_w)

    # Build the framed sidebar
    framed: list[str] = []
    framed.append(f"{DIM}{BOX_TL}{BOX_H * inner_w}{BOX_TR}{RESET}")
    for line in content_lines:
        framed.append(f"{DIM}{BOX_V}{RESET}{line:<{inner_w}}{DIM}{BOX_V}{RESET}")
    # Fill remaining rows to avoid stale content
    sidebar_height = min(len(framed) + 1, rows - 2)
    while len(framed) < sidebar_height:
        framed.append(f"{DIM}{BOX_V}{' ' * inner_w}{BOX_V}{RESET}")
    framed.append(f"{DIM}{BOX_BL}{BOX_H * inner_w}{BOX_BR}{RESET}")

    # Draw using cursor positioning
    buf = [_save_cursor()]
    for i, line in enumerate(framed[: rows - 1]):
        buf.append(_move(i + 1, start_col))
        buf.append(line)
    buf.append(_restore_cursor())

    try:
        sys.stdout.write("".join(buf))
        sys.stdout.flush()
    except Exception:
        pass


def clear_sidebar() -> None:
    """Erase the sidebar area (fill with spaces)."""
    snap = STATE.snapshot()
    cols, rows = _term_size()
    sw = snap["width"]
    if cols < sw + 40:
        return
    start_col = cols - sw + 1

    buf = [_save_cursor()]
    for row in range(1, rows):
        buf.append(_move(row, start_col))
        buf.append(" " * sw)
    buf.append(_restore_cursor())

    try:
        sys.stdout.write("".join(buf))
        sys.stdout.flush()
    except Exception:
        pass


def _refresh_loop() -> None:
    """Background thread: redraw sidebar at ~5 Hz while agent runs."""
    while not _stop_event.is_set():
        try:
            snap = STATE.snapshot()
            if snap["enabled"] and snap["agent_running"]:
                render_once()
            _stop_event.wait(0.2)
        except Exception:
            _stop_event.wait(1.0)


def start_renderer() -> None:
    """Start the background refresh thread."""
    global _refresh_thread
    if _refresh_thread is not None and _refresh_thread.is_alive():
        return
    _stop_event.clear()
    _refresh_thread = threading.Thread(
        target=_refresh_loop, daemon=True, name="sidebar-render"
    )
    _refresh_thread.start()


def stop_renderer() -> None:
    """Stop the background refresh thread and clear the sidebar."""
    _stop_event.set()
    if _refresh_thread is not None:
        _refresh_thread.join(timeout=1.0)
    clear_sidebar()
