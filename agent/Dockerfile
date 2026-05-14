# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
RUN pip install --prefix=/install .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/app:/install/lib/python3.12/site-packages"

WORKDIR /app
COPY --from=builder /install /install
COPY app ./app

# Pipecat needs libgomp1 at runtime for some audio ops (silero, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

EXPOSE 8090

# --proxy-headers + --forwarded-allow-ips so request.url.scheme reflects
# X-Forwarded-Proto from Fly's edge. Critical for Twilio signature
# validation: the URL Twilio signed is https://..., not http://...
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
