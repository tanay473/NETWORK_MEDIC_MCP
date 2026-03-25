"""
modules/remediate/windows.py
Windows-specific remediation helpers.
Called by executor.py via actions_map.py — do not call directly.
All subprocess calls go through utils/command_runner.py.
"""

from utils.command_runner import run_command, CommandResult
from utils.logger import get_logger

log = get_logger(__name__)


def flush_dns() -> CommandResult:
    return run_command(["ipconfig", "/flushdns"])


def release_dhcp() -> CommandResult:
    return run_command(["ipconfig", "/release"])


def renew_dhcp() -> CommandResult:
    return run_command(["ipconfig", "/renew"])


def reset_winsock() -> CommandResult:
    log.warning("Executing winsock reset — system restart may be required.")
    return run_command(["netsh", "winsock", "reset"])


def reset_tcp_ip() -> CommandResult:
    log.warning("Executing TCP/IP stack reset — system restart may be required.")
    return run_command(["netsh", "int", "ip", "reset"])


def disable_interface(interface: str = "Ethernet") -> CommandResult:
    return run_command(["netsh", "interface", "set", "interface", interface, "disable"])


def enable_interface(interface: str = "Ethernet") -> CommandResult:
    return run_command(["netsh", "interface", "set", "interface", interface, "enable"])


def set_dns_server(interface: str = "Ethernet", dns_server: str = "8.8.8.8") -> CommandResult:
    return run_command(
        ["netsh", "interface", "ip", "set", "dns", interface, "static", dns_server]
    )


def show_firewall_status() -> CommandResult:
    return run_command(["netsh", "advfirewall", "show", "allprofiles"])


def restart_dns_service() -> CommandResult:
    """Restarts the Windows DNS Client service."""
    stop = run_command(["net", "stop", "dnscache"], shell=False)
    if not stop.success:
        log.warning(f"Failed to stop dnscache: {stop.stderr}")
    return run_command(["net", "start", "dnscache"])
