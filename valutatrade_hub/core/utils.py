"""Проверка данных моделей и чтение JSON-файлов."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valutatrade_hub.core.currencies import (
    get_currency,
    validate_currency_code,
)
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


def validate_amount(amount: float | str) -> float:
    """Проверка положительного количества валюты."""
    message = "'amount' должен быть положительным числом"
    if isinstance(amount, str):
        try:
            amount = float(amount)
        except ValueError:
            raise ValueError(message) from None
    try:
        return validate_number(amount, "Значение суммы", positive=True)
    except (TypeError, ValueError):
        raise ValueError(message) from None


def validate_user_id(user_id: int) -> int:
    """Проверка типа и значения идентификатора пользователя."""
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise TypeError("Идентификатор пользователя должен быть целым числом.")
    if user_id <= 0:
        raise ValueError("Идентификатор пользователя должен быть положительным.")
    return user_id


def validate_number(value: float, name: str, *, positive: bool = False) -> float:
    """Проверка типа, конечности и знака числа."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} должно быть числом.")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{name} выходит за допустимый диапазон.") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} должно быть конечным числом.")
    if number < 0 or (positive and number == 0):
        constraint = "положительным" if positive else "неотрицательным"
        raise ValueError(f"{name} должно быть {constraint} числом.")
    return number


def load_user_data(user_id: int) -> dict[str, Any]:
    """Чтение данных пользователя по идентификатору из users.json."""

    validate_user_id(user_id)
    users = DatabaseManager().read("users", [])
    if not isinstance(users, list) or any(not isinstance(user, dict) for user in users):
        raise ValueError("Файл пользователей должен содержать список объектов.")
    matches = [user for user in users if user.get("user_id") == user_id]
    if not matches:
        raise ValueError(f"Пользователь с идентификатором {user_id} не найден.")
    if len(matches) > 1:
        raise ValueError(f"Идентификатор пользователя {user_id} повторяется.")
    return matches[0]


def parse_timestamp(value: str) -> datetime:
    """Преобразование метки времени в дату и время UTC."""
    date = datetime.fromisoformat(value)
    return (
        date.replace(tzinfo=timezone.utc)
        if date.tzinfo is None
        else date.astimezone(timezone.utc)
    )


@dataclass(frozen=True)
class RateQuote:
    """Курс валютной пары с датой обновления и источником."""

    from_currency: str
    to_currency: str
    rate: float
    updated_at: datetime
    source: str

    @property
    def inverse_rate(self) -> float:
        """Получение обратного курса валютной пары."""
        return validate_number(1 / self.rate, "Значение курса", positive=True)


class RateService:
    """Чтение курсов из локального кеша с проверкой срока хранения."""

    def __init__(
        self,
        cache_path: Path | None = None,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float | None = None,
    ) -> None:
        """Инициализация пути кеша и срока хранения курсов."""
        self._settings = SettingsLoader()
        self._database = DatabaseManager()
        self._cache_path = None if cache_path is None else Path(cache_path).resolve()
        self._ttl_seconds = ttl_seconds
        if ttl_seconds is not None:
            validate_number(ttl_seconds, "Время хранения", positive=True)
        self.clock = clock

    @property
    def cache_path(self) -> Path:
        """Получение пути кеша курсов."""
        return (
            self._cache_path
            if self._cache_path is not None
            else self._database.path("rates")
        )

    @property
    def ttl_seconds(self) -> float:
        """Получение срока хранения курса."""
        value = (
            self._settings.get("RATES_TTL_SECONDS")
            if self._ttl_seconds is None
            else self._ttl_seconds
        )
        return validate_number(value, "Время хранения", positive=True)

    def _load_cache(self) -> dict[str, Any]:
        """Чтение кеша с поддержкой предыдущего формата файла."""
        try:
            data = self._database.read(self.cache_path, {})
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        if "pairs" in data:
            return data if isinstance(data["pairs"], dict) else {}
        return {
            "pairs": {
                key: {**value, "source": data.get("source", "Cache")}
                for key, value in data.items()
                if "_" in key and isinstance(value, dict)
            },
            "last_refresh": data.get("last_refresh"),
        }

    def _pair(self, data: dict, code: str, base: str) -> RateQuote | None:
        """Получение наиболее свежего прямого или обратного курса."""
        candidates = []
        for key, inverse in ((f"{code}_{base}", False), (f"{base}_{code}", True)):
            record = data.get("pairs", {}).get(key)
            if not isinstance(record, dict):
                continue
            try:
                rate = validate_number(record["rate"], "Значение курса", positive=True)
                date = parse_timestamp(record["updated_at"])
                if inverse:
                    rate = validate_number(1 / rate, "Значение курса", positive=True)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if date.timestamp() <= self.clock():
                candidates.append(
                    RateQuote(
                        code, base, rate, date, str(record.get("source", "Cache"))
                    )
                )
        return max(candidates, key=lambda item: item.updated_at) if candidates else None

    def _quote(self, data: dict, code: str, base: str) -> RateQuote | None:
        """Расчёт курса напрямую или через общую валюту двух пар."""
        candidates = []
        direct = self._pair(data, code, base)
        if direct is not None:
            candidates.append(direct)
        anchors = {
            part for pair in data.get("pairs", {}) for part in pair.split("_")
        } - {code, base}
        for anchor in sorted(anchors):
            first = self._pair(data, code, anchor)
            second = self._pair(data, base, anchor)
            if first is None or second is None:
                continue
            try:
                rate = validate_number(
                    first.rate / second.rate, "Значение курса", positive=True
                )
            except (ValueError, OverflowError):
                continue
            sources = ", ".join(sorted({first.source, second.source}))
            candidates.append(
                RateQuote(
                    code, base, rate, min(first.updated_at, second.updated_at), sources
                )
            )
        return max(candidates, key=lambda item: item.updated_at) if candidates else None

    def validate_freshness(self, quote: RateQuote) -> None:
        """Проверка срока хранения курса с сообщением об обновлении кеша."""
        if quote.from_currency == quote.to_currency:
            return
        age = self.clock() - quote.updated_at.timestamp()
        if not 0 <= age < self.ttl_seconds:
            raise ValueError(
                f"Курс {quote.from_currency}→{quote.to_currency} устарел. "
                "Выполните 'update-rates', чтобы обновить данные."
            )

    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Получение актуального курса валютной пары из кеша."""
        code = get_currency(from_currency).code
        base = get_currency(to_currency).code
        if code == base:
            return RateQuote(
                code,
                base,
                1.0,
                datetime.fromtimestamp(self.clock(), timezone.utc),
                "Identity",
            )
        quote = self._quote(self._load_cache(), code, base)
        if quote is None:
            raise ValueError(
                f"Курс {code}→{base} отсутствует в кеше. "
                "Выполните 'update-rates', чтобы загрузить данные."
            )
        self.validate_freshness(quote)
        return quote

    def cached_rates(self, base_currency: str, currency: str | None = None) -> dict:
        """Получение курсов из кеша в указанной базовой валюте."""
        base = get_currency(base_currency).code
        data = self._load_cache()
        pairs = data.get("pairs", {})
        if not pairs:
            raise ValueError(
                "Локальный кеш курсов пуст. "
                "Выполните 'update-rates', чтобы загрузить данные."
            )
        codes = {part for pair in pairs for part in pair.split("_")}
        if currency is not None:
            code = validate_currency_code(currency)
            if code not in codes:
                raise ValueError(f"Курс для '{code}' не найден в кеше.")
            codes = {code}
        else:
            codes.discard(base)
        quotes = []
        for code in sorted(codes):
            quote = (
                self.get_rate(code, base)
                if code == base
                else self._quote(data, code, base)
            )
            if quote is not None:
                quotes.append(quote)
        if not quotes:
            raise ValueError("В кеше отсутствуют курсы для выбранной базовой валюты")
        stamp = data.get("last_refresh") or max(
            quote.updated_at for quote in quotes
        ).isoformat().replace("+00:00", "Z")
        return {"quotes": quotes, "last_refresh": stamp}
