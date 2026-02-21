"""Centralized Loguru logging configuration."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from loguru import logger


class InterceptHandler(logging.Handler):
    """Forward stdlib logging records to Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        level: object
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(
    log_file_prefix: str,
    logs_dir: str = "logs",
    third_party_levels: Optional[Dict[str, str]] = None,
) -> str:
    """Configure Loguru file/console sinks and stdlib interception."""
    log_path = Path(logs_dir)
    log_path.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_path / f"{log_file_prefix}_{timestamp}.log"

    logger.remove()
    logger.add(
        str(log_file),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name} | {message}",
        encoding="utf-8",
    )
    logger.add(sys.stdout, level="INFO", format="{message}")

    logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG, force=True)

    if third_party_levels:
        for logger_name, level_name in third_party_levels.items():
            level_value = getattr(logging, level_name.upper(), logging.INFO)
            logging.getLogger(logger_name).setLevel(level_value)

    return str(log_file)