#!/usr/bin/env bash
# One-shot setup for AURUM Linux MT5 executor (no Windows).
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker مطلوب. ثبّته ثم أعد التشغيل."
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "تم إنشاء .env — غيّر VNC_PASSWORD قبل الإنتاج."
fi

echo "بناء وتشغيل منفّذ MT5 على Linux (أول مرة قد تستغرق 10–15 دقيقة)…"
docker compose up -d --build

echo
echo "بعد اكتمال الإقلاع:"
echo "  1) افتح http://$(hostname -I 2>/dev/null | awk '{print $1}'):3000 وسجّل Exness مرة واحدة"
echo "  2) في AURUM الصق: http://IP:5001"
echo "  3) راقب السجلات: docker compose logs -f mt5"
