# eliozo-db — PostgreSQL + pgvector for the Eliozo app

Local (developer workstation) vector database for
`qualification-project/eliozoapp`. Runs as a Docker container under **colima**
on macOS; the same `.env` + Alembic migration will later back a **native**
PostgreSQL install on the Ubuntu server.

Full write-up and rationale:
`../eliozo-setup/REQUEST017_LOCAL-postgres-pgvector-colima.md`.
Operator guide (start/stop/credentials): *PostgreSQL + pgvector* section of
`../eliozo-setup/ADMIN-GUIDE.md`.

## Quick start

```bash
cp .env.example .env            # then fill in DB_PASSWORD + OPENAI_API_KEY
colima start --cpu 2 --memory 4 --disk 20   # if not already running
docker compose up -d            # start PostgreSQL 16 + pgvector on :5432

VENV=~/workspace/worksheet-generation-with-llms/wsheet-env/bin/python
$VENV -m alembic upgrade head   # create extension, tables, HNSW indexes
$VENV seed_test_data.py         # optional: a few rows with DUMMY embeddings
# or load every problem from the Flask app's RDF store (see
# qualification-project/eliozoapp/eliozo_dao/README.md, "Search by meaning"):
#   python -m eliozo_dao.postgres.load_problems [--embeddings openai]

docker exec -it eliozo-db psql -U appuser -d eliozo   # ad-hoc SQL
```

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | `pgvector/pgvector:pg16`, port 5432, named volume `pgdata`, healthcheck |
| `.env` | credentials + `OPENAI_API_KEY` — **git-ignored**, same file used on both environments |
| `.env.example` | committable template |
| `requirements.txt` | Python deps (installed into `wsheet-env`) |
| `alembic.ini`, `alembic/` | schema migrations; `env.py` builds the URL from `.env` |
| `seed_test_data.py` | sanity rows parsed from `math/problembase`, random embeddings |

## Stop / wipe

```bash
docker compose stop      # keep data
docker compose down      # remove container, keep volume
docker compose down -v   # DELETE the data volume
colima stop              # shut down the Docker VM
```

> **Note:** `.env` here holds a live `OPENAI_API_KEY` and the DB password and is
> git-ignored. On the Ubuntu server these become a systemd `EnvironmentFile`.
> macOS AirPlay occupies port `:5000` (HTTP 403) — unrelated; PostgreSQL is on
> `:5432`, and run local Flask with `--port 5001`.
