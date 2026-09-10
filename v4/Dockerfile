FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm test && npm run build

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    POETRY_NO_INTERACTION=1 POETRY_VIRTUALENVS_IN_PROJECT=true \
    PATH="/app/.venv/bin:/opt/poetry/bin:$PATH"
WORKDIR /app
RUN python -m venv /opt/poetry \
    && /opt/poetry/bin/pip install poetry==2.2.1
COPY pyproject.toml poetry.lock poetry.toml ./
RUN poetry install --only main --no-root
COPY src ./src
COPY scripts ./scripts
RUN poetry install --only main \
    && useradd --uid 10001 --create-home appuser \
    && mkdir -p /app/data && chown appuser:appuser /app/data

FROM base AS test
RUN poetry install --with test
COPY tests ./tests
COPY docs ./docs
USER appuser
CMD ["python", "-m", "pytest", "--import-mode=importlib", "-p", "no:cacheprovider", "--override-ini", "addopts=", "-q"]

FROM base AS runtime
USER appuser
ENTRYPOINT ["matchtrader"]
CMD ["--help"]

FROM base AS dashboard
COPY --from=frontend /frontend/dist /app/frontend/dist
USER appuser
ENTRYPOINT ["python", "-m", "matchtrader.dashboard.cli"]
CMD ["--container"]
