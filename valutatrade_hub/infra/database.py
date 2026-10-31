"""Доступ к JSON-файлам приложения."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from valutatrade_hub.core.utils import read_json, write_json
from valutatrade_hub.infra.settings import SettingsLoader


class DatabaseManager:
    """Общий экземпляр управления JSON-файлами."""

    _instance = None
    _instance_lock = RLock()

    def __new__(cls):
        """Получение единственного экземпляра доступа к данным."""
        # Реализация через __new__ явно показывает создание общего экземпляра.
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._lock = RLock()
                cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Инициализация доступа к файлам приложения."""
        with self._lock:
            if self._initialized:
                return
            self._settings = SettingsLoader()
            self._initialized = True

    def path(self, name: str | Path) -> Path:
        """Определение пути файла данных."""
        keys = {
            "users": "USERS_FILE",
            "portfolios": "PORTFOLIOS_FILE",
            "rates": "RATES_FILE",
        }
        if isinstance(name, str) and name in keys:
            return self._settings.get(keys[name])
        path = Path(name)
        return path if path.is_absolute() else self._settings.get("DATA_DIR") / path

    def read(self, name: str | Path, default: Any = None) -> Any:
        """Чтение данных из JSON-файла."""
        with self._lock:
            return read_json(self.path(name), default)

    def write(self, name: str | Path, data: Any) -> None:
        """Сохранение данных в JSON-файл."""
        with self._lock:
            write_json(self.path(name), data)

    @contextmanager
    def locked(self) -> Iterator["DatabaseManager"]:
        """Выполнение операций под общей блокировкой."""
        with self._lock:
            yield self
