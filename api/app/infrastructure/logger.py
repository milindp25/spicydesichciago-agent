from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "info") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


def get_logger(name: str = "api") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
