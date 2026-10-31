"""Доступ к JSON-файлам приложения."""

import json
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from valutatrade_hub.infra.settings import SettingsLoader


def read_json(path: Path, default: Any) -> Any:
    """Чтение данных из JSON-файла."""
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def write_json(path: Path, data: Any) -> None:
    """Сохранение данных в JSON-файл."""
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as file:
            temporary_path = Path(file.name)
            file.write(text)
        for attempt in range(5):
            try:
                temporary_path.replace(path)
                break
            except PermissionError as error:
                if getattr(error, "winerror", None) not in (5, 32) or attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


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
