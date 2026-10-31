"""Регистрация результатов пользовательских операций."""

import inspect
import math
from collections.abc import Callable
from functools import wraps
from typing import Any

from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging


def _number(value: Any, precision: int) -> str:
    """Форматирование числового значения для журнала."""
    try:
        if isinstance(value, bool):
            return repr(value)
        number = float(value)
        if math.isfinite(number):
            return f"{number:.{precision}f}"
    except (TypeError, ValueError, OverflowError):
        pass
    return repr(value)


def _message(
    action: str,
    arguments: dict[str, Any],
    result: Any,
    error: Exception | None,
    verbose: bool,
) -> str:
    """Формирование записи о результате операции."""
    owner = arguments.get("self")
    user = getattr(owner, "current_user", None)
    username = arguments.get("username", getattr(user, "username", None))
    username = getattr(result, "username", username)
    parts = [action]
    if username is not None:
        parts.append(f"user={username!r}")
    else:
        parts.append(
            f"user_id={arguments.get('user_id', getattr(user, 'user_id', None))!r}"
        )
    values = result if isinstance(result, dict) else {}
    code = values.get("currency_code", arguments.get("currency_code"))
    if code is not None:
        parts.append(f"currency={str(code).strip().upper()!r}")
    amount = values.get("amount", arguments.get("amount"))
    if amount is not None:
        parts.append(f"amount={_number(amount, 4)}")
    if "rate" in values:
        parts.append(f"rate={_number(values['rate'], 2)}")
    if code is not None:
        parts.append(f"base={values.get('base_currency', 'USD')!r}")
    parts.append("result=OK" if error is None else "result=ERROR")
    if error is not None:
        parts.extend(
            [
                f"error_type={type(error).__name__}",
                f"error_message={str(error)!r}",
            ]
        )
    if verbose:
        for key in ("before", "after"):
            if key in values:
                parts.append(f"{key}={_number(values[key], 4)}")
    return " ".join(parts)


def log_action(
    func: Callable | str | None = None,
    *,
    action: str | None = None,
    verbose: bool = False,
) -> Callable:
    """Добавление записи о результате операции в журнал."""
    if isinstance(func, str):
        action = func if action is None else action
        func = None

    def decorate(method: Callable) -> Callable:
        """Создание функции с регистрацией результата операции."""
        signature = inspect.signature(method)
        action_name = (action or method.__name__).upper()

        @wraps(method)
        def wrapper(*args, **kwargs):
            """Выполнение операции с записью результата в журнал."""
            logger = configure_logging()
            try:
                arguments = dict(signature.bind_partial(*args, **kwargs).arguments)
            except TypeError:
                arguments = {}
            include_context = verbose or SettingsLoader().get("LOG_VERBOSE", False)
            try:
                result = method(*args, **kwargs)
            except Exception as error:
                logger.info(
                    _message(action_name, arguments, None, error, include_context)
                )
                raise
            logger.info(_message(action_name, arguments, result, None, include_context))
            return result

        return wrapper

    return decorate if func is None else decorate(func)
