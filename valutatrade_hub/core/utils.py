"""Проверка данных моделей и чтение JSON-файлов."""

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
USERS_FILE = DATA_DIR / "users.json"
RATES_FILE = DATA_DIR / "rates.json"


def validate_user_id(user_id: int) -> int:
    """Проверка типа и значения идентификатора пользователя."""
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise TypeError("Идентификатор пользователя должен быть целым числом.")
    if user_id <= 0:
        raise ValueError("Идентификатор пользователя должен быть положительным.")
    return user_id


def normalize_currency_code(currency_code: str) -> str:
    """Проверка кода валюты и приведение к верхнему регистру."""
    if not isinstance(currency_code, str):
        raise TypeError("Код валюты должен быть строкой.")
    code = currency_code.strip().upper()
    if not code or not code.isascii() or not code.isalnum():
        raise ValueError("Код валюты должен содержать латинские буквы или цифры.")
    return code


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
    with USERS_FILE.open(encoding="utf-8") as file:
        users = json.load(file)
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
    with RATES_FILE.open(encoding="utf-8") as file:
        rates = json.load(file)
    if not isinstance(rates, dict):
        raise ValueError("Файл курсов должен содержать объект с кодами валют.")
    return rates


def get_exchange_rate(
    currency_code: str,
    base_currency: str = "USD",
    exchange_rates: Mapping[str, float] | None = None,
) -> float:
    """Расчёт курса валютной пары по курсам относительно USD."""
    code = normalize_currency_code(currency_code)
    base = normalize_currency_code(base_currency)
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
