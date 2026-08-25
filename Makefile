.PHONY: install dev api web test lint fmt migrate revision ingest

install:
	python -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

api:
	uvicorn app.main:app --reload --app-dir backend --port 8000

web:
	cd frontend && npm run dev

dev:
	@echo "Run 'make api' and 'make web' in two terminals."

test:
	pytest -q

lint:
	ruff check . && mypy backend/app

fmt:
	ruff format . && ruff check --fix .

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

ingest:
	bb ingest prices
