"""
utils/command_runner.py
Single choke-point for all subprocess calls in network_medic.
linux.py / windows.py / mac.py must call run_command() — never subprocess directly.
"""

import subprocess
from dataclasses import dataclass

from utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 30  # seconds


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def run_command(
    command: str | list[str],
    timeout: int = DEFAULT_TIMEOUT,
    shell: bool = False,
) -> CommandResult:
    """
    Execute a system command safely.

    Args:
        command : string (shell=True) or list of args (shell=False, preferred)
        timeout : seconds before forceful kill (default 30)
        shell   : use shell=True only when unavoidable (e.g. piped commands)

    Returns:
        CommandResult with stdout, stderr, returncode, timed_out flag
    """
    cmd_str = command if isinstance(command, str) else " ".join(command)
    log.debug(f"Running command: {cmd_str}")

    try:
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            shell=shell,
        )
        result = CommandResult(
            command=cmd_str,
            returncode=proc.returncode,
            stdout=proc.stdout.strip(),
            stderr=proc.stderr.strip(),
        )

    except subprocess.TimeoutExpired:
        log.warning(f"Command timed out after {timeout}s: {cmd_str}")
        result = CommandResult(
            command=cmd_str,
            returncode=-1,
            stdout="",
            stderr=f"Timed out after {timeout}s",
            timed_out=True,
        )

    except Exception as exc:
        log.error(f"Command failed with exception: {exc} | cmd: {cmd_str}")
        result = CommandResult(
            command=cmd_str,
            returncode=-1,
            stdout="",
            stderr=str(exc),
        )

    log.debug(
        f"Command result: rc={result.returncode} | "
        f"stdout={result.stdout[:120]} | stderr={result.stderr[:120]}"
    )
    return result
