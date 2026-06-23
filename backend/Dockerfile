# syntax=docker/dockerfile:1
#
# Production image for the Omiximo Support Automation API.
#
# Two stages: a build stage that compiles dependencies into a venv, and a slim
# runtime stage that carries only the venv + app and runs as a non-root user.
#
# IMPORTANT: the API is run as a SINGLE process (no --workers, no --reload).
# app.main:app starts in-process background loops (mirakl_poller,
# auto_send_executor, sla_monitor) via the FastAPI lifespan. Running more than
# one worker/replica would run those loops N times and could double-send
# replies to customers. Scale the web tier only after the schedulers are
# extracted into their own single-replica worker. See k8s/README.md.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Build everything into an isolated venv we can copy wholesale into runtime.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
# hatchling builds the wheel from the `app` package, so the source must be
# present at install time.
COPY . .
RUN pip install --upgrade pip && pip install .


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# libpq5 for asyncpg at runtime; postgresql-client gives pg_isready + psql
# (used by the wait-for-db init container and for debugging); curl for the
# container HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home appuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser . .

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Single process — see the note at the top of this file.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
