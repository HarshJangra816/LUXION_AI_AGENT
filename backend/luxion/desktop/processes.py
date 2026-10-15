"""Process management (PRD §33.5 "Process management", §5.11, Phase 7).

``system_stats`` answers "how loaded is this machine?"; this answers "what is
actually running, and what is eating the CPU?". psutil works on every
platform, so the module does not gate on Windows — the tools that *drive*
windows do.
"""

from __future__ import annotations

import time

from luxion.desktop.errors import DesktopError

#: Seconds between priming ``cpu_percent`` and reading it (psutil needs one
#: sample window to compute a non-zero value).
CPU_SAMPLE_S = 0.15

SORTS = ("cpu", "memory", "name")


def top_processes(
    *,
    sort: str = "cpu",
    limit: int = 25,
    query: str = "",
) -> dict[str, object]:
    """The most interesting running processes, sampled over ``CPU_SAMPLE_S``."""
    if sort not in SORTS:
        raise DesktopError(f"unknown sort '{sort}' (use {', '.join(SORTS)})", code="invalid_sort")
    try:
        import psutil
    except Exception as exc:  # noqa: BLE001 - dependency missing
        raise DesktopError(f"psutil is unavailable: {exc}", code="psutil_unavailable") from exc

    wanted = query.strip().lower()
    rows: list[dict[str, object]] = []

    primed: list[object] = []
    for process in psutil.process_iter(["pid", "name", "status", "memory_info"]):
        try:
            process.cpu_percent(None)  # first sample — always ~0
            primed.append(process)
        except Exception:  # noqa: BLE001 - exited / access denied between calls
            continue
    total = len(primed)
    time.sleep(CPU_SAMPLE_S)

    for process in primed:
        try:
            info = dict(process.info)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            continue
        name = str(info.get("name") or "")
        if not name:
            # Exited between the priming pass and this read — an unnamed row
            # is useless to the agent, so drop it rather than rank "" first.
            continue
        if wanted and wanted not in name.lower():
            continue
        memory = info.get("memory_info")
        try:
            cpu = round(float(process.cpu_percent(None)), 1)
        except Exception:  # noqa: BLE001
            cpu = 0.0
        rows.append(
            {
                "pid": int(info.get("pid") or 0),
                "name": name,
                "status": str(info.get("status") or ""),
                "cpu_percent": cpu,
                "rss_mb": round(memory.rss / 1048576, 1) if memory else 0.0,  # type: ignore[union-attr]
            }
        )

    if sort == "cpu":
        rows.sort(key=lambda row: float(row["cpu_percent"]), reverse=True)
    elif sort == "memory":
        rows.sort(key=lambda row: float(row["rss_mb"]), reverse=True)
    else:
        rows.sort(key=lambda row: str(row["name"]).lower())

    return {
        "processes": rows[: max(1, limit)],
        "matched": len(rows),
        "running": total,
        "sort": sort,
    }
