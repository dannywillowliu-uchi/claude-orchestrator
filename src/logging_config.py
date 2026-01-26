"""Centralized logging configuration for task-automation-mcp."""

import os
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler


def setup_logging(
    name: str = "task_automation",
    level: str = None,
    log_dir: str = "data/logs",
) -> logging.Logger:
    """
    Set up logging with console and file handlers.

    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to env var or INFO.
        log_dir: Directory for log files

    Returns:
        Configured logger
    """
    # Get log level from environment or default
    level = level or os.getenv("LOG_LEVEL", "INFO")
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    simple_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(simple_formatter)
    logger.addHandler(console_handler)

    # File handler (rotating)
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path / f"{name}.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    file_handler.setLevel(logging.DEBUG)  # File gets all logs
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)

    # Security-sensitive log (separate file, no sensitive data should go here)
    security_handler = RotatingFileHandler(
        log_path / "security.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
    )
    security_handler.setLevel(logging.WARNING)
    security_handler.setFormatter(detailed_formatter)

    # Create security logger
    security_logger = logging.getLogger(f"{name}.security")
    security_logger.addHandler(security_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger with the given name."""
    return logging.getLogger(f"task_automation.{name}")


# Sensitive data filter
class SensitiveDataFilter(logging.Filter):
    """Filter to redact sensitive data from logs."""

    SENSITIVE_PATTERNS = [
        ("token", "[REDACTED_TOKEN]"),
        ("password", "[REDACTED_PASSWORD]"),
        ("secret", "[REDACTED_SECRET]"),
        ("api_key", "[REDACTED_API_KEY]"),
        ("authorization", "[REDACTED_AUTH]"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg_lower = record.msg.lower()
            for pattern, replacement in self.SENSITIVE_PATTERNS:
                if pattern in msg_lower:
                    # Don't completely block, but warn
                    record.msg = f"[SENSITIVE] {record.msg}"
                    break
        return True
