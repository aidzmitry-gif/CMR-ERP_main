FROM python:3.12-slim

WORKDIR /app

# Local PDF conversion of immutable originals; fonts include Cyrillic.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock.txt

RUN groupadd --gid 10001 aios && useradd --uid 10001 --gid aios --create-home aios \
    && chown aios:aios /app
COPY --chown=aios:aios . .
RUN chmod +x docker/app-entrypoint.sh && mkdir -p /app/data && chown aios:aios /app/data
USER 10001:10001

EXPOSE 8000
ENTRYPOINT ["docker/app-entrypoint.sh"]
