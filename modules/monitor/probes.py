"""
modules/monitor/probes.py
Network probe functions: connectivity, DNS, latency.
Each probe returns a standardised dict conforming to state_schema.json probe fields.
collector.py calls all three and assembles the final SystemState.
"""

import socket
import subprocess
import platform
from datetime import datetime, timezone
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)

# Hosts used for probing — chosen for reliability
_CONNECTIVITY_HOSTS = ["8.8.8.8", "1.1.1.1", "208.67.222.222"]
_DNS_DOMAINS        = ["google.com", "cloudflare.com", "github.com"]
_LATENCY_TARGET     = "8.8.8.8"
_PING_COUNT         = 4


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

        # Parse avg latency from output (best-effort, platform differences acceptable)
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


# ── Probes ────────────────────────────────────────────────────────────────────

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

    # Get current DNS servers (best-effort, platform-specific)
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
