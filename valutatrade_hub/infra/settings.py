"""Загрузка и хранение настроек приложения."""

import json
import math
import tomllib
from pathlib import Path
from threading import RLock
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULTS = {
    "DATA_DIR": "data",
    "USERS_FILE": "users.json",
    "PORTFOLIOS_FILE": "portfolios.json",
    "RATES_FILE": "rates.json",
    "HISTORY_FILE": "exchange_rates.json",
    "RATES_TTL_SECONDS": 300,
    "DEFAULT_BASE_CURRENCY": "USD",
    "LOG_DIR": "logs",
    "LOG_FILE": "actions.log",
    "PARSER_LOG_FILE": "parser.log",
    "LOG_LEVEL": "INFO",
    "LOG_FORMAT": "%(levelname)s %(asctime)s %(message)s",
    "LOG_DATE_FORMAT": "%Y-%m-%dT%H:%M:%S",
    "LOG_MAX_BYTES": 1_048_576,
    "LOG_BACKUP_COUNT": 3,
    "LOG_VERBOSE": False,
}


class SettingsLoader:
    """Общий экземпляр настроек приложения."""

    _instance = None
    _instance_lock = RLock()

    def __new__(cls, *args, **kwargs):
        """Получение единственного экземпляра настроек."""
        # Реализация через __new__ явно показывает создание общего экземпляра.
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._lock = RLock()
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: Path | None = None) -> None:
        """Инициализация конфигурации приложения."""
        with self._lock:
            if self._initialized:
                return
            self._config_path = Path(
                config_path or PROJECT_ROOT / "pyproject.toml"
            ).resolve()
            self._values: dict[str, Any] = {}
            self.reload()
            self._initialized = True

    @property
    def config_path(self) -> Path:
        """Получение пути конфигурации."""
        return self._config_path

    def get(self, key: str, default: Any = None) -> Any:
        """Получение значения параметра конфигурации."""
        with self._lock:
            return self._values.get(key, default)

    def reload(self, config_path: Path | None = None) -> None:
        """Повторная загрузка конфигурации приложения."""
        with self._lock:
            path = Path(config_path or self._config_path).resolve()
            if path.suffix.lower() == ".json":
                with path.open(encoding="utf-8") as file:
                    configured = json.load(file)
            else:
                with path.open("rb") as file:
                    document = tomllib.load(file)
                configured = document.get("tool", {}).get("valutatrade", {})
            if not isinstance(configured, dict):
                raise ValueError("Конфигурация должна содержать объект с параметрами")
            values = {**DEFAULTS, **configured}
            ttl = values["RATES_TTL_SECONDS"]
            if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
                raise TypeError("RATES_TTL_SECONDS должен быть числом")
            if not math.isfinite(ttl) or ttl <= 0:
                raise ValueError("RATES_TTL_SECONDS должен быть положительным числом")
            for key in ("LOG_MAX_BYTES", "LOG_BACKUP_COUNT"):
                value = values[key]
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValueError(f"{key} должен быть положительным целым числом")
            if not isinstance(values["LOG_VERBOSE"], bool):
                raise TypeError("LOG_VERBOSE должен иметь тип bool")
            level = values["LOG_LEVEL"]
            if not isinstance(level, str) or level.upper() not in {
                "DEBUG",
                "INFO",
                "WARNING",
                "ERROR",
                "CRITICAL",
            }:
                raise ValueError("Неизвестный уровень журналирования")
            values["LOG_LEVEL"] = level.upper()
            base = values["DEFAULT_BASE_CURRENCY"]
            if not isinstance(base, str) or not base.strip():
                raise ValueError("Базовая валюта должна быть непустой строкой")
            values["DEFAULT_BASE_CURRENCY"] = base.strip().upper()
            for key in ("LOG_FORMAT", "LOG_DATE_FORMAT"):
                if not isinstance(values[key], str) or not values[key]:
                    raise ValueError(f"{key} должен быть непустой строкой")
            for key, parent in (("DATA_DIR", path.parent), ("LOG_DIR", path.parent)):
                values[key] = self._resolve_path(values[key], parent)
            for key in ("USERS_FILE", "PORTFOLIOS_FILE", "RATES_FILE", "HISTORY_FILE"):
                values[key] = self._resolve_path(values[key], values["DATA_DIR"])
            values["LOG_FILE"] = self._resolve_path(
                values["LOG_FILE"], values["LOG_DIR"]
            )
            values["PARSER_LOG_FILE"] = self._resolve_path(
                values["PARSER_LOG_FILE"], values["LOG_DIR"]
            )
            self._values = values
            self._config_path = path

    @staticmethod
    def _resolve_path(value: str | Path, parent: Path) -> Path:
        """Определение полного пути параметра конфигурации."""
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ValueError("Путь должен быть непустой строкой")
        path = Path(value)
        return (path if path.is_absolute() else parent / path).resolve()
