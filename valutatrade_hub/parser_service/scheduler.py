"""Периодический запуск обновления валютных курсов."""

import argparse
from threading import Event

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import validate_number
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import RatesUpdater


class RatesScheduler:
    """Последовательное обновление курсов с заданным интервалом."""

    def __init__(self, updater: RatesUpdater, interval: float | None = None) -> None:
        """Инициализация обновления, интервала и признака остановки."""
        self.updater = updater
        self.interval = validate_number(
            updater.config.UPDATE_INTERVAL if interval is None else interval,
            "Интервал обновления",
            positive=True,
        )
        self.stopped = Event()

    def stop(self) -> None:
        """Остановка ожидания следующего обновления."""
        self.stopped.set()

    def run(self, source: str | None = None) -> None:
        """Повторное обновление до установки признака остановки."""
        while not self.stopped.is_set():
            try:
                self.updater.run_update(source)
            except (ApiRequestError, OSError, ValueError) as error:
                self.updater.logger.error("Scheduled update failed: %s", error)
            self.stopped.wait(self.interval)


def main() -> None:
    """Запуск сервиса с параметрами интервала и источника."""
    parser = argparse.ArgumentParser(description="Периодическое обновление курсов.")
    parser.add_argument("--interval", type=float)
    parser.add_argument("--source", choices=("coingecko", "exchangerate"))
    args = parser.parse_args()
    config = ParserConfig()
    scheduler = RatesScheduler(RatesUpdater(config=config, notify=print), args.interval)
    try:
        scheduler.run(args.source)
    except KeyboardInterrupt:
        scheduler.stop()


if __name__ == "__main__":
    main()
