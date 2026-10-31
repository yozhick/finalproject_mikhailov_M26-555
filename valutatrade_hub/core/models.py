"""Модели пользователя, кошелька и валютного портфеля."""

import hashlib
import hmac
import math
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from valutatrade_hub.core.currencies import get_currency, validate_currency_code
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import (
    get_exchange_rate,
    load_exchange_rates,
    load_user_data,
    validate_number,
    validate_user_id,
)


class User:
    """Пользователь системы."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        """Инициализация пользователя с заданными данными."""
        self._user_id = validate_user_id(user_id)
        self.username = username
        for value, name in (
            (hashed_password, "Значение хеша пароля"),
            (salt, "Значение соли"),
        ):
            if not isinstance(value, str):
                raise TypeError(f"{name} должно быть строкой.")
            if not value:
                raise ValueError(f"{name} не может быть пустым.")
        if not isinstance(registration_date, datetime):
            raise TypeError("Дата регистрации должна иметь тип datetime.")
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> "User":
        """Создание пользователя с хешем пароля и случайной солью."""
        cls._validate_password(password)
        salt = secrets.token_hex(16)
        return cls(
            user_id,
            username,
            cls._hash_password(password, salt),
            salt,
            datetime.now(timezone.utc),
        )

    @staticmethod
    def _validate_password(password: str) -> None:
        """Проверка типа и длины пароля."""
        if not isinstance(password, str):
            raise TypeError("Пароль должен быть строкой.")
        if len(password) < 4:
            raise ValueError("Пароль должен содержать не менее четырёх символов.")

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        """Вычисление хеша пароля с солью по алгоритму SHA-256."""
        return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

    @property
    def user_id(self) -> int:
        """Получение идентификатора пользователя."""
        return self._user_id

    @property
    def username(self) -> str:
        """Получение имени пользователя."""
        return self._username

    @username.setter
    def username(self, username: str) -> None:
        """Изменение имени пользователя."""
        if not isinstance(username, str):
            raise TypeError("Имя пользователя должно быть строкой.")
        if not username.strip():
            raise ValueError("Имя пользователя не может быть пустым.")
        self._username = username.strip()

    @property
    def hashed_password(self) -> str:
        """Получение хеша пароля."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Получение соли пользователя."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Получение даты и времени регистрации пользователя."""
        return self._registration_date

    def get_user_info(self) -> dict[str, Any]:
        """Получение данных пользователя без хеша пароля и соли."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "registration_date": self.registration_date.isoformat(),
        }

    def change_password(self, new_password: str) -> None:
        """Изменение пароля пользователя."""
        self._validate_password(new_password)
        self._hashed_password = self._hash_password(new_password, self.salt)

    def verify_password(self, password: str) -> bool:
        """Проверка пароля по сохранённому хешу."""
        if not isinstance(password, str):
            raise TypeError("Пароль должен быть строкой.")
        candidate = self._hash_password(password, self.salt)
        return hmac.compare_digest(
            candidate.encode("utf-8"), self.hashed_password.encode("utf-8")
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразование данных пользователя в словарь."""
        return {
            **self.get_user_info(),
            "hashed_password": self.hashed_password,
            "salt": self.salt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        """Создание пользователя из словаря."""
        return cls(
            user_id=data["user_id"],
            username=data["username"],
            hashed_password=data["hashed_password"],
            salt=data["salt"],
            registration_date=datetime.fromisoformat(data["registration_date"]),
        )


class Wallet:
    """Кошелёк с балансом в одной валюте."""

    def __init__(self, currency_code: str, balance: float = 0.0) -> None:
        """Инициализация кошелька с заданной валютой и балансом."""
        self._currency_code = get_currency(currency_code).code
        self.balance = balance

    @property
    def currency_code(self) -> str:
        """Получение кода валюты кошелька."""
        return self._currency_code

    @property
    def balance(self) -> float:
        """Получение баланса кошелька."""
        return self._balance

    @balance.setter
    def balance(self, balance: float) -> None:
        """Изменение баланса кошелька."""
        self._balance = validate_number(balance, "Значение баланса")

    def deposit(self, amount: float) -> None:
        """Увеличение баланса на положительную сумму."""
        amount = validate_number(amount, "Значение суммы", positive=True)
        self.balance = self.balance + amount

    def withdraw(self, amount: float) -> None:
        """Снятие средств с проверкой доступного баланса."""
        amount = validate_number(amount, "Значение суммы", positive=True)
        if amount > self.balance:
            raise InsufficientFundsError(self.balance, amount, self.currency_code)
        self.balance = self.balance - amount

    def get_balance_info(self) -> dict[str, str | float]:
        """Получение кода валюты и баланса кошелька."""
        return {"currency_code": self.currency_code, "balance": self.balance}


class Portfolio:
    """Валютный портфель пользователя."""

    def __init__(
        self,
        user_id: int,
        wallets: dict[str, Wallet] | None = None,
        *,
        user: User | None = None,
    ) -> None:
        """Инициализация портфеля пользователя с заданными кошельками."""
        self._user_id = validate_user_id(user_id)
        if user is not None:
            if not isinstance(user, User):
                raise TypeError("Владелец портфеля должен иметь тип User.")
            if user.user_id != self.user_id:
                raise ValueError(
                    "Идентификаторы пользователя и владельца не совпадают."
                )
        self._user = user
        self._wallets: dict[str, Wallet] = {}
        if wallets is not None:
            if not isinstance(wallets, dict):
                raise TypeError("Кошельки должны быть представлены словарём.")
            for code, wallet in wallets.items():
                code = validate_currency_code(code)
                if not isinstance(wallet, Wallet):
                    raise TypeError(
                        "Значения словаря кошельков должны иметь тип Wallet."
                    )
                if code != wallet.currency_code:
                    raise ValueError("Ключ словаря не совпадает с валютой кошелька.")
                if code in self._wallets:
                    raise ValueError(f"Кошелёк {code} повторяется.")
                self._wallets[code] = wallet

    @property
    def user_id(self) -> int:
        """Получение идентификатора владельца портфеля."""
        return self._user_id

    @property
    def user(self) -> User:
        """Получение пользователя, которому принадлежит портфель."""
        if self._user is None:
            self._user = User.from_dict(load_user_data(self.user_id))
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Получение копии словаря кошельков."""
        return self._wallets.copy()

    def add_currency(self, currency_code: str) -> Wallet:
        """Создание кошелька для валюты, отсутствующей в портфеле."""
        code = get_currency(currency_code).code
        if code in self._wallets:
            raise ValueError(f"Кошелёк {code} уже существует.")
        wallet = Wallet(code)
        self._wallets[code] = wallet
        return wallet

    def get_wallet(self, currency_code: str) -> Wallet:
        """Получение кошелька по коду валюты."""
        code = validate_currency_code(currency_code)
        if code not in self._wallets:
            raise ValueError(f"Кошелёк {code} отсутствует в портфеле.")
        return self._wallets[code]

    def get_total_value(
        self,
        base_currency: str = "USD",
        exchange_rates: Mapping[str, float] | None = None,
    ) -> float:
        """Расчёт общей стоимости портфеля в базовой валюте."""
        base = validate_currency_code(base_currency)
        if not any(wallet.balance for wallet in self._wallets.values()):
            return 0.0
        rates = load_exchange_rates() if exchange_rates is None else exchange_rates
        values = [
            wallet.balance * get_exchange_rate(code, base, rates)
            for code, wallet in self._wallets.items()
            if wallet.balance
        ]
        try:
            total = math.fsum(values)
        except OverflowError:
            raise ValueError(
                "Общая стоимость выходит за допустимый диапазон."
            ) from None
        return validate_number(total, "Значение общей стоимости")

    def to_dict(self) -> dict[str, Any]:
        """Преобразование данных портфеля в словарь."""
        return {
            "user_id": self.user_id,
            "wallets": {
                code: {"balance": wallet.balance}
                for code, wallet in self._wallets.items()
            },
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, user: User | None = None
    ) -> "Portfolio":
        """Создание портфеля из словаря."""
        return cls(
            user_id=data["user_id"],
            wallets={
                code: Wallet(code, wallet["balance"])
                for code, wallet in data["wallets"].items()
            },
            user=user,
        )
