FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONHASHSEED=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ghostscript \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./

RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/uploads /app/compressed \
    && chown -R appuser:appuser /app

ENV PORT=5000 \
    FLASK_ENV=production \
    UPLOAD_FOLDER=/app/uploads \
    COMPRESSED_FOLDER=/app/compressed \
    MAX_CONTENT_LENGTH=104857600 \
    COMPRESS_RATE_LIMIT="10 per minute" \
    GHOSTSCRIPT_COMMAND=gs

EXPOSE 5000

USER appuser

CMD ["sh", "-c", "gunicorn -w 2 -k gthread -t 120 -b 0.0.0.0:${PORT} app:app"]
