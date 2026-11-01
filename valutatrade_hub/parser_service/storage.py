"""Хранение истории измерений и последних курсов."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from valutatrade_hub.core.currencies import validate_currency_code
from valutatrade_hub.core.utils import parse_timestamp, validate_number
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.config import ParserConfig


class RatesStorage:
    """JSON-хранилище измерений и кеша валютных пар."""

    def __init__(self, config: ParserConfig | None = None) -> None:
        """Инициализация настроек файлов и доступа к данным."""
        self.config = config if config is not None else ParserConfig()
        self.database = DatabaseManager()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Блокировка обновления истории и кеша между потоками и процессами."""
        with self.database.locked():
            path = self.config.HISTORY_FILE_PATH.parent / ".parser.lock"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a+b") as lock:
                if lock.tell() == 0:
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    lock.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _measurement(record: dict[str, Any]) -> dict[str, Any]:
        """Проверка измерения и формирование идентификатора пары и времени."""
        if not isinstance(record, dict):
            raise ValueError("Измерение должно содержать объект")
        code = validate_currency_code(record["from_currency"])
        base = validate_currency_code(record["to_currency"])
        rate = validate_number(record["rate"], "Значение курса", positive=True)
        timestamp = (
            parse_timestamp(record["timestamp"]).isoformat().replace("+00:00", "Z")
        )
        source = record["source"]
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Не задан источник измерения")
        meta = record.get("meta", {})
        if not isinstance(meta, dict):
            raise ValueError("Метаданные измерения должны содержать объект")
        return {
            "id": f"{code}_{base}_{timestamp}",
            "from_currency": code,
            "to_currency": base,
            "rate": rate,
            "timestamp": timestamp,
            "source": source,
            "meta": dict(meta),
        }

    def save(self, measurements: list[dict[str, Any]]) -> dict[str, Any]:
        """Дополнение истории и сохранение более свежих курсов."""
        with self._locked():
            records = [self._measurement(record) for record in measurements]
            history = self.database.read(self.config.HISTORY_FILE_PATH, [])
            if not isinstance(history, list):
                raise ValueError("История курсов должна содержать список")
            history = [self._measurement(record) for record in history]
            known = {record["id"]: record for record in history}
            cache = self.database.read(self.config.RATES_FILE_PATH, {})
            if not isinstance(cache, dict):
                raise ValueError("Кеш курсов должен содержать объект")
            pairs = cache.get("pairs")
            if pairs is None:
                # Чтение формата кеша из предыдущего раздела задания.
                pairs = {
                    key: {**value, "source": cache.get("source", "Cache")}
                    for key, value in cache.items()
                    if "_" in key and isinstance(value, dict)
                }
            if not isinstance(pairs, dict):
                raise ValueError("Курсы в кеше должны содержать объект")
            pairs = dict(pairs)
            updated_pairs = set()
            added = 0
            for record in records:
                if record["id"] not in known:
                    known[record["id"]] = record
                    history.append(record)
                    added += 1
                record = known[record["id"]]
                pair = f"{record['from_currency']}_{record['to_currency']}"
                current = pairs.get(pair)
                if current is not None:
                    current_date = parse_timestamp(current["updated_at"])
                    if current_date >= parse_timestamp(record["timestamp"]):
                        continue
                pairs[pair] = {
                    "rate": record["rate"],
                    "updated_at": record["timestamp"],
                    "source": record["source"],
                }
                updated_pairs.add(pair)
            stamp = cache.get("last_refresh")
            if updated_pairs:
                stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            # История сохраняется первой; повторная запись не дублирует измерения.
            if added:
                self.database.write(self.config.HISTORY_FILE_PATH, history)
            if updated_pairs:
                self.database.write(
                    self.config.RATES_FILE_PATH, {"pairs": pairs, "last_refresh": stamp}
                )
            return {"updated": len(updated_pairs), "last_refresh": stamp}
