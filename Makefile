.PHONY: backend-test backend-lint backend-dev

backend-test:
	cd backend && uv run pytest

backend-lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app

backend-dev:
	cd backend && uv run uvicorn app.main:app --reload --port 8000
