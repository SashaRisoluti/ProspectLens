# Immagine unica per i servizi api e worker (comandi diversi).
# Contesto di build: la radice del repository.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.13.9

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    CONFIG_DIR=/app/config \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY config/ /app/config/
RUN uv sync --frozen --no-dev

RUN useradd --system --no-create-home app
USER app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn prospectlens.api.main:app --host 0.0.0.0 --port 8000"]
