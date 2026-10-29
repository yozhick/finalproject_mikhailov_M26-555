.PHONY: install run lint format format-check

install:
	uv sync

run:
	uv run python main.py

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .
