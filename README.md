# ValutaTrade Hub

## Настройка API-ключей

Проект читает API-ключи из переменных окружения или файла `.env` в корне
проекта, рядом с `pyproject.toml`. Переменные окружения имеют приоритет
над значениями из `.env`.

| Переменная | Назначение |
| --- | --- |
| `EXCHANGERATE_API_KEY` | Обязательный ключ для получения фиатных курсов ExchangeRate-API. |
| `COINGECKO_API_KEY` | Необязательный ключ CoinGecko. При отсутствии ключа запрос выполняется без него. |

Пример содержимого `.env` с условными значениями ключей:

```dotenv
EXCHANGERATE_API_KEY=exchange_rate_api_key
# COINGECKO_API_KEY=coingecko_api_key
```

Альтернативный способ задания ключа в PowerShell:

```powershell
$env:EXCHANGERATE_API_KEY = "exchange_rate_api_key"
```
