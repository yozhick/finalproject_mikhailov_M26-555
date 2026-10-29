"""Командный интерфейс демонстрации валютного портфеля."""

import argparse
import time
from collections.abc import Sequence

from prettytable import PrettyTable

from valutatrade_hub.core.models import Portfolio, User, Wallet


def main(argv: Sequence[str] | None = None) -> None:
    """Обработка аргументов и вывод демонстрационного портфеля."""
    parser = argparse.ArgumentParser(
        description="Демонстрация основных классов ValutaTrade Hub.",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="Справка по аргументам.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Демонстрационный пользователь и портфель с учебными курсами.",
    )
    parser.add_argument(
        "--base-currency",
        default="USD",
        help="Базовая валюта расчёта общей стоимости (по умолчанию USD).",
    )
    args = parser.parse_args(argv)
    if not args.demo:
        parser.print_help()
        return
    started = time.perf_counter()
    user = User.create(1, "alice", "demo-password")
    portfolio = Portfolio(
        user.user_id,
        {
            "USD": Wallet("USD", 1500),
            "BTC": Wallet("BTC", 0.05),
            "EUR": Wallet("EUR", 200),
        },
        user=user,
    )
    try:
        total = portfolio.get_total_value(args.base_currency)
    except (TypeError, ValueError, OSError) as error:
        parser.error(str(error))
    table = PrettyTable()
    table.field_names = ["Валюта", "Баланс"]
    table.align["Валюта"] = "l"
    table.align["Баланс"] = "r"
    table.add_rows(
        [[code, f"{wallet.balance:.10g}"] for code, wallet in portfolio.wallets.items()]
    )
    info = user.get_user_info()
    print(f"Пользователь: {info['username']} (ID: {info['user_id']})")
    print(f"Дата регистрации: {info['registration_date']}")
    print(table)
    base_currency = args.base_currency.strip().upper()
    print(f"Общая стоимость ({base_currency}): {total:.10g}")
    print("Курсы: фиксированные учебные значения.")
    print(f"Время выполнения демонстрации: {time.perf_counter() - started:.6f} с")
