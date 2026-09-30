# AURUM — مكتب ذهب نخبة (XAUUSD)

بوت تداول ذهب مربوط بـ **FP Markets عبر cTrader Open API** (النظام الأساسي).

## التنفيذ

المسار الوحيد المفعّل: **cTrader Open API** لحسابات FP Markets على منصة cTrader.

مسارات MetaTrader 5 / MetaApi غير مفعّلة في هذا الإصدار.

## التشغيل

```bash
cd app
pip install -r requirements.txt
AURUM_MODE=paper uvicorn goldbot.api:app --host 0.0.0.0 --port 8000
```

## ربط FP Markets (cTrader)

1. أنشئ تطبيقاً على [openapi.ctrader.com](https://openapi.ctrader.com)
2. Redirect URI: `https://YOUR_HOST/api/ctrader/oauth/callback`
3. من تبويب «ربط cTrader»: احفظ Client ID/Secret → تفويض → اختر الحساب
4. الرمز: `XAUUSD`
