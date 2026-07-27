ARG BASE_REGISTRY=public.ecr.aws/docker/library
FROM ${BASE_REGISTRY}/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY requirements.lock ./
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.lock

COPY alembic.ini ./
COPY app ./app
COPY migrations ./migrations

RUN python -m pip install --no-deps .

EXPOSE 8000

CMD ["python", "-m", "app.startup"]
