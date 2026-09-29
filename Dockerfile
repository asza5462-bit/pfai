FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    AURUM_HOST=0.0.0.0 \
    PORT=8000 \
    AURUM_MODE=paper \
    AURUM_SYMBOL=XAUUSD \
    AURUM_AUTO_TRADE=false
WORKDIR /app
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app/ /app/
RUN useradd --create-home --uid 10001 aurum \
    && mkdir -p /app/data/goldbot \
    && chown -R aurum:aurum /app
USER aurum
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"
CMD ["sh", "-c", "uvicorn goldbot.api:app --host ${AURUM_HOST:-0.0.0.0} --port ${PORT:-8000}"]
