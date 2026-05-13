# syntax=docker/dockerfile:1.7
# Build from repo root: docker build -f api/Dockerfile -t spicy-desi-api:local .
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY api/pyproject.toml ./
COPY api/app ./app
RUN pip install --prefix=/install .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" PYTHONPATH="/app" \
    CONFIGS_DIR=/app/configs

WORKDIR /app
COPY --from=builder /install /install
COPY api/app ./app
COPY configs ./configs

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
