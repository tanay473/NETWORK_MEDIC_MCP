"""
modules/remediate/linux.py
Linux-specific remediation helpers.
Called by executor.py via actions_map.py — do not call directly.
All subprocess calls go through utils/command_runner.py.
"""

from utils.command_runner import run_command, CommandResult
from utils.logger import get_logger

log = get_logger(__name__)


def flush_dns() -> CommandResult:
    """Flush DNS cache via resolvectl (systemd-resolved)."""
    return run_command(["resolvectl", "flush-caches"])


def restart_network_manager() -> CommandResult:
    return run_command(["systemctl", "restart", "NetworkManager"])


def release_dhcp(interface: str = "eth0") -> CommandResult:
    return run_command(["dhclient", "-r", interface])


def renew_dhcp(interface: str = "eth0") -> CommandResult:
    return run_command(["dhclient", interface])


def disable_interface(interface: str = "eth0") -> CommandResult:
    return run_command(["ip", "link", "set", interface, "down"])


def enable_interface(interface: str = "eth0") -> CommandResult:
    return run_command(["ip", "link", "set", interface, "up"])


def set_dns_server(interface: str = "eth0", dns_server: str = "8.8.8.8") -> CommandResult:
    return run_command(["resolvectl", "dns", interface, dns_server])


def show_firewall_status() -> CommandResult:
    return run_command(["iptables", "-L", "-n"])


def restart_service(service: str = "networking") -> CommandResult:
    return run_command(["systemctl", "restart", service])
