"""Bounded logging setup for the Windows GPU services."""
from __future__ import annotations
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

def configure_rotating_logging(
    logger_name: str,
    log_name: str,
    *,
    default_directory: str | None = None,
    max_bytes: int = 50 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure one bounded UTF-8 file sink for a service logger."""
    configured_max_bytes = int(os.environ.get("GPU_LOG_MAX_BYTES", str(max_bytes)))
    configured_backup_count = int(os.environ.get("GPU_LOG_BACKUP_COUNT", str(backup_count)))
    if configured_max_bytes <= 0 or configured_backup_count < 0:
        raise ValueError("GPU log rotation limits must be positive")
    directory = Path(os.environ.get("GPU_LOG_DIR", default_directory or "."))
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, "_gpu_rotating", False) for handler in logger.handlers):
        handler = RotatingFileHandler(
            directory / log_name,
            maxBytes=configured_max_bytes,
            backupCount=configured_backup_count,
            encoding="utf-8",
        )
        handler._gpu_rotating = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    return logger
