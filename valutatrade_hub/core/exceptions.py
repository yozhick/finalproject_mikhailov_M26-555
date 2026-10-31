"""Исключения операций с валютами и кошельками."""


class InsufficientFundsError(ValueError):
    """Недостаточный баланс кошелька."""

    def __init__(self, available: float, required: float, code: str) -> None:
        """Формирование сообщения о недостатке средств."""
        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {available:.4f} {code}, "
            f"требуется {required:.4f} {code}"
        )


class CurrencyNotFoundError(ValueError):
    """Отсутствие валюты в реестре."""

    def __init__(self, code: str) -> None:
        """Формирование сообщения о неизвестной валюте."""
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(ValueError):
    """Ошибка получения курса из внешнего источника."""

    def __init__(self, reason: str) -> None:
        """Формирование сообщения об ошибке источника курсов."""
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")
