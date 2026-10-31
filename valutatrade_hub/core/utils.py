"""Проверка данных моделей и чтение JSON-файлов."""

import json
import math
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valutatrade_hub.core.currencies import (
    get_currency,
    supported_codes,
    validate_currency_code,
)
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.settings import SettingsLoader

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
USERS_FILE = DATA_DIR / "users.json"
RATES_FILE = DATA_DIR / "rates.json"


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


def read_records(path: Path) -> list[dict[str, Any]]:
    """Чтение списка записей из JSON-файла."""
    records = read_json(path, [])
    if not isinstance(records, list) or any(
        not isinstance(item, dict) for item in records
    ):
        raise ValueError(f"Файл {path.name} должен содержать список объектов.")
    return records


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
    from valutatrade_hub.infra.database import DatabaseManager

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


def load_exchange_rates() -> dict[str, float]:
    """Чтение курсов из rates.json, выраженных в USD за единицу валюты."""
    from valutatrade_hub.infra.database import DatabaseManager

    data = DatabaseManager().read("rates", {})
    if not isinstance(data, dict):
        raise ValueError("Файл курсов должен содержать объект с кодами валют.")
    rates = {"USD": 1.0}
    for pair, record in data.items():
        if pair.endswith("_USD") and isinstance(record, dict):
            code = validate_currency_code(pair.removesuffix("_USD"))
            rates[code] = validate_number(
                record.get("rate"), "Значение курса", positive=True
            )
    return rates


def get_exchange_rate(
    currency_code: str,
    base_currency: str = "USD",
    exchange_rates: Mapping[str, float] | None = None,
) -> float:
    """Расчёт курса валютной пары по курсам относительно USD."""
    code = get_currency(currency_code).code
    base = get_currency(base_currency).code
    if code == base:
        return 1.0
    rates = load_exchange_rates() if exchange_rates is None else exchange_rates
    if not isinstance(rates, Mapping):
        raise TypeError("Курсы должны быть представлены словарём.")
    values = {}
    for symbol in (code, base):
        if symbol not in rates:
            raise ValueError(f"Курс валюты {symbol} отсутствует.")
        values[symbol] = validate_number(rates[symbol], "Значение курса", positive=True)
    return validate_number(values[code] / values[base], "Значение курса", positive=True)


STUB_RATES = {
    "EUR_USD": 1.0786,
    "BTC_USD": 59337.21,
    "RUB_USD": 0.01016,
    "ETH_USD": 3720.0,
}


def fetch_stub_rates() -> dict[str, Any]:
    """Получение фиксированных учебных курсов валют."""
    return {
        **{pair: {"rate": rate} for pair, rate in STUB_RATES.items()},
        "source": "StubParserService",
    }


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
    """Сервис получения курсов валют."""

    def __init__(
        self,
        cache_path: Path | None = None,
        provider: Callable[[], dict[str, Any]] | None = fetch_stub_rates,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float | None = None,
    ) -> None:
        """Инициализация кеша и источника курсов."""
        from valutatrade_hub.infra.database import DatabaseManager

        self._settings = SettingsLoader()
        self._database = DatabaseManager()
        self._cache_path = None if cache_path is None else Path(cache_path).resolve()
        self._ttl_seconds = ttl_seconds
        if ttl_seconds is not None:
            validate_number(ttl_seconds, "Время хранения", positive=True)
        self.provider = provider
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
        """Чтение кеша курсов валют."""
        try:
            data = self._database.read(self.cache_path, {})
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def known_currencies(self) -> set[str]:
        """Получение кодов зарегистрированных валют."""
        return set(supported_codes())

    def _pair(
        self, data: dict[str, Any], code: str, base: str
    ) -> tuple[float, datetime] | None:
        """Получение прямого или обратного курса из кеша."""
        candidates = []
        for key, inverse in ((f"{code}_{base}", False), (f"{base}_{code}", True)):
            record = data.get(key)
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
                candidates.append((rate, date))
        return max(candidates, key=lambda item: item[1]) if candidates else None

    def _quote(self, data: dict[str, Any], code: str, base: str) -> RateQuote | None:
        """Расчёт курса валютной пары по данным кеша."""
        source = str(data.get("source", "Cache"))
        candidates = []
        direct = self._pair(data, code, base)
        if direct is not None:
            candidates.append(direct)
        if code != "USD" and base != "USD":
            first = self._pair(data, code, "USD")
            second = self._pair(data, base, "USD")
            if first is not None and second is not None:
                try:
                    rate = validate_number(
                        first[0] / second[0], "Значение курса", positive=True
                    )
                except (ValueError, OverflowError):
                    pass
                else:
                    candidates.append((rate, min(first[1], second[1])))
        if not candidates:
            return None
        rate, date = max(candidates, key=lambda item: item[1])
        return RateQuote(code, base, rate, date, source)

    def _is_fresh(self, quote: RateQuote) -> bool:
        """Проверка срока хранения курса."""
        age = self.clock() - quote.updated_at.timestamp()
        return 0 <= age < self.ttl_seconds

    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Получение курса валютной пары с проверкой срока хранения."""
        code = get_currency(from_currency).code
        base = get_currency(to_currency).code
        with self._database.locked():
            return self._get_rate(code, base)

    def _get_rate(self, code: str, base: str) -> RateQuote:
        """Чтение курса и обновление просроченных данных."""
        if code == base:
            return RateQuote(
                code,
                base,
                1.0,
                datetime.fromtimestamp(self.clock(), timezone.utc),
                "Identity",
            )
        data = self._load_cache()
        quote = self._quote(data, code, base)
        if quote is not None and self._is_fresh(quote):
            return quote
        if self.provider is None:
            raise ApiRequestError(f"Источник курсов недоступен для {code}→{base}")
        try:
            updates = self.provider()
            if not isinstance(updates, dict):
                raise ValueError("Некорректный ответ источника курсов")
            now = datetime.fromtimestamp(self.clock(), timezone.utc)
            stamp = now.replace(tzinfo=None).isoformat(timespec="seconds")
            refreshed = dict(data)
            for key, record in updates.items():
                if "_" not in key or not isinstance(record, dict):
                    continue
                parts = key.split("_")
                if len(parts) != 2:
                    raise ValueError("Некорректная валютная пара источника курсов")
                for part in parts:
                    validate_currency_code(part)
                rate = validate_number(record["rate"], "Значение курса", positive=True)
                updated_at = record.get("updated_at", stamp)
                parse_timestamp(updated_at)
                refreshed[key] = {"rate": rate, "updated_at": updated_at}
            refreshed["source"] = updates.get("source", "ParserService")
            refreshed["last_refresh"] = stamp
            quote = self._quote(refreshed, code, base)
            if quote is None or not self._is_fresh(quote):
                raise ApiRequestError(f"Курс {code}→{base} отсутствует или устарел")
            self._database.write(self.cache_path, refreshed)
            return quote
        except ApiRequestError:
            raise
        except (KeyError, TypeError, ValueError, OSError, OverflowError) as error:
            raise ApiRequestError(str(error)) from error
