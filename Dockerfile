FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PFAI_HOST=0.0.0.0 \
    PORT=8000 \
    PFAI_LOG_LEVEL=INFO
WORKDIR /app
COPY app/requirements.txt /app/requirements.txt
COPY app/requirements-training.txt /app/requirements-training.txt
# Core API + real CPU LoRA training stack (torch CPU wheel — not a mock backend).
RUN pip install --no-cache-dir -r /app/requirements.txt \
 && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
      -r /app/requirements-training.txt
COPY app/ /app/
# Base open-weight (~328MB) is not stored in git (GitHub file limit). Fetch at build.
RUN python - <<'PY'
from pathlib import Path
from urllib.request import urlretrieve
import hashlib

dest = Path("data/models/distilgpt2/model.safetensors")
dest.parent.mkdir(parents=True, exist_ok=True)
if dest.exists() and dest.stat().st_size > 100_000_000:
    print("distilgpt2 weights already present")
else:
    url = "https://huggingface.co/distilbert/distilgpt2/resolve/main/model.safetensors"
    print("downloading", url)
    urlretrieve(url, dest)
    print("downloaded_bytes", dest.stat().st_size)
PY
RUN useradd --create-home --uid 10001 pfai \
    && mkdir -p /app/data \
    && chown -R pfai:pfai /app
USER pfai
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"
CMD ["sh", "-c", "uvicorn pfai.api:app --host ${PFAI_HOST:-0.0.0.0} --port ${PORT:-8000}"]
