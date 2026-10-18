# Backend + worker image (FastAPI / APScheduler). PAPER trading only.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
# libgomp1: OpenMP runtime needed by XGBoost / scikit-learn wheels
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /usr/local/bin/uv

WORKDIR /app
# Optional LLM SDKs: docker compose build --build-arg UV_EXTRAS="--extra ai"
ARG UV_EXTRAS=""
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project ${UV_EXTRAS}
COPY alembic.ini ./
COPY alembic ./alembic
COPY labs/course_labs.yaml ./labs/course_labs.yaml
COPY docs ./docs
COPY src ./src
RUN uv sync --frozen --no-dev ${UV_EXTRAS} && useradd -m -u 1000 trader && mkdir -p /app/data && chown -R trader /app
USER trader
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1
CMD ["trader", "serve", "--host", "0.0.0.0", "--port", "8000"]
