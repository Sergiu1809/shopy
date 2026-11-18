-- Local Compose only: runs once, on the first start of an empty db volume.
-- P1's first Alembic migration must create both too (Neon has no init scripts).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
