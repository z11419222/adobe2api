# Repository Instructions

## Commands
- Use Python 3.10 for runtime work (`Dockerfile` uses `python:3.10-slim-bullseye`); in this Windows workspace, bare `python` may resolve to 3.14 and fail pinned `Pillow`/`pydantic-core` installs.
- Install runtime deps with `py -3.10 -m pip install -r requirements.txt`; there is no committed dev requirements file.
- Run locally from the repo root: `py -3.10 -m uvicorn app:app --host 0.0.0.0 --port 6001 --reload`.
- Docker path: `docker compose up -d --build`; the image runs `python app.py` and reads `PORT`.
- Fast smoke checks that do not call Adobe upstream: `curl http://127.0.0.1:6001/api/v1/health` and `curl -H "Authorization: Bearer <config api_key>" http://127.0.0.1:6001/v1/models`.
- Syntax-check Python when no narrower test exists: `py -3.10 -m compileall -q app.py api core`.

## App shape
- `app.py` is both the FastAPI app (`app`) and script entrypoint; importing it instantiates stores/client/managers and starts `refresh_manager`'s background thread.
- Route files expose `build_*_router(...)` factories and receive dependencies from `app.py`; do not create duplicate global managers/clients inside routers.
- `api/routes/generation.py` owns OpenAI-compatible image/video routes plus legacy `/api/v1/generate`; `api/routes/admin.py` owns the admin UI/API; `api/routes/entity.py` owns `/v1/entities`.
- Model IDs are generated in `core/models/catalog.py`; `MODELS.md` says its source of truth is `core.models.catalog`, so keep docs in sync when changing catalog loops.
- `core/models/resolver.py` silently falls unsupported ratios back to `1:1`, and model IDs with ratio/resolution suffixes override request `aspect_ratio`/`quality`.

## Runtime state and secrets
- Runtime state is file-backed: `config/config.json`, `config/tokens.json`, `config/refresh_profile.json`, `config/entities.json`, `data/request_logs.jsonl`, `data/request_errors.jsonl`, and `data/generated/`.
- `.gitignore` ignores `data`, `config/config.json`, `config/tokens.json`, and `config/refresh_profile.json`; treat any generated `config/entities.json` as private runtime state too.
- `ConfigManager` and `TokenManager` migrate legacy `data/config.json` and `data/tokens.json` into `config/` if the new files are missing.
- Service auth uses `config/config.json` key `api_key`; clients may send `Authorization: Bearer <api_key>` or `X-API-Key: <api_key>`. Admin APIs require the session cookie from `/api/v1/auth/login`.
- Environment overrides used by code/deploy include `PORT`, `ADOBE_ADMIN_SESSION_SECRET`, `ADOBE_API_KEY`, `ADOBE_IMPERSONATE`, `ADOBE_PROXY`, `ADOBE_USER_AGENT`, `ADOBE_SEC_CH_UA`, `ADOBE_GENERATE_TIMEOUT`, `ADOBE_PUBLIC_BASE_URL`, and `PUBLIC_BASE_URL`.

## Testing and CI gotchas
- `.github/workflows/docker-image.yml` only builds/pushes the Docker image on `master`; it does not run lint, typecheck, or tests.
- `pytest` is not in `requirements.txt` and there is no pytest config. Do not assume `pytest` is the verification gate unless you add dev tooling.
- `tests/test_generate.py` is an upstream Adobe exercise script requiring `ADOBE_ACCESS_TOKEN` and `ADOBE_API_KEY`; do not run it as a default unit test.
- `tests/test_service.py` is a manual smoke script, not a pytest test; as written it launches `python app.py` with `cwd=tests/`, so verify/fix that before relying on it.

## Deployment notes
- Docker Compose persists `./data:/app/data` and `./config:/app/config`, and sets `ADOBE_API_KEY=clio-playground-web`.
- Zeabur deploys from `master`, initializes `/app/config/config.json`, persists `/app/config` and `/app/data`, and sets public URL env vars in `zeabur-template.yaml`.
- Generated media lives in `data/generated/`, is served as `/generated/<filename>`, and is pruned by `generated_max_size_mb` / `generated_prune_size_mb`.

## Browser extension
- `browser-cookie-exporter/` is a plain Chrome/Edge extension (`manifest.json`, `popup.*`) with no build step; it exports minimal JSON of the form `{ "cookie": "k=v; ..." }` for admin import.
