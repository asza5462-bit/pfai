# PFAI v8.0 — Web Control Plane

هذه النسخة تحول الواجهة الموجودة في `app/pfai/static/index.html` إلى Dashboard عربية RTL متعددة الأقسام متصلة مباشرة بـFastAPI الموجود في `app/pfai/api.py`.

## ما تم تغييره

- Dashboard تشغيلية RTL كاملة.
- Live System ومراقبة حالة الـBackend.
- Continuous Learning وGoverned Cycle.
- Code Evaluation / Best-of-N / Code Solve.
- Regression Queue وAuto-Fix workflow.
- Knowledge & Memory.
- Metrics & Analytics.
- Recovery Center.
- Deployment Center.
- Security / Owner Gate.
- API Console للمسارات الحقيقية.
- Modules inventory.
- Settings مع Backend URL وRefresh interval.
- Owner secret يستخدم `sessionStorage` فقط.
- لا توجد بيانات Metrics أو Learning أو Deployment وهمية.
- أضيف دعم CORS اختياري عبر `PFAI_CORS_ORIGINS` للواجهة المستضافة منفصلًا.

## تشغيل محلي

```bash
cd app
pip install -r requirements.txt
uvicorn pfai.api:app --host 0.0.0.0 --port 8000
```

ثم افتح:

`http://localhost:8000/`

## تشغيل Dashboard منفصلة

إذا كانت الواجهة مستضافة على ChatGPT Sites أو استضافة Frontend أخرى، ضع عنوان PFAI Backend في Settings > Backend.

على الـBackend، يمكن السماح بأصل الواجهة عبر:

```bash
PFAI_CORS_ORIGINS=https://your-site.example
```

لعدة أصول:

```bash
PFAI_CORS_ORIGINS=https://your-site.example,https://preview.example
```

لا تضع `PFAI_OWNER_PASSWORD_HASH` أو `ANTHROPIC_API_KEY` في Frontend.

## Production

الحزمة تحتوي `Dockerfile` و`docker-compose.yml` و`render.yaml` و`railway.toml`.

شغّل محرك PFAI Python كخدمة Backend مستمرة مع قرص دائم لـ `data/`.
لا تحوّل الوظائف إلى Mock داخل Dashboard، ولا تستخدم Vercel serverless لهذا المشروع.
