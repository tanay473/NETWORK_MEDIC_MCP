"""
modules/remediate/mac.py
macOS-specific remediation helpers.
Called by executor.py via actions_map.py — do not call directly.
All subprocess calls go through utils/command_runner.py.
"""

from utils.command_runner import run_command, CommandResult
from utils.logger import get_logger

log = get_logger(__name__)


def flush_dns() -> CommandResult:
    """Flush DNS cache on macOS."""
    result = run_command(["dscacheutil", "-flushcache"])
    # Also restart mDNSResponder for full effect
    run_command(["killall", "-HUP", "mDNSResponder"])
    return result


def disable_interface(interface: str = "en0") -> CommandResult:
    return run_command(["ifconfig", interface, "down"])


def enable_interface(interface: str = "en0") -> CommandResult:
    return run_command(["ifconfig", interface, "up"])


def renew_dhcp(interface: str = "en0") -> CommandResult:
    return run_command(["ipconfig", "set", interface, "DHCP"])


def set_dns_server(interface: str = "Wi-Fi", dns_server: str = "8.8.8.8") -> CommandResult:
    return run_command(["networksetup", "-setdnsservers", interface, dns_server])


def show_firewall_status() -> CommandResult:
    return run_command([
        "/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"
    ])


def restart_mdns() -> CommandResult:
    return run_command(["launchctl", "kickstart", "-k", "system/com.apple.mDNSResponder"])
