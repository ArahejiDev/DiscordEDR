"""
Plain-text logger. Complements the database: the DB is for structured
queries, this log is for quick inspection / tail -f.

Uses RotatingFileHandler so edr.log doesn't grow forever: once it exceeds
LOG_MAX_BYTES it rotates to edr.log.1, edr.log.2..., keeping at most
LOG_BACKUP_COUNT old files (the oldest ones are deleted automatically).
"""
import logging
from logging.handlers import RotatingFileHandler
import os
from bot.config import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT


def setup_logger():
    directory = os.path.dirname(LOG_FILE)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    logger = logging.getLogger("discord_edr")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger  # avoid duplicate handlers if this is called more than once

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


log = setup_logger()