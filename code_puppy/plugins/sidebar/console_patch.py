"""Constrain Rich Console width so output doesn't collide with the sidebar.

Monkey-patches ``Console.__init__`` to cap ``width`` at
``terminal_width - sidebar_width`` when no explicit width is provided.
Also patches live Console instances found via gc.

Reversible via ``uninstall()``.
"""

from __future__ import annotations

import gc
import shutil

from rich.console import Console

from .state import STATE

_original_init = Console.__init__
_patched = False


def _effective_width() -> int:
    """Max width that leaves room for the sidebar."""
    cols = shutil.get_terminal_size().columns
    return max(40, cols - STATE.width - 1)


def _patched_init(self, *args, **kwargs):
    if "width" not in kwargs or kwargs["width"] is None:
        kwargs["width"] = _effective_width()
    _original_init(self, *args, **kwargs)


def install() -> None:
    """Patch Console.__init__ and shrink live instances."""
    global _patched
    if _patched:
        return
    Console.__init__ = _patched_init  # type: ignore[method-assign]
    _patched = True
    _shrink_live_consoles()


def uninstall() -> None:
    """Restore original Console.__init__ and widen live instances."""
    global _patched
    if not _patched:
        return
    Console.__init__ = _original_init  # type: ignore[method-assign]
    _patched = False
    _restore_live_consoles()


def _shrink_live_consoles() -> None:
    """Walk live Console instances and cap their width."""
    w = _effective_width()
    try:
        for obj in gc.get_objects():
            if isinstance(obj, Console):
                try:
                    obj._width = w  # noqa: SLF001 — internal but stable
                except Exception:
                    pass
    except Exception:
        pass


def _restore_live_consoles() -> None:
    """Walk live Console instances and remove width cap."""
    try:
        for obj in gc.get_objects():
            if isinstance(obj, Console):
                try:
                    obj._width = None  # noqa: SLF001
                except Exception:
                    pass
    except Exception:
        pass
