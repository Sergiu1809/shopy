# Local shortcuts. The api image must be current (`docker compose up --build`) and
# migrated (the api service runs `alembic upgrade head` on start) before `make seed`.
.PHONY: seed reindex

seed:
	docker compose run --rm api python -m seed.seed

# Enqueue every product, its reviews and every policy (GH-13); the worker embeds what
# changed. For databases seeded before P2a.
reindex:
	docker compose run --rm api python -m worker.reindex_all
