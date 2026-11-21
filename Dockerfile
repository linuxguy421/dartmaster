FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system dartmaster \
    && useradd --system --gid dartmaster --home-dir /nonexistent dartmaster \
    && mkdir -p /var/lib/dartmaster \
    && chown -R dartmaster:dartmaster /var/lib/dartmaster

COPY pyproject.toml README.md ./
COPY app ./app
COPY data ./data
COPY assets ./assets

RUN python -m pip install --no-cache-dir .

ENV DARTMASTER_DB_PATH=/var/lib/dartmaster/dartmaster.sqlite3

USER dartmaster

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
