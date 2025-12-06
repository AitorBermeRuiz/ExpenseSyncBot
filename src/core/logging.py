"""Logging configuration using Loguru."""

import os
import sys

from loguru import logger


def setup_logging(log_level: str = "INFO") -> None:
    """Configure the Loguru logger for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    LOG_FORMAT = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # Create logs directory
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Console handler
    logger.add(
        sink=sys.stderr,
        level=log_level.upper(),
        format=LOG_FORMAT,
        colorize=True,
    )

    # File handler with rotation
    logger.add(
        sink=os.path.join(log_dir, "expense_sync_{time}.log"),
        level=log_level.upper(),
        format=LOG_FORMAT,
        rotation="10 MB",
        retention="7 days",
        compression="gz",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    logger.info("Logger configured successfully")
