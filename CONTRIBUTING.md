# Contributing

Thanks for helping! Local DS is deliberately small: one Python process, SQLite, and a no-build frontend.

The full developer guide is **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** (setup, tests, conventions, step-by-step
recipes, releasing). Start with **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** to see how the pieces fit.

## Quick setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
sudo apt install ffmpeg shellcheck        # or your OS's package manager

export DATA_DIR=./data SCHEDULER_ENABLED=false
python -m app.seed --users                 # demo data, users demo/demo-password and friend/friend-password
uvicorn --factory app.main:create_app --reload --port 8080
```

## Before opening a pull request

```bash
ruff check . && ruff format --check .
pytest -q
shellcheck install.sh docker/entrypoint.sh scripts/*.sh
node --check app/static/app.js && node --check app/static/sw.js
```

CI runs the same checks plus a Docker build and smoke test.

## Guidelines

- Keep the single-container, no-build-step design. New Python dependencies need a good reason.
- Never auto-delete comments, reactions or Short records; only video files expire.
- Anything that fetches a user-supplied URL must go through `app.urlsafe.safe_get`.
- Insert user or feed text into the DOM with `textContent` (the `h()` helper); only server-sanitized article HTML
  may use `innerHTML`.
- Add or update tests for behaviour changes, a line in `CHANGELOG.md`, and the matching page in `docs/`.
- Mobile first: check new UI at 360 px wide (`python scripts/screenshots.py` helps).
