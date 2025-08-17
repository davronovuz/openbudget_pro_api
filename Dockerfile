FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# minimal system deps (DRF + Gunicorn uchun yetadi)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt bo'lsa ishlatamiz (yo'q bo'lsa pip install django d.r.f gunicorn qiling)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# source
COPY . /app

# zarur papkalar
RUN mkdir -p /app/staticfiles /app/media /app/db

EXPOSE 8001
