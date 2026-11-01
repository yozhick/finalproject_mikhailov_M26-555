"""Настройка файлового журнала операций."""

import logging
import time
from logging.handlers import RotatingFileHandler
from threading import RLock

from valutatrade_hub.infra.settings import SettingsLoader

_CONFIG_LOCK = RLock()
_configured_signatures = {}


def configure_logging(
    level: str | int | None = None, *, name: str = "actions"
) -> logging.Logger:
    """Настройка формата, уровня и ротации журнала."""
    if name not in ("actions", "parser"):
        raise ValueError("Неизвестный журнал приложения")
    settings = SettingsLoader()
    path = settings.get("PARSER_LOG_FILE" if name == "parser" else "LOG_FILE")
    level = settings.get("LOG_LEVEL") if level is None else level
    signature = (
        str(path),
        level,
        settings.get("LOG_FORMAT"),
        settings.get("LOG_DATE_FORMAT"),
        settings.get("LOG_MAX_BYTES"),
        settings.get("LOG_BACKUP_COUNT"),
    )
    with _CONFIG_LOCK:
        logger = logging.getLogger(f"valutatrade.{name}")
        handler_name = f"valutatrade.{name}.file"
        handlers = [
            handler for handler in logger.handlers if handler.get_name() == handler_name
        ]
        if len(handlers) == 1 and signature == _configured_signatures.get(name):
            logger.setLevel(level)
            return logger
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=settings.get("LOG_MAX_BYTES"),
            backupCount=settings.get("LOG_BACKUP_COUNT"),
            encoding="utf-8",
            delay=True,
        )
        formatter = logging.Formatter(
            settings.get("LOG_FORMAT"), settings.get("LOG_DATE_FORMAT")
        )
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        handler.set_name(handler_name)
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
        _configured_signatures[name] = signature
        return logger
