"""Последовательное обновление курсов внешних источников."""

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from valutatrade_hub.core.currencies import validate_currency_code
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import validate_number
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage


class RatesUpdater:
    """Получение курсов, ведение журнала и сохранение результатов."""

    def __init__(
        self,
        clients: Sequence[BaseApiClient] | None = None,
        storage: RatesStorage | None = None,
        *,
        config: ParserConfig | None = None,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        """Инициализация клиентов, хранилища и вывода состояния обновления."""
        self.config = (
            config
            if config is not None
            else storage.config
            if storage is not None
            else ParserConfig()
        )
        self.clients = (
            [CoinGeckoClient(self.config), ExchangeRateApiClient(self.config)]
            if clients is None
            else list(clients)
        )
        self.storage = storage if storage is not None else RatesStorage(self.config)
        self.notify = notify
        self.logger = configure_logging(name="parser")

    def _report(self, message: str, *, error: bool = False) -> None:
        """Запись этапа обновления в журнал и вывод состояния."""
        try:
            if error:
                self.logger.error(message)
            else:
                self.logger.info(message)
        except (OSError, ValueError):
            pass
        if self.notify is not None:
            self.notify(f"{'ERROR' if error else 'INFO'}: {message}")

    @staticmethod
    def _records(client: BaseApiClient, rates: dict) -> list[dict[str, Any]]:
        """Проверка курсов клиента и формирование записей измерений."""
        if not isinstance(rates, dict) or not rates:
            raise ApiRequestError("Источник не вернул курсы")
        stamp = (client.timestamp or datetime.now(timezone.utc)).isoformat()
        records = []
        try:
            for pair, value in rates.items():
                code, base = pair.split("_")
                code = validate_currency_code(code)
                base = validate_currency_code(base)
                records.append(
                    {
                        "from_currency": code,
                        "to_currency": base,
                        "rate": validate_number(value, "Значение курса", positive=True),
                        "timestamp": stamp,
                        "source": client.source,
                        "meta": client.metadata.get(pair, {}),
                    }
                )
        except (AttributeError, TypeError, ValueError):
            raise ApiRequestError("Источник вернул некорректные курсы") from None
        return records

    def run_update(self, source: str | None = None) -> dict[str, Any]:
        """Обновление кеша и истории с продолжением после ошибки источника."""
        names = {"coingecko": "CoinGecko", "exchangerate": "ExchangeRate-API"}
        if source is not None and source not in names:
            raise ValueError("Неизвестный источник курсов")
        clients = [
            client
            for client in self.clients
            if source is None or client.source == names[source]
        ]
        if not clients:
            raise ValueError("Не заданы клиенты выбранного источника")
        self._report("Starting rates update...")
        measurements = []
        errors = {}
        for client in clients:
            try:
                rates = client.fetch_rates()
                measurements.extend(self._records(client, rates))
            except ApiRequestError as error:
                errors[client.source] = error.reason
                self._report(
                    f"Failed to fetch from {client.source}: {error.reason}.", error=True
                )
            else:
                self._report(
                    f"Fetching from {client.source}... OK ({len(rates)} rates)"
                )
        if not measurements:
            raise ApiRequestError("Не удалось получить курсы ни из одного источника")
        self._report(
            f"Writing {len(measurements)} rates "
            f"to {self.storage.config.RATES_FILE_PATH}..."
        )
        try:
            result = self.storage.save(measurements)
        except (OSError, KeyError, TypeError, ValueError) as error:
            self._report("Failed to save rates.", error=True)
            raise ValueError("Не удалось сохранить курсы в JSON-хранилище") from error
        self._report(f"Rates update finished: {result['updated']} rates updated.")
        return {**result, "errors": errors}
