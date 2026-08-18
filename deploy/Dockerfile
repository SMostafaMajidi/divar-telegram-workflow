FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app/src

COPY src ./src
COPY web ./web
COPY config ./config

EXPOSE 8765

CMD ["python3", "-m", "main", "serve", "--host", "0.0.0.0", "--port", "8765"]
