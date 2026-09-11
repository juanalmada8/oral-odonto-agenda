# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------- build: dependencies only, in a venv
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Resolve dependencies from pyproject.toml with a stub package, then drop the stub: the real code
# runs from /app so templates/static are always next to it. Code changes don't bust this layer.
COPY pyproject.toml README.md ./
RUN mkdir app && touch app/__init__.py \
    && pip install --upgrade pip \
    && pip install . \
    && pip uninstall -y odonto-agenda-ai

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    # Configuration comes from the environment (Cloud Run env vars + Secret Manager), never a .env file.
    APP_ENV_FILE="" \
    PORT=8080

RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/health', timeout=2)"

# One process per container: Cloud Run scales instances; sync endpoints run in the threadpool.
# Jobs reuse this image: `alembic upgrade head` (migrations), `python -m app.tasks.run_scheduled`.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
