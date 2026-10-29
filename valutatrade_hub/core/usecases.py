"""Операции покупки и продажи валюты с расчётами через USD-кошелёк."""

from collections.abc import Mapping

from valutatrade_hub.core.models import Portfolio, Wallet
from valutatrade_hub.core.utils import (
    get_exchange_rate,
    normalize_currency_code,
    validate_number,
)


def _trade_values(
    currency_code: str,
    amount: float,
    exchange_rates: Mapping[str, float] | None,
) -> tuple[str, float, float]:
    """Проверка параметров операции и расчёт стоимости в USD."""
    code = normalize_currency_code(currency_code)
    if code == "USD":
        raise ValueError("Валюта покупки или продажи должна отличаться от USD.")
    amount = validate_number(amount, "Значение суммы", positive=True)
    rate = get_exchange_rate(code, "USD", exchange_rates)
    cost = validate_number(amount * rate, "Значение стоимости", positive=True)
    return code, amount, cost


def buy_currency(
    portfolio: Portfolio,
    currency_code: str,
    amount: float,
    exchange_rates: Mapping[str, float] | None = None,
) -> Wallet:
    """Покупка валюты со списанием её стоимости с кошелька USD."""
    code, amount, cost = _trade_values(currency_code, amount, exchange_rates)
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
) -> Wallet:
    """Продажа валюты с зачислением её стоимости на кошелёк USD."""
    code, amount, cost = _trade_values(currency_code, amount, exchange_rates)
    wallet = portfolio.get_wallet(code)
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
