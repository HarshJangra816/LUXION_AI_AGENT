"""System statistics (PRD §39 hardware, §20: LOW)."""

from __future__ import annotations

import platform
from datetime import UTC, datetime

import psutil

from luxion.tools.base import Tool, ToolContext, ToolResult, ToolSpec

GB = 1024**3


class SystemStats(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="system_stats",
            description=(
                "Get this machine's CPU, memory, disk and network snapshot: "
                "load, RAM, free disk space, uptime and battery."
            ),
            risk="low",
            category="system",
            tags=[
                "system",
                "cpu",
                "memory",
                "ram",
                "disk",
                "storage",
                "battery",
                "uptime",
                "performance",
                "load",
                "stats",
            ],
            read_only=True,
            parameters={"type": "object", "properties": {}, "required": []},
        )

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        cpu = psutil.cpu_percent(interval=0.1)
        cores = psutil.cpu_count(logical=True)
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()

        partitions = []
        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (OSError, PermissionError):
                continue
            partitions.append(
                {
                    "mount": partition.mountpoint,
                    "total_gb": round(usage.total / GB, 1),
                    "free_gb": round(usage.free / GB, 1),
                    "used_pct": usage.percent,
                }
            )

        net = psutil.net_io_counters()
        boot = datetime.fromtimestamp(psutil.boot_time(), tz=UTC)
        uptime_s = int(datetime.now(UTC).timestamp() - psutil.boot_time())

        battery: dict | None = None
        if psutil.sensors_battery():
            info = psutil.sensors_battery()
            if info is not None:
                battery = {"percent": info.percent, "plugged": info.power_plugged}

        data = {
            "cpu_percent": cpu,
            "cpu_cores": cores,
            "ram_total_gb": round(memory.total / GB, 1),
            "ram_used_percent": memory.percent,
            "ram_available_gb": round(memory.available / GB, 1),
            "swap_used_percent": swap.percent,
            "disks": partitions,
            "net_sent_mb": round(net.bytes_sent / 1024**2, 1),
            "net_recv_mb": round(net.bytes_recv / 1024**2, 1),
            "uptime_s": uptime_s,
            "booted_at": boot.isoformat(timespec="seconds"),
            "platform": platform.platform(),
            "battery": battery,
        }
        lines = [
            f"CPU {cpu}% across {cores} cores",
            f"RAM {data['ram_used_percent']}% used of {data['ram_total_gb']} GB "
            f"({data['ram_available_gb']} GB free)",
        ]
        for disk in partitions:
            lines.append(
                f"Disk {disk['mount']} {disk['used_pct']}% used "
                f"({disk['free_gb']} GB free of {disk['total_gb']} GB)"
            )
        lines.append(f"Network sent {data['net_sent_mb']} MB / received {data['net_recv_mb']} MB")
        lines.append(f"Uptime {uptime_s // 3600}h {(uptime_s % 3600) // 60}m")
        if battery:
            state = "charging" if battery["plugged"] else "discharging"
            lines.append(f"Battery {battery['percent']}% ({state})")
        return ToolResult(output="\n".join(lines), data=data)


BUILTIN_TOOLS: list[Tool] = [SystemStats()]
