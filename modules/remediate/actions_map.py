"""
modules/remediate/actions_map.py
Maps logical action_type strings to OS-specific command builders.
executor.py calls get_command(action_type, os, params) to get the actual command list.
"""

from utils.os_detector import OS
from utils.logger import get_logger

log = get_logger(__name__)

# Type alias for command: list of args passed to subprocess
Command = list[str]


def get_command(action_type: str, os: OS, params: dict | None = None) -> Command:
    """
    Returns the system command list for a given logical action on a given OS.

    Args:
        action_type : logical action string from plan_schema.json enum
        os          : OS enum value from os_detector
        params      : optional action parameters from the plan

    Returns:
        List of command args (passed directly to command_runner.run_command)

    Raises:
        ValueError: if action_type is unsupported on the given OS
    """
    params = params or {}
    key = (action_type, os)

    builders = {
        # ── flush_dns ─────────────────────────────────────────────────────────
        ("flush_dns", OS.WINDOWS): lambda p: ["ipconfig", "/flushdns"],
        ("flush_dns", OS.LINUX):   lambda p: ["resolvectl", "flush-caches"],
        ("flush_dns", OS.MAC):     lambda p: ["dscacheutil", "-flushcache"],

        # ── restart_network_interface ─────────────────────────────────────────
        ("restart_network_interface", OS.WINDOWS): lambda p: [
            "netsh", "interface", "set", "interface",
            p.get("interface", "Ethernet"), "disable"
        ],
        ("restart_network_interface", OS.LINUX): lambda p: [
            "systemctl", "restart", "NetworkManager"
        ],
        ("restart_network_interface", OS.MAC): lambda p: [
            "ifconfig", p.get("interface", "en0"), "down"
        ],

        # ── release_renew_dhcp ────────────────────────────────────────────────
        ("release_renew_dhcp", OS.WINDOWS): lambda p: ["ipconfig", "/release"],
        ("release_renew_dhcp", OS.LINUX):   lambda p: ["dhclient", "-r"],
        ("release_renew_dhcp", OS.MAC):     lambda p: ["ipconfig", "set", p.get("interface", "en0"), "DHCP"],

        # ── change_dns_server ─────────────────────────────────────────────────
        ("change_dns_server", OS.WINDOWS): lambda p: [
            "netsh", "interface", "ip", "set", "dns",
            p.get("interface", "Ethernet"), "static",
            p.get("dns_server", "8.8.8.8")
        ],
        ("change_dns_server", OS.LINUX): lambda p: [
            "resolvectl", "dns",
            p.get("interface", "eth0"),
            p.get("dns_server", "8.8.8.8")
        ],
        ("change_dns_server", OS.MAC): lambda p: [
            "networksetup", "-setdnsservers",
            p.get("interface", "Wi-Fi"),
            p.get("dns_server", "8.8.8.8")
        ],

        # ── reset_winsock (Windows only) ──────────────────────────────────────
        ("reset_winsock", OS.WINDOWS): lambda p: ["netsh", "winsock", "reset"],

        # ── reset_tcp_ip (Windows only) ───────────────────────────────────────
        ("reset_tcp_ip", OS.WINDOWS): lambda p: ["netsh", "int", "ip", "reset"],

        # ── disable_interface ─────────────────────────────────────────────────
        ("disable_interface", OS.WINDOWS): lambda p: [
            "netsh", "interface", "set", "interface",
            p.get("interface", "Ethernet"), "disable"
        ],
        ("disable_interface", OS.LINUX): lambda p: [
            "ip", "link", "set", p.get("interface", "eth0"), "down"
        ],
        ("disable_interface", OS.MAC): lambda p: [
            "ifconfig", p.get("interface", "en0"), "down"
        ],

        # ── enable_interface ──────────────────────────────────────────────────
        ("enable_interface", OS.WINDOWS): lambda p: [
            "netsh", "interface", "set", "interface",
            p.get("interface", "Ethernet"), "enable"
        ],
        ("enable_interface", OS.LINUX): lambda p: [
            "ip", "link", "set", p.get("interface", "eth0"), "up"
        ],
        ("enable_interface", OS.MAC): lambda p: [
            "ifconfig", p.get("interface", "en0"), "up"
        ],

        # ── ping_test ─────────────────────────────────────────────────────────
        ("ping_test", OS.WINDOWS): lambda p: ["ping", "-n", "4", p.get("target", "8.8.8.8")],
        ("ping_test", OS.LINUX):   lambda p: ["ping", "-c", "4", p.get("target", "8.8.8.8")],
        ("ping_test", OS.MAC):     lambda p: ["ping", "-c", "4", p.get("target", "8.8.8.8")],

        # ── traceroute ────────────────────────────────────────────────────────
        ("traceroute", OS.WINDOWS): lambda p: ["tracert", p.get("target", "8.8.8.8")],
        ("traceroute", OS.LINUX):   lambda p: ["traceroute", p.get("target", "8.8.8.8")],
        ("traceroute", OS.MAC):     lambda p: ["traceroute", p.get("target", "8.8.8.8")],

        # ── check_firewall ────────────────────────────────────────────────────
        ("check_firewall", OS.WINDOWS): lambda p: ["netsh", "advfirewall", "show", "allprofiles"],
        ("check_firewall", OS.LINUX):   lambda p: ["iptables", "-L", "-n"],
        ("check_firewall", OS.MAC):     lambda p: ["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"],

        # ── restart_service ───────────────────────────────────────────────────
        ("restart_service", OS.WINDOWS): lambda p: ["net", "stop", p.get("service", "dnscache"), "&&", "net", "start", p.get("service", "dnscache")],
        ("restart_service", OS.LINUX):   lambda p: ["systemctl", "restart", p.get("service", "networking")],
        ("restart_service", OS.MAC):     lambda p: ["launchctl", "kickstart", "-k", p.get("service", "system/com.apple.mDNSResponder")],
    }

    builder = builders.get(key)
    if builder is None:
        raise ValueError(
            f"No command mapping for action_type='{action_type}' on os='{os.value}'. "
            f"This action may not be supported on this platform."
        )

    command = builder(params)
    log.debug(f"actions_map: {action_type} on {os.value} → {' '.join(command)}")
    return command
