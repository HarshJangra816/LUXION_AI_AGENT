"""Desktop notifications (Phase 10).

Stdlib-only PowerShell toast (see :mod:`luxion.notify.toast` for the how and
why). The ``notify`` tool and ``POST /api/notify/test`` both route through
:func:`send_toast`, so cooldown and capability rules apply to every caller.
"""

from __future__ import annotations

from luxion.notify.toast import (
    ToastError,
    build_script,
    encode_script,
    reset_cooldown,
    send_toast,
)

__all__ = [
    "ToastError",
    "build_script",
    "encode_script",
    "reset_cooldown",
    "send_toast",
]
