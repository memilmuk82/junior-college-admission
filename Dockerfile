FROM ghcr.io/astral-sh/uv:0.11.26 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-kor \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY wsgi.py ./

EXPOSE 5000

CMD ["uv", "run", "--no-sync", "flask", "--app", "wsgi", "run", "--host=0.0.0.0", "--port=5000"]
