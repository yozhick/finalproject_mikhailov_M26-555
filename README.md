# ValutaTrade Hub

Консольное приложение для управления виртуальным портфелем фиатных валют
и криптовалют: регистрация, вход, покупка, продажа, просмотр балансов и курсов.

При регистрации портфель пуст. Покупка эмулирует оплату реальными деньгами
вне приложения: валюта зачисляется без проверки остатка и списания средств
с USD-кошелька. Продажа валюты зачисляет выручку в USD, а продажа самого USD
эмулирует вывод денег. При продаже проверяется достаточность баланса.

## Установка и запуск

Необходимы Python 3.12+ и uv. Команды выполняются из корня проекта:

```powershell
uv sync --locked
uv run valutatrade
```

## API-ключи

Ключи задаются переменными окружения или в `.env` рядом с `pyproject.toml`.
Окружение имеет приоритет. Пример файла с условными значениями:

```dotenv
EXCHANGERATE_API_KEY=exchange_rate_api_key
# COINGECKO_API_KEY=coingecko_api_key
```

Ключ ExchangeRate-API обязателен для фиатных курсов; ключ CoinGecko необязателен.

## Пример работы

Команды вводятся в одной интерактивной сессии. `--amount` задаёт количество
единиц выбранной валюты.

```text
update-rates
register --username alice --password 1234
login --username alice --password 1234
buy --currency BTC --amount 0.05
sell --currency BTC --amount 0.01
show-portfolio
get-rate --from USD --to BTC
show-rates --top 2
exit
```

## Parser Service и кеш

Parser Service получает криптовалютные курсы из CoinGecko и фиатные —
из ExchangeRate-API. Ручное обновление выполняет команда `update-rates`;
`--source coingecko` или `--source exchangerate` выбирает один источник.
Периодическое обновление запускается отдельным процессом:

```powershell
uv run valutatrade-parser --interval 3600
```

Основной сервис читает последние курсы из `data/rates.json`.
История измерений хранится в `data/exchange_rates.json`.
TTL по умолчанию — 300 секунд; параметр `RATES_TTL_SECONDS` находится
в `[tool.valutatrade]` файла `pyproject.toml`. При устаревшем курсе
приложение предлагает выполнить `update-rates`.

## Структура каталогов

```text
finalproject_mikhailov_M26-555/
├── data/
│   ├── users.json
│   ├── portfolios.json
│   ├── rates.json
│   └── exchange_rates.json
├── docs/
│   └── valutatrade-demo.cast
├── valutatrade_hub/
│   ├── __init__.py
│   ├── logging_config.py
│   ├── decorators.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── currencies.py
│   │   ├── exceptions.py
│   │   ├── models.py
│   │   ├── usecases.py
│   │   └── utils.py
│   ├── infra/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   └── database.py
│   ├── parser_service/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── api_clients.py
│   │   ├── updater.py
│   │   ├── storage.py
│   │   └── scheduler.py
│   └── cli/
│       ├── __init__.py
│       └── interface.py
├── main.py
├── Makefile
├── uv.lock
├── pyproject.toml
├── README.md
├── .python-version
└── .gitignore
```

## Демонстрация

[![Демонстрация ValutaTrade Hub](https://asciinema.org/a/UMD8OV8piJGJknzS.svg)](https://asciinema.org/a/UMD8OV8piJGJknzS)
