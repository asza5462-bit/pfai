# ORBIT

مشروع ويب نظيف: **GitHub → Render**.

## التشغيل محلياً

```bash
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload --port 8000
```

افتح: http://127.0.0.1:8000

## النشر على Render

1. ادفع الكود إلى GitHub.
2. اربط المستودع بخدمة Web على Render (Docker).
3. مسار الصحة: `/health`

أو استخدم `render.yaml` من جذر المستودع.

## المسارات

| المسار | الوصف |
|--------|--------|
| `/` | الصفحة الرئيسية |
| `/health` | فحص الصحة |
| `/api/info` | معلومات الـ API |
