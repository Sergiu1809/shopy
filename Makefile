# Local shortcuts. The api image must be current (`docker compose up --build`) and
# migrated (the api service runs `alembic upgrade head` on start) before `make seed`.
.PHONY: seed

seed:
	docker compose run --rm api python -m seed.seed
