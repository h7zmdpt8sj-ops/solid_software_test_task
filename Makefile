.PHONY: install up down db run test lint format check

install:
	uv sync

up:
	docker compose up --build --detach --wait

down:
	docker compose down --volumes

db:
	docker compose up --detach --wait db

run: db
	uv run flask --app app run --port 8000 --debug

test: db
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

format:
	uv run ruff check --fix .
	uv run ruff format .

check: lint test
