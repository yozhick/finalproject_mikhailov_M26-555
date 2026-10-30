"""Операции пользователей и валютных портфелей."""

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import (
    DATA_DIR,
    RateQuote,
    RateService,
    RateUnavailableError,
    get_exchange_rate,
    normalize_currency_code,
    read_records,
    validate_amount,
    validate_number,
    write_json,
)


class JsonStorage:
    """Хранилище пользователей и портфелей."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        """Инициализация путей файлов данных."""
        self.users_file = Path(data_dir) / "users.json"
        self.portfolios_file = Path(data_dir) / "portfolios.json"

    def load_users(self) -> list[User]:
        """Чтение пользователей из хранилища."""
        try:
            users = [User.from_dict(record) for record in read_records(self.users_file)]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Некорректные данные пользователей") from error
        if len({user.user_id for user in users}) != len(users):
            raise ValueError("Идентификаторы пользователей повторяются")
        if len({user.username for user in users}) != len(users):
            raise ValueError("Имена пользователей повторяются")
        return users

    def save_users(self, users: list[User]) -> None:
        """Сохранение пользователей в хранилище."""
        write_json(self.users_file, [user.to_dict() for user in users])

    def load_portfolios(self) -> list[dict[str, Any]]:
        """Чтение записей портфелей из хранилища."""
        records = read_records(self.portfolios_file)
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
        records = self.load_portfolios()
        for index, record in enumerate(records):
            if record["user_id"] == portfolio.user_id:
                records[index] = portfolio.to_dict()
                break
        else:
            records.append(portfolio.to_dict())
        write_json(self.portfolios_file, records)


def _trade_values(
    currency_code: str,
    amount: float,
    exchange_rates: Mapping[str, float] | None,
) -> tuple[str, float, float]:
    """Проверка параметров операции и расчёт стоимости в USD."""
    code = normalize_currency_code(currency_code)
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
        new_balance = validate_number(
            (wallet.balance if wallet else 0) + amount, "Значение баланса"
        )
        if wallet is None:
            wallet = portfolio.add_currency(code)
        wallet.balance = new_balance
        return wallet
    if code == "USD":
        raise ValueError("Валюта покупки или продажи должна отличаться от USD.")
    usd_wallet = portfolio.get_wallet("USD")
    if cost > usd_wallet.balance:
        raise ValueError("Недостаточно средств в кошельке USD.")
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
        raise ValueError(f"Недостаточно средств в кошельке {code}.")
    usd_wallet = portfolio.wallets.get("USD")
    usd_balance = usd_wallet.balance if usd_wallet is not None else 0.0
    new_usd_balance = validate_number(usd_balance + cost, "Значение баланса")
    new_balance = validate_number(wallet.balance - amount, "Значение баланса")
    if usd_wallet is None:
        usd_wallet = portfolio.add_currency("USD")
    wallet.balance = new_balance
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

    def register(self, username: str, password: str) -> User:
        """Регистрация пользователя с пустым портфелем."""
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

    def show_portfolio(self, base_currency: str = "USD") -> dict[str, Any]:
        """Получение балансов и общей стоимости портфеля."""
        user = self._require_user()
        base = normalize_currency_code(base_currency)
        if base not in self.rates.known_currencies():
            raise ValueError(f"Неизвестная базовая валюта '{base}'")
        portfolio = self.storage.get_portfolio(user)
        rows = []
        for code, wallet in portfolio.wallets.items():
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
        user = self._require_user()
        code = normalize_currency_code(currency_code)
        amount = validate_amount(amount)
        portfolio = self.storage.get_portfolio(user)
        wallet = portfolio.wallets.get(code)
        before = wallet.balance if wallet is not None else 0.0
        if selling:
            if wallet is None:
                raise ValueError(
                    f"У вас нет кошелька '{code}'. Добавьте валюту: "
                    "она создаётся автоматически при первой покупке."
                )
            if amount > before:
                raise ValueError(
                    f"Недостаточно средств: доступно {before:.4f} {code}, "
                    f"требуется {amount:.4f} {code}"
                )
        try:
            quote = self.rates.get_rate(code, "USD")
        except RateUnavailableError:
            raise ValueError(f"Не удалось получить курс для {code}→USD") from None
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
        }

    def buy(self, currency_code: str, amount: float | str) -> dict[str, Any]:
        """Покупка указанного количества валюты."""
        return self._trade(currency_code, amount, selling=False)

    def sell(self, currency_code: str, amount: float | str) -> dict[str, Any]:
        """Продажа указанного количества валюты."""
        return self._trade(currency_code, amount, selling=True)

    def get_rate(self, from_currency: str, to_currency: str) -> RateQuote:
        """Получение курса валютной пары."""
        return self.rates.get_rate(from_currency, to_currency)
