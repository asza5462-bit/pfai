FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    AURUM_HOST=0.0.0.0 \
    PORT=8000 \
    AURUM_MODE=paper \
    AURUM_SYMBOL=XAUUSDm \
    AURUM_AUTO_TRADE=false \
    AURUM_OPEN_REGISTER=1 \
    AURUM_COOKIE_SECURE=1 \
    AURUM_MIN_CONFLUENCE=0.62 \
    AURUM_LOOP_SECONDS=6 \
    AURUM_TICK_SECONDS=0.5 \
    AURUM_PULSE_CONFIRM=true \
    AURUM_COOLDOWN_SEC=120
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
