# 02: Skeleton: uv project, settings, /health, Docker

Status: ready-for-agent

- uv project (Python 3.12) with pinned deps and `uv.lock`; `app/` package; pydantic-settings `Settings` with the spec's env table; `.env.example`; `.gitignore` (`.env`, chroma dir).
- FastAPI app with `GET /health`.
- Dockerfile (`uv sync --locked`, `PORT`) and compose (`.env`, healthcheck on `/health`).

Done when `docker compose up --build` reaches healthy, and `uv run pytest` passes a `/health` test.
