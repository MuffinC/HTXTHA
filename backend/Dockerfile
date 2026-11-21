# Backend image: FastAPI + the PDF/LLM pipeline. Runs as a non-root user.
#
# Base image pinned to an exact patch release for reproducible builds
# (DECISIONS D-052). PyMuPDF ships manylinux wheels, so no system packages are needed.
FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

WORKDIR /app

# Fixed UID/GID so the /data volume's ownership is predictable.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

# Dependencies first: this layer is reused until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

USER app
EXPOSE 8000

# /api/health always answers 200 while the API is up (model readiness is in the
# body), so this checks the API process, not whether the model has been pulled.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
