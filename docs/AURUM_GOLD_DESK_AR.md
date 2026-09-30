# AURUM — مكتب ذهب نخبة (XAUUSD)

بوت تداول ذهب جاهز للربط مع **FP Markets** عبر MetaTrader 5 أو cTrader.

## ماذا يفعل

- يقرأ الشموع والأنماط (Pin, Engulfing, Stars, Structure)
- يجمع أصوات مدارس عالمية: Price Action · SMC/ICT · Trend · Sessions · ATR
- تقديرات سيولة/مؤسسات من OHLC
- إدارة مخاطر صارمة: لوت حسب المخاطرة، حد خسارة يومي، تبريد، رفض السبريد الواسع
- وضع `paper` على Render/Linux · وضع `mt5` مع FP Markets

## حقيقة مهمة

**لا يمكن ضمان خسارة صفر أو تكات رابحة دائماً.** AURUM مصمم لتقليل الصفقات السيئة وحماية رأس المال.

## التشغيل

```bash
cd app
pip install -r requirements.txt
AURUM_MODE=paper uvicorn goldbot.api:app --host 0.0.0.0 --port 8000
```

## ربط FP Markets

راجع `GET /api/connect-guide` أو تبويب «ربط FP Markets السحابي».

### MT5 عبر MetaApi (بدون Windows)

1. توكن من [MetaApi](https://app.metaapi.cloud/api-access/generate-token)
2. من لوحة MetaApi أضف حساب MT5 بسيرفر مثل `FPMarkets-Live` وانتظر Connected
3. اربط Account ID من تبويب الربط في AURUM
4. الرمز الافتراضي: `XAUUSD`

### cTrader Open API

يعمل إن كان حساب FP Markets على منصة **cTrader**:

1. تطبيق على [openapi.ctrader.com](https://openapi.ctrader.com)
2. Redirect URI: `https://YOUR_HOST/api/ctrader/oauth/callback`
3. احفظ → فوّض → اختر الحساب

### Windows agent

فعّل المسار من تبويب الربط وشغّل `aurum_exness_agent.py` مع MT5 مفتوح على سيرفر FP Markets.
