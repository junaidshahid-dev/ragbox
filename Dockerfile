FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ragbox/ ragbox/
COPY sample_docs/ sample_docs/

# /data MUST be a mounted PERSISTENT VOLUME in production. Container filesystems are wiped on
# every redeploy - without a volume here, every account and every customer document is destroyed.
# GET /health reports data_persistent:false if this is misconfigured.
ENV RAGBOX_HOME=/data
RUN mkdir -p /data

# run unprivileged: a process that writes user-uploaded files should never be root
RUN useradd -m -u 10001 ragbox && chown -R ragbox:ragbox /app /data
USER ragbox

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

# ${PORT} lets Railway/Render/Fly inject their own port; falls back to 8000 locally
CMD ["sh", "-c", "uvicorn ragbox.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
