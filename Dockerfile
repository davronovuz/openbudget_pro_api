# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OS deps (psycopg2 va Pillow uchun umumiy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gcc musl-dev \
    libjpeg62-turbo-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Talablar
COPY requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt && pip install gunicorn

# Loyihani ko‘chir
COPY . /app

# App porti
EXPOSE 8001

# Default: gunicorn (compose ichida migrate/collectstatic qilamiz)
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8001", "--workers", "3"]
