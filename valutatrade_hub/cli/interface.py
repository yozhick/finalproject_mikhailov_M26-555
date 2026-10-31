"""Командный интерфейс управления валютным портфелем."""

import argparse
import shlex
import sys
from collections.abc import Sequence
from typing import Any

from prettytable import PrettyTable

from valutatrade_hub.core.currencies import FiatCurrency, get_currency, supported_codes
from valutatrade_hub.core.exceptions import ApiRequestError, CurrencyNotFoundError
from valutatrade_hub.core.usecases import TradingService


class CommandParser(argparse.ArgumentParser):
    """Разбор аргументов пользовательских команд."""

    def error(self, message: str) -> None:
        """Формирование ошибки аргументов команды."""
        raise ValueError(f"Некорректная команда: {message}")


def build_parser() -> CommandParser:
    """Создание парсера пользовательских команд."""
    parser = CommandParser(
        prog="valutatrade", description="Управление валютным портфелем."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("register", "login"):
        command = commands.add_parser(name)
        command.add_argument("--username", required=True)
        command.add_argument("--password", required=True)
    portfolio = commands.add_parser("show-portfolio")
    portfolio.add_argument("--base")
    for name in ("buy", "sell"):
        errors = (
            "неизвестная валюта; неположительное количество; "
            "недоступный источник курсов"
        )
        if name == "sell":
            errors += "; недостаточный баланс"
        command = commands.add_parser(name, epilog=f"Ошибки: {errors}.")
        command.add_argument("--currency", required=True)
        command.add_argument("--amount", required=True)
    rate = commands.add_parser(
        "get-rate",
        epilog=(
            "Ошибки: неизвестная валюта; недоступный источник курсов. "
            f"Поддерживаемые валюты: {', '.join(supported_codes())}."
        ),
    )
    rate.add_argument("--from", dest="from_currency", required=True)
    rate.add_argument("--to", dest="to_currency", required=True)
    commands.add_parser("help")
    commands.add_parser("exit")
    return parser


def print_help() -> None:
    """Вывод справки по пользовательским командам."""
    table = PrettyTable()
    table.field_names = ["Команда", "Назначение"]
    table.align = "l"
    table.add_rows(
        [
            [
                "register --username NAME --password PASSWORD",
                "Регистрация пользователя",
            ],
            ["login --username NAME --password PASSWORD", "Вход в систему"],
            ["show-portfolio [--base USD]", "Просмотр портфеля"],
            ["buy --currency CODE --amount NUMBER", "Покупка валюты"],
            ["sell --currency CODE --amount NUMBER", "Продажа валюты"],
            ["get-rate --from CODE --to CODE", "Просмотр курса валютной пары"],
            ["help", "Справка по командам"],
            ["exit", "Завершение работы"],
        ]
    )
    print(table)


def print_portfolio(report: dict[str, Any]) -> None:
    """Вывод балансов и общей стоимости портфеля."""
    base = report["base_currency"]
    value_precision = 2 if isinstance(get_currency(base), FiatCurrency) else 8
    print(f"Портфель пользователя '{report['username']}' (база: {base}):")
    if not report["wallets"]:
        print("Кошельки отсутствуют.")
    for wallet in report["wallets"]:
        code = wallet["currency_code"]
        precision = 2 if isinstance(get_currency(code), FiatCurrency) else 4
        print(
            f"- {code}: {wallet['balance']:.{precision}f} "
            f"→ {wallet['value']:.{value_precision}f} {base}"
        )
    print("-------------------------------")
    print(f"ИТОГО: {report['total']:,.{value_precision}f} {base}")


def print_trade(result: dict[str, Any], *, selling: bool) -> None:
    """Вывод результата покупки или продажи валюты."""
    code = result["currency_code"]
    operation = "Продажа" if selling else "Покупка"
    print(
        f"{operation} выполнена: {result['amount']:.4f} {code} "
        f"по курсу {result['rate']:.2f} USD/{code}"
    )
    print("Изменения в портфеле:")
    print(f"- {code}: было {result['before']:.4f} → стало {result['after']:.4f}")
    label = "Оценочная выручка" if selling else "Оценочная стоимость покупки"
    print(f"{label}: {result['total']:,.2f} USD")


def run_command(
    command: str | Sequence[str],
    service: TradingService,
    parser: CommandParser | None = None,
    *,
    exit_on_error: bool = False,
) -> bool:
    """Выполнение пользовательской команды."""
    parser = build_parser() if parser is None else parser
    try:
        if isinstance(command, str):
            try:
                tokens = shlex.split(command)
            except ValueError:
                raise ValueError("Некорректные кавычки в команде") from None
        else:
            tokens = list(command)
        if not tokens:
            return True
        args = parser.parse_args(tokens)
        if args.command == "exit":
            return False
        if args.command == "help":
            print_help()
        elif args.command == "register":
            user = service.register(args.username, args.password)
            print(
                f"Пользователь '{user.username}' зарегистрирован (id={user.user_id}). "
                f"Войдите: login --username {shlex.quote(user.username)} "
                "--password ****"
            )
        elif args.command == "login":
            user = service.login(args.username, args.password)
            print(f"Вы вошли как '{user.username}'")
        elif args.command == "show-portfolio":
            print_portfolio(service.show_portfolio(args.base))
        elif args.command == "buy":
            print_trade(service.buy(args.currency, args.amount), selling=False)
        elif args.command == "sell":
            print_trade(service.sell(args.currency, args.amount), selling=True)
        elif args.command == "get-rate":
            quote = service.get_rate(args.from_currency, args.to_currency)
            inverse = quote.inverse_rate
            print(
                f"Курс {quote.from_currency}→{quote.to_currency}: {quote.rate:.8f} "
                f"(обновлено: {quote.updated_at:%Y-%m-%d %H:%M:%S})"
            )
            print(
                f"Обратный курс {quote.to_currency}→{quote.from_currency}: "
                f"{inverse:.2f}"
            )
    except SystemExit as error:
        if error.code:
            raise
    except (TypeError, ValueError, OSError) as error:
        print(str(error))
        if isinstance(error, CurrencyNotFoundError):
            print(f"Поддерживаемые валюты: {', '.join(supported_codes())}")
        elif isinstance(error, ApiRequestError):
            print("Повторите попытку позже или проверьте подключение к сети.")
        if exit_on_error:
            raise SystemExit(1) from None
    return True


def main(argv: Sequence[str] | None = None) -> None:
    """Запуск командного интерфейса."""
    args = list(sys.argv[1:] if argv is None else argv)
    service = TradingService()
    parser = build_parser()
    if args:
        run_command(args, service, parser, exit_on_error=True)
        return
    while True:
        try:
            command = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if not run_command(command, service, parser):
            break
