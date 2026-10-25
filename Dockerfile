FROM python:3.12-slim

# FFmpeg нужен для сборки аудиокниг (M4B)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Копируем только то, что нужно вебу (без .env, token.txt, MyBooks, CLI).
COPY src ./src
COPY web ./web

ENV PORT=8000 \
    WEB_TMP_DIR=/tmp/yabooks_web \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# 1 воркер — чтобы держать потребление RAM в рамках (цель ~200–300 МБ).
# WEB_SECRET_KEY задайте через окружение (иначе сессии сбрасываются при рестарте).
# HTTPS: если заданы WEB_SSL_CERT и WEB_SSL_KEY (пути к сертификату и ключу),
# uvicorn поднимается по TLS; иначе — обычный HTTP.
CMD ["sh", "-c", "uvicorn web.app:app --host 0.0.0.0 --port ${PORT} --workers 1 ${WEB_SSL_CERT:+--ssl-certfile $WEB_SSL_CERT --ssl-keyfile $WEB_SSL_KEY}"]
