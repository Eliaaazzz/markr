FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/markr

COPY pyproject.toml ./
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/pip pip install .

FROM base AS test
RUN --mount=type=cache,target=/root/.cache/pip pip install .[dev]
COPY tests ./tests
CMD ["pytest", "--cov=app", "--cov-report=term-missing", "--cov-fail-under=100"]

FROM base AS runtime
RUN useradd --create-home markr
USER markr
EXPOSE 4567
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4567"]
