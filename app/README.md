# PFAI 8.0.0 — Production Candidate

حزمة PFAI Control Plane: FastAPI + Dashboard عربية RTL + تعلم مستمر محكوم.

للتفاصيل التشغيلية والمعمارية راجع:
- `AGENTS.md`
- `docs/OPERATIONS.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`

## الحالة الافتراضية

- مزود النموذج: Anthropic (`ANTHROPIC_API_KEY` من Environment/Secrets فقط — لا يُخزَّن في Git).
- النموذج الافتراضي: `claude-opus-5`.
- الشبكة الخارجية مغلقة افتراضيًا.
- التعلم المستمر مفعّل في `configs/default.json`، ويمكن تعطيله فورًا عبر `PFAI_CONTINUOUS_TRAINING_ENABLED=false`.
- ترقية المرشحين إلى active تتطلب موافقة المالك (`X-Owner-Secret`) — لا يوجد auto-promote.
- `/health` متاح للفحص الصحي.

## تشغيل API + Dashboard محليًا

```bash
# اضبط الأسرار في بيئتك فقط (لا تضعها في ملفات متعقّبة)
export PFAI_OWNER_EMAIL='you@example.com'
export PFAI_OWNER_SECRET_HASH="$(python3 -c 'import hashlib; print(hashlib.sha256(b"CHANGE_THIS_SECRET").hexdigest())')"
# export ANTHROPIC_API_KEY=...   # من أسرار المنصة/الصدفة فقط

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python run_web.py
```

افتح `http://127.0.0.1:8000/`

## فحص الصحة

```bash
curl http://127.0.0.1:8000/health
```

## تعطيل/تفعيل التعلم المستمر

```bash
export PFAI_CONTINUOUS_TRAINING_ENABLED=false   # إيقاف فوري
export PFAI_CONTINUOUS_TRAINING_ENABLED=true    # فرض التشغيل
# أو اترك المتغير فارغًا لاستخدام configs/default.json
```

## Docker Compose

من جذر المستودع (حيث `Dockerfile`):

```bash
docker compose up -d
docker compose --profile continuous up -d   # API + worker التعلم
```

## النشر

لا يُنصح بـ Vercel. استخدم Docker على Render أو Railway أو VM مع قرص دائم على `/app/data`.
انظر `docs/OPERATIONS.md` و`render.yaml` و`railway.toml`.

## الاختبارات

الحزمة الأصلية وثّقت 260 اختبارًا. بعد أي تعديل مهم شغّل على الأقل:

```bash
python -m pytest tests/test_api_wiring.py tests/test_v81_continuous_enable_gate.py -q
```
