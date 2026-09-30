# AURUM — مكتب ذهب نخبة (XAUUSD)

بوت تداول ذهب مربوط بـ **FP Markets عبر cTrader Open API** — يعمل من التطبيق مباشرة.

## النظام الأساسي

- الوسيط: **FP Markets** فقط
- المنصة: **cTrader Open API**
- بدون Windows / بدون MetaApi في الوضع الافتراضي

## التشغيل المحلي

```bash
cd app
pip install -r requirements.txt
AURUM_MODE=paper uvicorn goldbot.api:app --host 0.0.0.0 --port 8000
```

## ربط FP Markets من التطبيق

1. أنشئ حساب تطبيق (تسجيل)
2. أنشئ تطبيقاً على [openapi.ctrader.com](https://openapi.ctrader.com)
3. Redirect URI: `https://YOUR_HOST/api/ctrader/oauth/callback`
4. من تبويب «ربط cTrader»: احفظ Client ID/Secret → تفويض → اختر حساب FP Markets
5. اضغط «ابدأ التداول»

## متغيرات Render المهمة

```
AURUM_PREFER_CTRADER=true
AURUM_PREFER_METAAPI=false
AURUM_SYMBOL=XAUUSD
CTRADER_CLIENT_ID=...
CTRADER_CLIENT_SECRET=...
AURUM_AUTH_SECRET=...
AURUM_PUBLIC_URL=https://pfai-v8.onrender.com
```

## معايير البوت

- تنفيذ حقيقي فقط عند اتصال cTrader (لا صفقات وهمية)
- شموع وأسعار من الوسيط
- إدارة ذكية: تعادل، تتبع، خروج، مزامنة الصفقات
- حدود مخاطرة يومية وصفقة واحدة وcooldown
