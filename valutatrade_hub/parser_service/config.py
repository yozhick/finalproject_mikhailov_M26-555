"""Параметры запросов и файлов сервиса курсов."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.core.currencies import validate_currency_code
from valutatrade_hub.core.utils import validate_number
from valutatrade_hub.infra.settings import PROJECT_ROOT, SettingsLoader

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EXCHANGERATE_API_URL = "https://v6.exchangerate-api.com/v6"
FIAT_CURRENCIES = ("EUR", "GBP", "RUB")
CRYPTO_CURRENCIES = ("BTC", "ETH", "SOL")
CRYPTO_ID_MAP = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}


def _environment_value(name: str) -> str:
    """Чтение ключа из окружения или локального файла .env."""
    if name in os.environ:
        return os.environ[name].strip()
    path = PROJECT_ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key.strip() == name:
                return value.strip().strip("\"'")
    return ""


@dataclass
class ParserConfig:
    """Настройки источников курсов и периодического обновления."""

    EXCHANGERATE_API_KEY: str = field(
        default_factory=lambda: _environment_value("EXCHANGERATE_API_KEY"), repr=False
    )
    COINGECKO_API_KEY: str = field(
        default_factory=lambda: _environment_value("COINGECKO_API_KEY"), repr=False
    )
    COINGECKO_URL: str = COINGECKO_URL
    EXCHANGERATE_API_URL: str = EXCHANGERATE_API_URL
    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple[str, ...] = FIAT_CURRENCIES
    CRYPTO_CURRENCIES: tuple[str, ...] = CRYPTO_CURRENCIES
    CRYPTO_ID_MAP: dict[str, str] = field(default_factory=lambda: dict(CRYPTO_ID_MAP))
    RATES_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("RATES_FILE")
    )
    HISTORY_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("HISTORY_FILE")
    )
    REQUEST_TIMEOUT: float = 10
    UPDATE_INTERVAL: float = 3600

    def __post_init__(self) -> None:
        """Проверка кодов валют, путей и временных параметров."""
        self.BASE_CURRENCY = validate_currency_code(self.BASE_CURRENCY)
        for name in ("FIAT_CURRENCIES", "CRYPTO_CURRENCIES"):
            codes = tuple(validate_currency_code(code) for code in getattr(self, name))
            if len(set(codes)) != len(codes):
                raise ValueError(f"{name} содержит повторяющиеся коды")
            setattr(self, name, codes)
        for code in self.CRYPTO_CURRENCIES:
            coin_id = self.CRYPTO_ID_MAP.get(code)
            if not isinstance(coin_id, str) or not coin_id.strip():
                raise ValueError(f"Не задан ID CoinGecko для {code}")
        self.REQUEST_TIMEOUT = validate_number(
            self.REQUEST_TIMEOUT, "Время ожидания ответа", positive=True
        )
        self.UPDATE_INTERVAL = validate_number(
            self.UPDATE_INTERVAL, "Интервал обновления", positive=True
        )
        self.RATES_FILE_PATH = Path(self.RATES_FILE_PATH).resolve()
        self.HISTORY_FILE_PATH = Path(self.HISTORY_FILE_PATH).resolve()
        if self.RATES_FILE_PATH == self.HISTORY_FILE_PATH:
            raise ValueError("Пути кеша и истории должны различаться")
