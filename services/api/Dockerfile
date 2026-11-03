# API + worker image (same image, different command). Non-root, no build tools in the final layer.
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd -r vand && useradd -r -g vand -d /app -s /usr/sbin/nologin vand \
 && apt-get update && apt-get install -y --no-install-recommends util-linux && rm -rf /var/lib/apt/lists/*  # `unshare` for parser network isolation
WORKDIR /app
# Runtime-only pinned lock (no test/dev tooling in the production image)
COPY requirements.runtime.lock.txt .
RUN pip install --no-deps -r requirements.runtime.lock.txt
COPY --chown=vand:vand . .
USER vand
EXPOSE 8000
# No Docker HEALTHCHECK: this image also runs the worker (no HTTP). The API is health-checked by the platform at /healthz;
# worker liveness is reported via the ops queue snapshot (`worker_stale`).
# --proxy-headers is NOT enabled: client IP comes from CF-Connecting-IP, trusted only on edge-authenticated requests.
# Render (and most PaaS) inject $PORT; default 8000 locally. exec => uvicorn is PID 1 and receives SIGTERM for graceful shutdown.
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --timeout-graceful-shutdown 20"]
