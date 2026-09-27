"""Structured logging helpers for PFAI processes."""
from __future__ import annotations

import logging
import os
import sys


def setup_logging(name: str = "pfai", level: str | None = None) -> logging.Logger:
    log_level = (level or os.getenv("PFAI_LOG_LEVEL", "INFO")).upper()
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.setLevel(log_level)
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(log_level)
    logger.propagate = False
    return logger
