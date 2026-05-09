FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# PORT is injected by DigitalOcean App Platform; falls back to 8000 for
# local / TrueNAS Docker Compose deployments.
EXPOSE ${PORT:-8000}

CMD gunicorn -w 4 -b 0.0.0.0:${PORT:-8000} --timeout 60 --preload wsgi:app
