"""Клиенты внешних источников валютных курсов."""

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import validate_number
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    """Общий интерфейс получения курсов внешнего источника."""

    source: str

    def __init__(self, config: ParserConfig | None = None) -> None:
        """Инициализация настроек запроса и метаданных ответа."""
        self.config = config if config is not None else ParserConfig()
        self.timestamp: datetime | None = None
        self.metadata: dict[str, dict[str, Any]] = {}

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Получение курсов в формате валютная пара — значение."""
        raise NotImplementedError

    def _request(self, url: str, **kwargs: Any) -> tuple[dict, dict]:
        """Отправка GET-запроса и проверка HTTP-ответа и JSON."""
        self.timestamp = None
        self.metadata = {}
        started = time.perf_counter()
        try:
            response = requests.get(
                url,
                timeout=self.config.REQUEST_TIMEOUT,
                allow_redirects=False,
                **kwargs,
            )
        except requests.exceptions.Timeout:
            raise ApiRequestError("Превышено время ожидания ответа") from None
        except requests.exceptions.RequestException:
            # Текст исключения requests может содержать URL с ключом доступа.
            raise ApiRequestError("Ошибка сети") from None
        with response:
            status = response.status_code
            if status != 200:
                reasons = {
                    401: "Неверный ключ доступа",
                    403: "Доступ к API запрещён",
                    429: "Превышен лимит запросов",
                }
                raise ApiRequestError(reasons.get(status, f"Ответ API: HTTP {status}"))
            try:
                data = response.json()
            except ValueError:
                raise ApiRequestError("Ответ API содержит некорректный JSON") from None
            if not isinstance(data, dict):
                raise ApiRequestError("Ответ API должен содержать объект")
            self.timestamp = datetime.now(timezone.utc)
            meta = {
                "request_ms": round((time.perf_counter() - started) * 1000),
                "status_code": status,
            }
            if response.headers.get("ETag"):
                meta["etag"] = response.headers["ETag"]
            return data, meta


class CoinGeckoClient(BaseApiClient):
    """Получение криптовалютных курсов CoinGecko."""

    source = "CoinGecko"

    def fetch_rates(self) -> dict[str, float]:
        """Получение курсов криптовалют к базовой валюте."""
        config = self.config
        if not config.CRYPTO_CURRENCIES:
            return {}
        ids = [config.CRYPTO_ID_MAP[code] for code in config.CRYPTO_CURRENCIES]
        data, meta = self._request(
            config.COINGECKO_URL,
            headers=(
                {"x-cg-demo-api-key": config.COINGECKO_API_KEY}
                if config.COINGECKO_API_KEY
                else {}
            ),
            params={
                "ids": ",".join(ids),
                "vs_currencies": config.BASE_CURRENCY.lower(),
                "include_last_updated_at": "true",
            },
        )
        rates = {}
        metadata = {}
        try:
            for code, coin_id in zip(config.CRYPTO_CURRENCIES, ids, strict=True):
                record = data[coin_id]
                rate = validate_number(
                    record[config.BASE_CURRENCY.lower()],
                    "Значение курса",
                    positive=True,
                )
                pair = f"{code}_{config.BASE_CURRENCY}"
                rates[pair] = rate
                metadata[pair] = {**meta, "raw_id": coin_id}
                if "last_updated_at" in record:
                    timestamp = validate_number(
                        record["last_updated_at"], "Время обновления", positive=True
                    )
                    metadata[pair]["source_updated_at"] = (
                        datetime.fromtimestamp(timestamp, timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            raise ApiRequestError("Некорректные курсы в ответе CoinGecko") from None
        self.metadata = metadata
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Получение фиатных курсов ExchangeRate-API."""

    source = "ExchangeRate-API"

    def fetch_rates(self) -> dict[str, float]:
        """Получение фиатных курсов с пересчётом направления пары."""
        config = self.config
        if not config.FIAT_CURRENCIES:
            return {}
        if not config.EXCHANGERATE_API_KEY:
            raise ApiRequestError("Не задан EXCHANGERATE_API_KEY")
        key = quote(config.EXCHANGERATE_API_KEY, safe="")
        url = (
            f"{config.EXCHANGERATE_API_URL.rstrip('/')}/{key}"
            f"/latest/{config.BASE_CURRENCY}"
        )
        data, meta = self._request(url)
        if data.get("result") != "success":
            reasons = {
                "invalid-key": "Неверный ключ доступа",
                "inactive-account": "Учётная запись API не активирована",
                "quota-reached": "Превышен лимит запросов",
                "unsupported-code": "Базовая валюта не поддерживается API",
                "malformed-request": "Некорректный запрос к API",
            }
            kind = data.get("error-type")
            reason = reasons.get(kind) if isinstance(kind, str) else None
            raise ApiRequestError(reason or "Ошибка ExchangeRate-API")
        rates = {}
        try:
            if data["base_code"] != config.BASE_CURRENCY:
                raise ValueError("Неверная базовая валюта ответа")
            values = data.get("conversion_rates", data.get("rates"))
            if "time_last_update_utc" in data:
                meta["source_updated_at"] = (
                    parsedate_to_datetime(data["time_last_update_utc"])
                    .astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
            for code in config.FIAT_CURRENCIES:
                value = validate_number(values[code], "Значение курса", positive=True)
                rates[f"{code}_{config.BASE_CURRENCY}"] = validate_number(
                    1 / value, "Значение обратного курса", positive=True
                )
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
            raise ApiRequestError(
                "Некорректные курсы в ответе ExchangeRate-API"
            ) from None
        self.metadata = {pair: dict(meta) for pair in rates}
        return rates
