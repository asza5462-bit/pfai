# منفّذ Exness على Linux (بدون Windows)

Exness لا توفّر REST API عام. هذا المجلد يبني MetaTrader 5 داخل Docker/Wine على Linux ويعرّض REST لـ AURUM.

## إعداد سريع

```bash
cd deploy/mt5-linux
chmod +x setup.sh
./setup.sh
```

1. افتح `http://IP:3000` وسجّل دخول حساب Exness/MT5 مرة واحدة.
2. في AURUM → تبويب الربط → الصق `http://IP:5001`.
3. ابدأ التداول من التطبيق.

أول إقلاع قد يستغرق 10–15 دقيقة (تحميل MT5 + Wine).

## البديل الأسهل (بدون VPS)

1. افتح https://app.metaapi.cloud/api-access/generate-token
2. الصق التوكن في AURUM — يتم الربط التلقائي بحساب Exness المحفوظ.
