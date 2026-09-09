FROM python:3.12-slim

WORKDIR /app

# Local PDF conversion of immutable originals; fonts include Cyrillic.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker/app-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["docker/app-entrypoint.sh"]
