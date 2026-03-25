"""
utils/os_detector.py
Detects the host OS once at runtime and caches the result.
Used by executor.py to dispatch to the correct platform module.
"""

import platform
from enum import Enum

from utils.logger import get_logger

log = get_logger(__name__)


class OS(str, Enum):
    LINUX   = "linux"
    WINDOWS = "windows"
    MAC     = "mac"
    UNKNOWN = "unknown"


_cached_os: OS | None = None


def get_os() -> OS:
    """
    Returns the current OS as an OS enum value.
    Result is cached after first call.

    Usage:
        from utils.os_detector import get_os, OS
        if get_os() == OS.LINUX:
            ...
    """
    global _cached_os
    if _cached_os is not None:
        return _cached_os

    system = platform.system().lower()

    if system == "linux":
        _cached_os = OS.LINUX
    elif system == "windows":
        _cached_os = OS.WINDOWS
    elif system == "darwin":
        _cached_os = OS.MAC
    else:
        _cached_os = OS.UNKNOWN

    log.debug(f"Detected OS: {_cached_os.value} (platform.system={platform.system()})")
    return _cached_os


def assert_supported() -> None:
    """
    Raises RuntimeError if the OS is not supported.
    Call this at startup in main.py or orchestrator.py.
    """
    os = get_os()
    if os == OS.UNKNOWN:
        raise RuntimeError(
            f"Unsupported OS: {platform.system()}. "
            "network_medic supports Linux, Windows, and macOS only."
        )
