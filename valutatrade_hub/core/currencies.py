"""Типы валют и реестр поддерживаемых кодов."""

import math
from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError


def validate_currency_code(code: str) -> str:
    """Проверка и приведение кода валюты к верхнему регистру."""
    if not isinstance(code, str):
        raise TypeError("Код валюты должен быть строкой")
    code = code.strip().upper()
    if not 2 <= len(code) <= 5 or not code.isascii() or not code.isalnum():
        raise ValueError(
            "Код валюты должен содержать от 2 до 5 латинских букв или цифр"
        )
    return code


def _validate_text(value: str, name: str) -> str:
    """Проверка непустого строкового значения."""
    if not isinstance(value, str):
        raise TypeError(f"{name} должно быть строкой")
    if not value.strip():
        raise ValueError(f"{name} не может быть пустым")
    return value.strip()


class Currency(ABC):
    """Базовый класс валюты."""

    def __init__(self, name: str, code: str) -> None:
        """Инициализация названия и кода валюты."""
        self.name = name
        self.code = code

    @property
    def name(self) -> str:
        """Получение названия валюты."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        """Изменение названия валюты."""
        self._name = _validate_text(value, "Название валюты")

    @property
    def code(self) -> str:
        """Получение кода валюты."""
        return self._code

    @code.setter
    def code(self, value: str) -> None:
        """Изменение кода валюты."""
        self._code = validate_currency_code(value)

    @abstractmethod
    def get_display_info(self) -> str:
        """Получение строкового представления валюты."""
        raise NotImplementedError


class FiatCurrency(Currency):
    """Фиатная валюта со страной или зоной эмиссии."""

    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        """Инициализация фиатной валюты."""
        super().__init__(name, code)
        self.issuing_country = issuing_country

    @property
    def issuing_country(self) -> str:
        """Получение страны или зоны эмиссии."""
        return self._issuing_country

    @issuing_country.setter
    def issuing_country(self, value: str) -> None:
        """Изменение страны или зоны эмиссии."""
        self._issuing_country = _validate_text(
            value, "Значение страны или зоны эмиссии"
        )

    def get_display_info(self) -> str:
        """Получение названия валюты и страны или зоны эмиссии."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом и значением капитализации."""

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float) -> None:
        """Инициализация криптовалюты."""
        super().__init__(name, code)
        self.algorithm = algorithm
        self.market_cap = market_cap

    @property
    def algorithm(self) -> str:
        """Получение названия алгоритма."""
        return self._algorithm

    @algorithm.setter
    def algorithm(self, value: str) -> None:
        """Изменение названия алгоритма."""
        self._algorithm = _validate_text(value, "Название алгоритма")

    @property
    def market_cap(self) -> float:
        """Получение значения капитализации."""
        return self._market_cap

    @market_cap.setter
    def market_cap(self, value: float) -> None:
        """Изменение значения капитализации."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Капитализация должна быть числом")
        try:
            number = float(value)
        except OverflowError:
            raise ValueError("Капитализация выходит за допустимый диапазон") from None
        if not math.isfinite(number) or number < 0:
            raise ValueError(
                "Капитализация должна быть конечным неотрицательным числом"
            )
        self._market_cap = number

    def get_display_info(self) -> str:
        """Получение названия валюты, алгоритма и капитализации."""
        market_cap = f"{self.market_cap:.2e}".replace("e+", "e")
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {market_cap})"
        )


_REGISTRY = {
    "USD": (FiatCurrency, {"name": "US Dollar", "issuing_country": "United States"}),
    "EUR": (FiatCurrency, {"name": "Euro", "issuing_country": "Eurozone"}),
    "RUB": (FiatCurrency, {"name": "Russian Ruble", "issuing_country": "Russia"}),
    "GBP": (
        FiatCurrency,
        {"name": "Pound Sterling", "issuing_country": "United Kingdom"},
    ),
    "BTC": (
        CryptoCurrency,
        {"name": "Bitcoin", "algorithm": "SHA-256", "market_cap": 1.12e12},
    ),
    "ETH": (
        CryptoCurrency,
        {"name": "Ethereum", "algorithm": "Ethash", "market_cap": 0.0},
    ),
    "SOL": (
        CryptoCurrency,
        {"name": "Solana", "algorithm": "Proof of Stake", "market_cap": 0.0},
    ),
}


def get_currency(code: str) -> Currency:
    """Создание объекта валюты по коду из реестра."""
    try:
        code = validate_currency_code(code)
    except ValueError:
        raise CurrencyNotFoundError(code.strip().upper()) from None
    if code not in _REGISTRY:
        raise CurrencyNotFoundError(code)
    currency_type, attributes = _REGISTRY[code]
    return currency_type(code=code, **attributes)


def supported_codes() -> tuple[str, ...]:
    """Получение поддерживаемых кодов валют."""
    return tuple(_REGISTRY)
