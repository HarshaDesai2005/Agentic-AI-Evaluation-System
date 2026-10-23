"""Logging with redaction of confidential examination content."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import config

_SECRETISH = re.compile(
    r"(password|secret|api[_-]?key|token|authorization)\s*[:=]\s*\S+",
    re.IGNORECASE,
)

_MAX_MSG = 400


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        msg = _SECRETISH.sub(r"\1=[REDACTED]", msg)
        if len(msg) > _MAX_MSG:
            msg = msg[:_MAX_MSG] + "…[truncated]"
        record.msg = msg
        record.args = ()
        return True


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("evalscheme")
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    log_path = Path(config.DATA_DIR) / "app.log"
    try:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        file_handler.addFilter(RedactingFilter())
        logger.addHandler(file_handler)
    except OSError:
        pass
    logger.propagate = False
    return logger


logger = setup_logging()
