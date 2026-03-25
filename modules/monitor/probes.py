"""
modules/monitor/probes.py
Network probe functions: connectivity, DNS, latency, and device state.
Each probe returns a standardised dict conforming to state_schema.json probe fields.
collector.py calls all probes and assembles the final SystemState.
"""

import socket
import subprocess
import platform
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)

# Hosts used for probing — chosen for reliability
_CONNECTIVITY_HOSTS = ["8.8.8.8", "1.1.1.1", "208.67.222.222"]
_DNS_DOMAINS        = ["google.com", "cloudflare.com", "github.com"]
_LATENCY_TARGET     = "8.8.8.8"
_PING_COUNT         = 4
_CRITICAL_PORTS     = [53, 80, 443]
_PORT_TEST_HOST     = "8.8.8.8"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ping(host: str, count: int = 2) -> tuple[bool, float | None, float | None]:
    """
    Ping a host. Returns (reachable, avg_ms, packet_loss_pct).
    Cross-platform: uses -n on Windows, -c on Linux/Mac.
    """
    system = platform.system().lower()
    count_flag = "-n" if system == "windows" else "-c"

    try:
        result = subprocess.run(
            ["ping", count_flag, str(count), host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        reachable = result.returncode == 0
        avg_ms = None
        loss_pct = None
        output = result.stdout

        if system == "windows":
            for line in output.splitlines():
                if "Average" in line:
                    parts = line.split("=")
                    if parts:
                        try:
                            avg_ms = float(parts[-1].replace("ms", "").strip())
                        except ValueError:
                            pass
                if "Lost" in line:
                    try:
                        loss_pct = float(line.split("(")[1].split("%")[0].strip())
                    except (IndexError, ValueError):
                        pass
        else:
            for line in output.splitlines():
                if "avg" in line or "rtt" in line:
                    try:
                        avg_ms = float(line.split("/")[4])
                    except (IndexError, ValueError):
                        pass
                if "packet loss" in line:
                    try:
                        loss_pct = float(line.split("%")[0].split()[-1])
                    except (IndexError, ValueError):
                        pass

        return reachable, avg_ms, loss_pct

    except subprocess.TimeoutExpired:
        log.warning(f"Ping timed out for host: {host}")
        return False, None, 100.0
    except Exception as exc:
        log.error(f"Ping failed for {host}: {exc}")
        return False, None, 100.0


def _run(cmd: list[str], timeout: int = 5) -> str:
    """Helper to run a command and return stdout as string. Returns '' on failure."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


# ── Original Probes ───────────────────────────────────────────────────────────

def check_connectivity() -> dict[str, Any]:
    """
    Checks reachability of known reliable hosts via ping.
    Returns connectivity probe dict per state_schema.json.
    """
    log.debug("Running connectivity probe...")
    reachable, unreachable = [], []

    for host in _CONNECTIVITY_HOSTS:
        ok, _, _ = _ping(host, count=2)
        (reachable if ok else unreachable).append(host)

    total = len(_CONNECTIVITY_HOSTS)
    reachable_count = len(reachable)

    if reachable_count == total:
        status = "healthy"
    elif reachable_count > 0:
        status = "degraded"
    else:
        status = "failed"

    log.info(f"Connectivity: {status} | reachable={reachable} unreachable={unreachable}")
    return {
        "status": status,
        "reachable_hosts": reachable,
        "unreachable_hosts": unreachable,
        "details": f"{reachable_count}/{total} hosts reachable",
    }


def check_dns() -> dict[str, Any]:
    """
    Attempts DNS resolution for known domains using socket.getaddrinfo.
    Returns dns probe dict per state_schema.json.
    """
    log.debug("Running DNS probe...")
    resolved, failed = [], []

    for domain in _DNS_DOMAINS:
        try:
            socket.getaddrinfo(domain, None)
            resolved.append(domain)
        except socket.gaierror as exc:
            log.warning(f"DNS resolution failed for {domain}: {exc}")
            failed.append(domain)

    dns_servers = _get_dns_servers()
    total = len(_DNS_DOMAINS)
    resolved_count = len(resolved)

    if resolved_count == total:
        status = "healthy"
    elif resolved_count > 0:
        status = "degraded"
    else:
        status = "failed"

    log.info(f"DNS: {status} | resolved={resolved} failed={failed}")
    return {
        "status": status,
        "resolved": resolved,
        "failed": failed,
        "current_dns_servers": dns_servers,
        "details": f"{resolved_count}/{total} domains resolved",
    }


def check_latency() -> dict[str, Any]:
    """
    Measures round-trip latency and packet loss to a reliable target.
    Returns latency probe dict per state_schema.json.
    """
    log.debug("Running latency probe...")
    reachable, avg_ms, loss_pct = _ping(_LATENCY_TARGET, count=_PING_COUNT)

    if not reachable:
        status = "failed"
    elif loss_pct is not None and loss_pct > 20:
        status = "degraded"
    elif avg_ms is not None and avg_ms > 200:
        status = "degraded"
    else:
        status = "healthy"

    log.info(f"Latency: {status} | avg_ms={avg_ms} loss_pct={loss_pct}")
    return {
        "status": status,
        "avg_ms": avg_ms,
        "packet_loss_pct": loss_pct,
        "target_host": _LATENCY_TARGET,
        "details": f"avg={avg_ms}ms loss={loss_pct}% to {_LATENCY_TARGET}",
    }


# ── Device State Probes ───────────────────────────────────────────────────────

def check_gateway() -> dict[str, Any]:
    """
    Detects the default gateway and checks if it is reachable via ping.
    A failed gateway means traffic can't leave the local network at all.
    """
    log.debug("Running gateway probe...")
    system = platform.system().lower()
    gateway_ip = None

    try:
        if system == "windows":
            output = _run(["ipconfig"])
            for line in output.splitlines():
                if "Default Gateway" in line and ":" in line:
                    ip = line.split(":")[-1].strip()
                    if ip and ip != "":
                        gateway_ip = ip
                        break
        else:
            output = _run(["ip", "route", "show", "default"])
            parts = output.split()
            if "via" in parts:
                gateway_ip = parts[parts.index("via") + 1]

    except Exception as exc:
        log.warning(f"Gateway detection failed: {exc}")

    if not gateway_ip:
        log.warning("Could not detect default gateway")
        return {
            "status": "failed",
            "gateway_ip": None,
            "reachable": False,
            "details": "Could not detect default gateway IP",
        }

    reachable, avg_ms, _ = _ping(gateway_ip, count=2)
    status = "healthy" if reachable else "failed"

    log.info(f"Gateway: {status} | ip={gateway_ip} reachable={reachable} avg_ms={avg_ms}")
    return {
        "status": status,
        "gateway_ip": gateway_ip,
        "reachable": reachable,
        "avg_ms": avg_ms,
        "details": f"Gateway {gateway_ip} {'reachable' if reachable else 'unreachable'} avg={avg_ms}ms",
    }


def check_interfaces() -> dict[str, Any]:
    """
    Lists network interfaces and their up/down state.
    Helps identify if a specific adapter is disabled or disconnected.
    """
    log.debug("Running interfaces probe...")
    system = platform.system().lower()
    interfaces = []

    try:
        if system == "windows":
            output = _run(["netsh", "interface", "show", "interface"])
            for line in output.splitlines()[3:]:  # skip header rows
                parts = line.split()
                if len(parts) >= 4:
                    admin_state = parts[0]
                    state       = parts[1]
                    iface_type  = parts[2]
                    name        = " ".join(parts[3:])
                    interfaces.append({
                        "name":        name,
                        "admin_state": admin_state,
                        "state":       state,
                        "type":        iface_type,
                    })

        elif system == "linux":
            output = _run(["ip", "link", "show"])
            current = {}
            for line in output.splitlines():
                if line and line[0].isdigit():
                    if current:
                        interfaces.append(current)
                    parts = line.split(":")
                    name  = parts[1].strip() if len(parts) > 1 else "unknown"
                    state = "up" if "UP" in line else "down"
                    current = {"name": name, "state": state, "admin_state": "enabled"}
            if current:
                interfaces.append(current)

        elif system == "darwin":
            output = _run(["ifconfig", "-a"])
            for line in output.splitlines():
                if line and not line.startswith("\t") and ":" in line:
                    name  = line.split(":")[0]
                    state = "up" if "UP" in line else "down"
                    interfaces.append({"name": name, "state": state, "admin_state": "enabled"})

    except Exception as exc:
        log.error(f"Interface check failed: {exc}")

    active   = [i for i in interfaces if i.get("state", "").lower() in ("up", "connected")]
    inactive = [i for i in interfaces if i.get("state", "").lower() not in ("up", "connected")]
    status   = "healthy" if active else "failed"

    log.info(f"Interfaces: {status} | active={len(active)} inactive={len(inactive)}")
    return {
        "status":     status,
        "interfaces": interfaces,
        "active":     [i["name"] for i in active],
        "inactive":   [i["name"] for i in inactive],
        "details":    f"{len(active)} active, {len(inactive)} inactive interfaces",
    }


def check_ports() -> dict[str, Any]:
    """
    Checks if critical ports (53/DNS, 80/HTTP, 443/HTTPS) are reachable
    on a known reliable host. Helps diagnose firewall or ISP blocking.
    """
    log.debug("Running port probe...")
    open_ports   = []
    closed_ports = []

    for port in _CRITICAL_PORTS:
        try:
            sock = socket.create_connection((_PORT_TEST_HOST, port), timeout=3)
            sock.close()
            open_ports.append(port)
        except (socket.timeout, ConnectionRefusedError, OSError):
            closed_ports.append(port)

    total = len(_CRITICAL_PORTS)
    open_count = len(open_ports)

    if open_count == total:
        status = "healthy"
    elif open_count > 0:
        status = "degraded"
    else:
        status = "failed"

    log.info(f"Ports: {status} | open={open_ports} closed={closed_ports}")
    return {
        "status":       status,
        "open_ports":   open_ports,
        "closed_ports": closed_ports,
        "tested_host":  _PORT_TEST_HOST,
        "details":      f"{open_count}/{total} critical ports reachable on {_PORT_TEST_HOST}",
    }


def check_wifi() -> dict[str, Any]:
    """
    Detects WiFi connection state and signal strength where available.
    Returns connection type (wifi/ethernet/unknown) and signal info.
    """
    log.debug("Running WiFi/connection-type probe...")
    system = platform.system().lower()
    result = {
        "status":          "unknown",
        "connection_type": "unknown",
        "ssid":            None,
        "signal_strength": None,
        "details":         "",
    }

    try:
        if system == "windows":
            output = _run(["netsh", "wlan", "show", "interfaces"])
            if "There is no wireless interface" in output or output == "":
                result.update({
                    "status":          "healthy",
                    "connection_type": "ethernet",
                    "details":         "No wireless interface detected — likely on Ethernet",
                })
            else:
                ssid, signal = None, None
                for line in output.splitlines():
                    if "SSID" in line and "BSSID" not in line:
                        ssid = line.split(":")[-1].strip()
                    if "Signal" in line:
                        signal = line.split(":")[-1].strip()
                connected = "State" in output and "connected" in output.lower()
                result.update({
                    "status":          "healthy" if connected else "degraded",
                    "connection_type": "wifi",
                    "ssid":            ssid,
                    "signal_strength": signal,
                    "details":         f"WiFi {'connected' if connected else 'disconnected'} | SSID={ssid} signal={signal}",
                })

        elif system == "linux":
            output = _run(["iwgetid", "-r"])
            if output:
                result.update({
                    "status":          "healthy",
                    "connection_type": "wifi",
                    "ssid":            output,
                    "details":         f"Connected to WiFi SSID: {output}",
                })
            else:
                result.update({
                    "status":          "healthy",
                    "connection_type": "ethernet",
                    "details":         "No WiFi SSID detected — likely on Ethernet",
                })

        elif system == "darwin":
            output = _run([
                "/System/Library/PrivateFrameworks/Apple80211.framework"
                "/Versions/Current/Resources/airport", "-I"
            ])
            if output:
                ssid, rssi = None, None
                for line in output.splitlines():
                    if " SSID:" in line:
                        ssid = line.split(":")[-1].strip()
                    if "agrCtlRSSI" in line:
                        rssi = line.split(":")[-1].strip()
                result.update({
                    "status":          "healthy",
                    "connection_type": "wifi",
                    "ssid":            ssid,
                    "signal_strength": f"{rssi} dBm" if rssi else None,
                    "details":         f"WiFi SSID={ssid} signal={rssi}dBm",
                })
            else:
                result.update({
                    "status":          "healthy",
                    "connection_type": "ethernet",
                    "details":         "No WiFi detected — likely on Ethernet",
                })

    except Exception as exc:
        log.warning(f"WiFi probe failed: {exc}")
        result.update({"status": "unknown", "details": str(exc)})

    log.info(f"WiFi: {result['status']} | type={result['connection_type']} ssid={result['ssid']}")
    return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_dns_servers() -> list[str]:
    """Best-effort DNS server detection. Returns empty list if unavailable."""
    system = platform.system().lower()
    servers = []

    try:
        if system == "windows":
            result = subprocess.run(
                ["netsh", "interface", "ip", "show", "dns"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "DNS" in line and ":" in line:
                    parts = line.split(":")
                    if len(parts) > 1:
                        ip = parts[-1].strip()
                        if ip and ip not in servers:
                            servers.append(ip)
        else:
            with open("/etc/resolv.conf") as f:
                for line in f:
                    if line.startswith("nameserver"):
                        servers.append(line.split()[1])
    except Exception as exc:
        log.debug(f"Could not retrieve DNS servers: {exc}")

    return servers
