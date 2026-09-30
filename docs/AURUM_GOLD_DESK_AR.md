# AURUM — مكتب ذهب نخبة (XAUUSD)

تحويل جذري من PFAI إلى بوت تداول ذهب حقيقي جاهز للربط مع **MetaTrader 5 / Exness**.

## ماذا يفعل

- يقرأ الشموع والأنماط (Pin, Engulfing, Stars, Structure)
- يجمع أصوات مدارس عالمية: Price Action · SMC/ICT · Trend · Sessions · ATR
- تقديرات سيولة/مؤسسات من OHLC (ليست شريط أوامر حقيقي للبنوك)
- إدارة مخاطر صارمة: لوت حسب المخاطرة، حد خسارة يومي، تبريد، رفض السبريد الواسع
- وضع `paper` على Render/Linux · وضع `mt5` على Windows VPS مع Exness

## حقيقة مهمة

**لا يمكن ضمان خسارة صفر أو تكات رابحة دائماً.** أي ادّعاء كذلك غير صادق. AURUM مصمم لتقليل الصفقات السيئة وحماية رأس المال.

## التشغيل

```bash
cd app
pip install -r requirements.txt
AURUM_MODE=paper uvicorn goldbot.api:app --host 0.0.0.0 --port 8000
```

## ربط Exness

راجع `GET /api/connect-guide` أو تبويب «ربط Exness السحابي».

### cTrader Open API (من التطبيق مباشرة)

يعمل فقط إن كان حساب Exness على منصة **cTrader** (وليس MT5 فقط):

1. أنشئ تطبيقاً على [openapi.ctrader.com](https://openapi.ctrader.com) واحصل على Client ID + Secret.
2. أضف Redirect URI: `https://YOUR_HOST/api/ctrader/oauth/callback`
3. من تبويب الربط: احفظ التطبيق → تفويض cTrader → اختر الحساب.
4. اختياري عبر البيئة: `CTRADER_CLIENT_ID` / `CTRADER_CLIENT_SECRET` / `AURUM_PUBLIC_URL`.

مسارات أخرى: MetaApi (MT5) · Windows agent · Linux Docker MT5.
