"""
utils/logger.py
Structured logging for network_medic.
All modules import get_logger() from here — never use print() or logging directly.
"""

import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "network_medic.log"

_fmt = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _build_handler(stream=None, filepath=None) -> logging.Handler:
    if filepath:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(filepath, encoding="utf-8")
    else:
        handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(_fmt)
    return handler


def get_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    """
    Returns a named logger with both console and file handlers.
    Usage:
        from utils.logger import get_logger
        log = get_logger(__name__)
        log.info("collector started")
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured, avoid duplicate handlers

    logger.setLevel(level)
    logger.addHandler(_build_handler(stream=sys.stdout))
    logger.addHandler(_build_handler(filepath=LOG_FILE))
    logger.propagate = False

    return logger
