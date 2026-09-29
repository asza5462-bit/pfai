# منفّذ Exness على Linux (بدون Windows)

Exness لا توفّر REST API عام. هذا المجلد يشغّل MetaTrader 5 داخل Docker/Wine على Linux ويعرّض REST لـ AURUM.

## الخطوات

1. على أي سيرفر Linux x86_64 مع Docker:
   ```bash
   cp .env.example .env
   # عدّل VNC_PASSWORD
   docker compose up -d
   ```
2. افتح `http://IP:3000` وسجّل دخول حساب Exness/MT5 مرة واحدة.
3. في AURUM → تبويب الربط → الصق `http://IP:5001` واحفظ منفّذ Linux.
4. ابدأ التداول من التطبيق.

البديل الأسهل بدون VPS: توكن MetaApi (حساب واحد مجاني تقريباً) من https://app.metaapi.cloud
