# syntax=docker/dockerfile:1

# --- Builder: resolve dependencies into a self-contained venv --------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

# --- Runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    PATH="/opt/venv/bin:$PATH"

# libpq is needed by psycopg; curl backs the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .

# Baked into the image so the admin's CSS/JS are served without a build step
# at boot. A throwaway key is fine: collectstatic never touches the database.
RUN DJANGO_SECRET_KEY=build-only DJANGO_DEBUG=false DJANGO_ALLOWED_HOSTS=* \
    python manage.py collectstatic --noinput \
    && mkdir -p /app/uploads && chown -R app:app /app/uploads /app/staticfiles

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/ || exit 1

# Threads (not extra workers) because the ingestion pipeline keeps its own
# in-process queue — a second worker process would run it twice.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "1", \
     "--threads", "8", \
     "--timeout", "120", \
     "--access-logfile", "-"]
