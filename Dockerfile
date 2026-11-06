FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TEAMBRAIN_ENV=production \
    TEAMBRAIN_DB=/data/teambrain.sqlite3 \
    HOST=0.0.0.0

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system teambrain \
    && useradd --system --gid teambrain --home-dir /app teambrain \
    && mkdir -p /data \
    && chown teambrain:teambrain /data

COPY --chown=teambrain:teambrain server ./server
COPY --chown=teambrain:teambrain README.md ./README.md
USER teambrain

EXPOSE 8000
VOLUME ["/data"]
CMD ["python", "-m", "server.app", "--http"]
