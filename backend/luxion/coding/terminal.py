"""Sandboxed command runner (PRD §34 "Running commands", §36, Phase 8).

The engine behind ``run_command`` / ``run_tests`` / ``install_dependencies``.
Three layers keep it honest:

1. **Workspace cwd** — the command always runs inside an approved workspace
   (the tool resolves the path before calling in here).
2. **Capability + risk** — the tools declare ``requires="terminal"`` and
   ``risk="high"``, so the executor gates them before anything executes
   (PRD §39) and the autonomy matrix asks the user at the default level.
3. **This module** — a backstop for irreversible damage (``_BLOCKED``),
   a scrubbed environment so child processes cannot read API keys
   (PRD §57 rule 6), an output clip so a runaway ``echo`` cannot flood the
   context, and a process-*tree* kill on timeout (a plain ``kill`` leaves
   ``npm``'s children alive on Windows).
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Default wall-clock limit when the caller does not pick one.
DEFAULT_TIMEOUT_S = 120.0
MAX_TIMEOUT_S = 900.0
#: Characters of combined stdout+stderr handed back to the model.
DEFAULT_MAX_OUTPUT = 20_000
MAX_MAX_OUTPUT = 200_000

#: Environment variables matching this pattern never reach a child process.
#: Deliberately narrow: ``auth`` alone would scrub ``GIT_AUTHOR_*`` and break
#: every git commit whose identity comes from the environment.
_SECRET_PATTERN = re.compile(
    r"(?i)(token|secret|password|passwd|credential|api_?key|access_?key|"
    r"private_?key|(^|_)key$|(^|_)auth$|authorization)"
)

#: Catastrophic / irreversible commands no confirmation should ever allow.
#: This is a *backstop*, not the permission model — the risk engine already
#: asks the user for every high-risk tool. Case-insensitive substring match.
_BLOCKED: tuple[str, ...] = (
    "rm -rf /",
    "rm -rf ~",
    "rm -fr /",
    "rm -fr ~",
    ":(){:|:&};:",  # fork bomb
    "mkfs",
    "diskpart",
    "format c:",
    "format /",
    "del /s /q c:",
    "rd /s /q c:",
    "reg delete",
    "shutdown",
    "reboot",
    "> /dev/sd",
    "dd if=",
    "bcdedit",
    "cipher /w",
    "iex (new-object",
)

#: Commands the runner refuses to *start*; checked before subprocess spawn.
_BLOCKED_COMPILED = tuple(re.compile(re.escape(item), re.IGNORECASE) for item in _BLOCKED)


class CommandBlockedError(Exception):
    """Raised when a command matches the catastrophic backstop list."""


def check_blocked(command: str) -> None:
    """Raise :class:`CommandBlockedError` for a catastrophically unsafe command."""
    for pattern in _BLOCKED_COMPILED:
        if pattern.search(command):
            raise CommandBlockedError(
                f"refusing to run a destructive command (matched '{pattern.pattern}'): "
                "this would damage the machine or the data beyond recovery"
            )


@dataclass
class CommandResult:
    """Outcome of one shell invocation."""

    command: str
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    clipped: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_s": round(self.duration_s, 2),
            "timed_out": self.timed_out,
            "clipped": self.clipped,
        }


def scrubbed_env() -> dict[str, str]:
    """The child environment: everything except secret-looking variables."""
    return {key: value for key, value in os.environ.items() if not _SECRET_PATTERN.search(key)}


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill a process *and its children* (Windows ``taskkill /T``, POSIX group)."""
    if process.poll() is not None:
        return
    if os.name == "nt":  # pragma: no cover - Windows-only path
        try:
            subprocess.run(  # noqa: S603 - fixed argv, our own helper
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            process.kill()
    else:  # pragma: no cover - POSIX-only path
        import signal

        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            process.kill()


def run_command(
    command: str,
    *,
    cwd: Path,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_output: int = DEFAULT_MAX_OUTPUT,
) -> CommandResult:
    """Run ``command`` through the platform shell inside ``cwd``.

    Raises :class:`CommandBlockedError` for the catastrophic backstop list.
    Output is clipped to ``max_output`` characters (head kept, tail dropped,
    with a marker); a timeout kills the whole process tree and is reported in
    ``timed_out`` rather than raised — a hung build is data, not an error.
    """
    command = str(command).strip()
    if not command:
        raise ValueError("empty command")
    check_blocked(command)

    timeout = max(1.0, min(float(timeout_s), MAX_TIMEOUT_S))
    limit = max(1000, min(int(max_output), MAX_MAX_OUTPUT))
    env = scrubbed_env()

    started = time.monotonic()
    process = subprocess.Popen(  # noqa: S602 - the terminal tool *is* a shell
        command,
        cwd=str(cwd),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,  # never block on an accidental prompt
        env=env,
    )
    timed_out = False
    try:
        stdout_bytes, stderr_bytes = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(process)
        try:
            stdout_bytes, stderr_bytes = process.communicate(timeout=10)
        except subprocess.SubprocessError:  # pragma: no cover - kill already ran
            stdout_bytes, stderr_bytes = b"", b""
    duration = time.monotonic() - started

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    clipped = False
    if len(stdout) + len(stderr) > limit:
        clipped = True
        stdout = stdout[:limit] + "\n…[output clipped]"
        stderr = stderr[: max(1000, limit // 10)]

    return CommandResult(
        command=command,
        cwd=str(cwd),
        exit_code=None if timed_out else process.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_s=duration,
        timed_out=timed_out,
        clipped=clipped,
    )
