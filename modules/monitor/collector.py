"""
modules/monitor/collector.py
Aggregates all probe results into a single SystemState dict.
This is the OBSERVE stage entry point called by orchestrator.py.

Output conforms to state_schema.json.
"""

import uuid
from datetime import datetime, timezone

from modules.monitor.probes import (
    check_connectivity,
    check_dns,
    check_latency,
    check_gateway,
    check_interfaces,
    check_ports,
    check_wifi,
)
from utils.os_detector import get_os
from utils.logger import get_logger

log = get_logger(__name__)


def _derive_overall_health(probes: dict) -> str:
    """
    Derives aggregate health from individual probe statuses.
    Logic: any 'failed' → failed | any 'degraded' → degraded | else healthy
    """
    statuses = [p.get("status", "failed") for p in probes.values()]
    if "failed" in statuses:
        return "failed"
    if "degraded" in statuses:
        return "degraded"
    return "healthy"


def _detect_anomalies(probes: dict) -> list[str]:
    """
    Produces a human-readable list of anomaly descriptions for prompt injection.
    Covers all probes including new device state checks.
    """
    anomalies = []

    # Connectivity
    conn = probes.get("connectivity", {})
    if conn.get("status") == "failed":
        anomalies.append("No connectivity to any external host — complete network failure.")
    elif conn.get("status") == "degraded":
        anomalies.append(f"Partial connectivity loss — unreachable hosts: {conn.get('unreachable_hosts')}")

    # DNS
    dns = probes.get("dns", {})
    if dns.get("status") == "failed":
        anomalies.append("DNS resolution completely failed — all test domains unresolvable.")
    elif dns.get("status") == "degraded":
        anomalies.append(f"DNS resolution degraded — failed domains: {dns.get('failed')}")

    # Latency
    latency = probes.get("latency", {})
    if latency.get("status") == "failed":
        anomalies.append(f"No response from latency target {latency.get('target_host')} — host unreachable.")
    elif latency.get("status") == "degraded":
        anomalies.append(
            f"High latency or packet loss — "
            f"avg={latency.get('avg_ms')}ms loss={latency.get('packet_loss_pct')}%"
        )

    # Gateway
    gateway = probes.get("gateway", {})
    if gateway.get("status") == "failed":
        anomalies.append(
            f"Default gateway {gateway.get('gateway_ip', 'unknown')} is unreachable — "
            "traffic cannot leave the local network."
        )

    # Interfaces
    interfaces = probes.get("interfaces", {})
    if interfaces.get("status") == "failed":
        anomalies.append("No active network interfaces detected — all adapters may be disabled.")
    elif interfaces.get("inactive"):
        anomalies.append(f"Inactive interfaces detected: {interfaces.get('inactive')}")

    # Ports
    ports = probes.get("ports", {})
    if ports.get("status") == "failed":
        anomalies.append(
            f"All critical ports blocked on {ports.get('tested_host')} — "
            "firewall or ISP restriction suspected."
        )
    elif ports.get("status") == "degraded":
        anomalies.append(f"Some critical ports unreachable: {ports.get('closed_ports')}")

    # WiFi
    wifi = probes.get("wifi", {})
    if wifi.get("status") == "degraded":
        anomalies.append(
            f"WiFi disconnected — SSID={wifi.get('ssid')} signal={wifi.get('signal_strength')}"
        )

    return anomalies


def collect() -> dict:
    """
    Runs all probes and returns a complete SystemState snapshot.
    Called by orchestrator.py at the start of every pipeline run.

    Returns:
        dict conforming to state_schema.json
    """
    log.info("Starting system state collection...")

    probes = {
        "connectivity": check_connectivity(),
        "dns":          check_dns(),
        "latency":      check_latency(),
        "gateway":      check_gateway(),
        "interfaces":   check_interfaces(),
        "ports":        check_ports(),
        "wifi":         check_wifi(),
    }

    overall_health = _derive_overall_health(probes)
    anomalies      = _detect_anomalies(probes)

    state = {
        "snapshot_id":    str(uuid.uuid4()),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "os":             get_os().value,
        "probes":         probes,
        "overall_health": overall_health,
        "anomalies":      anomalies,
    }

    log.info(
        f"Collection complete | health={overall_health} "
        f"anomalies={len(anomalies)} | snapshot_id={state['snapshot_id']}"
    )
    return state
