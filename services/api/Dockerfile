# API + worker image (same image, different command). Non-root, no build tools in the final layer.
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd -r vand && useradd -r -g vand -d /app -s /usr/sbin/nologin vand \
 && apt-get update && apt-get install -y --no-install-recommends util-linux && rm -rf /var/lib/apt/lists/*  # `unshare` for parser network isolation
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install -r requirements.lock.txt
COPY --chown=vand:vand . .
USER vand
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status==200 else 1)"
# --proxy-headers is NOT enabled: client IP comes from CF-Connecting-IP, trusted only on edge-authenticated requests.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "20"]
