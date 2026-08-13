.PHONY: up down dev test lint migrate

up:
	docker compose up -d db redis

down:
	docker compose down

dev:
	docker compose up -d
	cd frontend && npm run dev

test:
	docker compose run --rm api pytest

lint:
	docker compose run --rm api ruff check .

migrate:
	docker compose run --rm api alembic upgrade head