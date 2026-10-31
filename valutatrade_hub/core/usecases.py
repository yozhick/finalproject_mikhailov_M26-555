"""Операции пользователей и валютных портфелей."""

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from valutatrade_hub.core.currencies import get_currency, validate_currency_code
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import (
    RateQuote,
    RateService,
    get_exchange_rate,
    validate_amount,
    validate_number,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


class JsonStorage:
    """Хранилище пользователей и портфелей."""

    def __init__(self, data_dir: Path | None = None) -> None:
        """Инициализация путей файлов данных."""
        self._data_dir = None if data_dir is None else Path(data_dir).resolve()
        self._database = DatabaseManager()

    @property
    def database(self) -> DatabaseManager:
        """Получение общего экземпляра доступа к данным."""
        return self._database

    @property
    def users_file(self) -> Path:
        """Получение пути файла пользователей."""
        return (
            self._database.path("users")
            if self._data_dir is None
            else self._data_dir / "users.json"
        )

    @property
    def portfolios_file(self) -> Path:
        """Получение пути файла портфелей."""
        return (
            self._database.path("portfolios")
            if self._data_dir is None
            else self._data_dir / "portfolios.json"
        )

    def _records(self, path: Path) -> list[dict[str, Any]]:
        """Чтение списка записей из хранилища."""
        records = self._database.read(path, [])
        if not isinstance(records, list) or any(
            not isinstance(item, dict) for item in records
        ):
            raise ValueError(f"Файл {path.name} должен содержать список объектов")
        return records

    def load_users(self) -> list[User]:
        """Чтение пользователей из хранилища."""
        try:
            users = [
                User.from_dict(record) for record in self._records(self.users_file)
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Некорректные данные пользователей") from error
        if len({user.user_id for user in users}) != len(users):
            raise ValueError("Идентификаторы пользователей повторяются")
        if len({user.username for user in users}) != len(users):
            raise ValueError("Имена пользователей повторяются")
        return users

    def save_users(self, users: list[User]) -> None:
        """Сохранение пользователей в хранилище."""
        self._database.write(self.users_file, [user.to_dict() for user in users])

    def load_portfolios(self) -> list[dict[str, Any]]:
        """Чтение записей портфелей из хранилища."""
        records = self._records(self.portfolios_file)
        try:
            portfolios = [Portfolio.from_dict(record) for record in records]
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise ValueError("Некорректные данные портфелей") from error
        if len({portfolio.user_id for portfolio in portfolios}) != len(portfolios):
            raise ValueError("Идентификаторы владельцев портфелей повторяются")
        return records

    def get_portfolio(self, user: User) -> Portfolio:
        """Получение портфеля пользователя из хранилища."""
        for record in self.load_portfolios():
            if record["user_id"] == user.user_id:
                return Portfolio.from_dict(record, user=user)
        raise ValueError(f"Портфель пользователя '{user.username}' не найден")

    def save_portfolio(self, portfolio: Portfolio) -> None:
        """Сохранение портфеля пользователя в хранилище."""
        with self._database.locked():
            records = self.load_portfolios()
            for index, record in enumerate(records):
                if record["user_id"] == portfolio.user_id:
                    records[index] = portfolio.to_dict()
                    break
            else:
                records.append(portfolio.to_dict())
            self._database.write(self.portfolios_file, records)


def _trade_values(
    currency_code: str,
    amount: float,
    exchange_rates: Mapping[str, float] | None,
) -> tuple[str, float, float]:
    """Проверка параметров операции и расчёт стоимости в USD."""
    code = validate_currency_code(currency_code)
    amount = validate_number(amount, "Значение суммы", positive=True)
    rate = get_exchange_rate(code, "USD", exchange_rates)
    cost = validate_number(amount * rate, "Значение стоимости", positive=True)
    return code, amount, cost


def buy_currency(
    portfolio: Portfolio,
    currency_code: str,
    amount: float,
    exchange_rates: Mapping[str, float] | None = None,
    *,
    debit_usd: bool = True,
) -> Wallet:
    """Покупка валюты с изменением балансов кошельков."""
    code, amount, cost = _trade_values(currency_code, amount, exchange_rates)
    if not debit_usd:
        wallet = portfolio.wallets.get(code)
        validate_number((wallet.balance if wallet else 0) + amount, "Значение баланса")
        if wallet is None:
            wallet = portfolio.add_currency(code)
        wallet.deposit(amount)
        return wallet
    if code == "USD":
        raise ValueError("Валюта покупки или продажи должна отличаться от USD.")
    usd_wallet = portfolio.get_wallet("USD")
    if cost > usd_wallet.balance:
        raise InsufficientFundsError(usd_wallet.balance, cost, "USD")
    wallet = portfolio.wallets.get(code)
    balance = wallet.balance if wallet is not None else 0.0
    new_balance = validate_number(balance + amount, "Значение баланса")
    new_usd_balance = validate_number(usd_wallet.balance - cost, "Значение баланса")
    if wallet is None:
        wallet = portfolio.add_currency(code)
    usd_wallet.balance = new_usd_balance
    wallet.balance = new_balance
    return wallet


def sell_currency(
    portfolio: Portfolio,
    currency_code: str,
    amount: float,
    exchange_rates: Mapping[str, float] | None = None,
    *,
    credit_usd: bool = True,
) -> Wallet:
    """Продажа валюты с изменением балансов кошельков."""
    code, amount, cost = _trade_values(currency_code, amount, exchange_rates)
    if code == "USD" and credit_usd:
        raise ValueError("Валюта покупки или продажи должна отличаться от USD.")
    wallet = portfolio.get_wallet(code)
    if not credit_usd:
        wallet.withdraw(amount)
        return wallet
    if amount > wallet.balance:
        raise InsufficientFundsError(wallet.balance, amount, code)
    usd_wallet = portfolio.wallets.get("USD")
    usd_balance = usd_wallet.balance if usd_wallet is not None else 0.0
    new_usd_balance = validate_number(usd_balance + cost, "Значение баланса")
    validate_number(wallet.balance - amount, "Значение баланса")
    if usd_wallet is None:
        usd_wallet = portfolio.add_currency("USD")
    wallet.withdraw(amount)
    usd_wallet.balance = new_usd_balance
    return wallet


class TradingService:
    """Операции учётной записи и валютного портфеля."""

    def __init__(
        self, storage: JsonStorage | None = None, rates: RateService | None = None
    ) -> None:
        """Инициализация хранилища, сервиса курсов и сессии."""
        self.storage = storage if storage is not None else JsonStorage()
        self.rates = rates if rates is not None else RateService()
        self._settings = SettingsLoader()
        self._current_user: User | None = None

    @property
    def current_user(self) -> User | None:
        """Получение пользователя текущей сессии."""
        return self._current_user

    def _require_user(self) -> User:
        """Проверка наличия пользовательской сессии."""
        if self.current_user is None:
            raise ValueError("Сначала выполните login")
        return self.current_user

    @log_action(action="REGISTER")
    def register(self, username: str, password: str) -> User:
        """Регистрация пользователя с пустым портфелем."""
        with self.storage.database.locked():
            if not isinstance(username, str) or not username.strip():
                raise ValueError("Имя пользователя не может быть пустым")
            username = username.strip()
            users = self.storage.load_users()
            if any(user.username == username for user in users):
                raise ValueError(f"Имя пользователя '{username}' уже занято")
            if not isinstance(password, str):
                raise TypeError("Пароль должен быть строкой")
            if len(password) < 4:
                raise ValueError("Пароль должен быть не короче 4 символов")
            self.storage.load_portfolios()
            user_id = max((user.user_id for user in users), default=0) + 1
            user = User.create(user_id, username, password)
            self.storage.save_users([*users, user])
            try:
                self.storage.save_portfolio(Portfolio(user_id, user=user))
            except (OSError, ValueError):
                self.storage.save_users(users)
                raise
            return user

    @log_action(action="LOGIN")
    def login(self, username: str, password: str) -> User:
        """Проверка учётных данных и открытие сессии пользователя."""
        self._current_user = None
        if not isinstance(username, str):
            raise TypeError("Имя пользователя должно быть строкой")
        username = username.strip()
        user = next(
            (user for user in self.storage.load_users() if user.username == username),
            None,
        )
        if user is None:
            raise ValueError(f"Пользователь '{username}' не найден")
        if not user.verify_password(password):
            raise ValueError("Неверный пароль")
        self._current_user = user
        return user

    def show_portfolio(self, base_currency: str | None = None) -> dict[str, Any]:
        """Получение балансов и общей стоимости портфеля."""
        user = self._require_user()
        base = get_currency(
            self._settings.get("DEFAULT_BASE_CURRENCY")
            if base_currency is None
            else base_currency
        ).code
        portfolio = self.storage.get_portfolio(user)
        rows = []
        for code, wallet in portfolio.wallets.items():
            get_currency(code)
            value = 0.0
            if wallet.balance:
                quote = self.rates.get_rate(code, base)
                value = validate_number(
                    wallet.balance * quote.rate, "Значение стоимости"
                )
            rows.append(
                {"currency_code": code, "balance": wallet.balance, "value": value}
            )
        try:
            total = math.fsum(row["value"] for row in rows)
        except OverflowError:
            raise ValueError("Общая стоимость выходит за допустимый диапазон") from None
        return {
            "username": user.username,
            "base_currency": base,
            "wallets": rows,
            "total": validate_number(total, "Значение общей стоимости"),
        }

    def _trade(
        self, currency_code: str, amount: float | str, *, selling: bool
    ) -> dict[str, Any]:
        """Выполнение покупки или продажи валюты с сохранением портфеля."""
        with self.storage.database.locked():
            user = self._require_user()
            code = get_currency(currency_code).code
            amount = validate_amount(amount)
            portfolio = self.storage.get_portfolio(user)
            wallet = portfolio.wallets.get(code)
            before = wallet.balance if wallet is not None else 0.0
            if selling:
                if wallet is None:
                    raise InsufficientFundsError(0.0, amount, code)
                if amount > before:
                    raise InsufficientFundsError(before, amount, code)
            quote = self.rates.get_rate(code, "USD")
            rates = {"USD": 1.0, code: quote.rate}
            if selling:
                wallet = sell_currency(
                    portfolio, code, amount, rates, credit_usd=code != "USD"
                )
            else:
                wallet = buy_currency(portfolio, code, amount, rates, debit_usd=False)
            total = validate_number(
                amount * quote.rate, "Значение стоимости", positive=True
            )
            self.storage.save_portfolio(portfolio)
            return {
                "currency_code": code,
                "amount": amount,
                "rate": quote.rate,
                "before": before,
                "after": wallet.balance,
                "total": total,
                "base_currency": "USD",
            }

    @log_action(action="BUY")
    def buy(self, currency_code: str, amount: float | str) -> dict[str, Any]:
        """Покупка указанного количества валюты."""
        return self._trade(currency_code, amount, selling=False)

    @log_action(action="SELL")
    def sell(self, currency_code: str, amount: float | str) -> dict[str, Any]:
        """Продажа указанного количества валюты."""
        return self._trade(currency_code, amount, selling=True)

    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Получение курса валютной пары."""
        code = get_currency(from_currency).code
        base = get_currency(to_currency).code
        return self.rates.get_rate(code, base)
