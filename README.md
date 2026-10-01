# NOVA Code

استوديو برمجة ذكي يحوّل المحادثة إلى كود حقيقي داخل مساحة عمل معزولة.

## القدرات

- شات عربي/إنجليزي مع وكيل برمجي متعدد الخطوات.
- قراءة وكتابة وحذف الملفات مع حماية كاملة من Path Traversal.
- مستكشف ملفات ومحرر كود وتبويبات وحفظ مباشر.
- تنفيذ أوامر تطوير مقيّدة بمهلة وحدود إخراج وموافقة صريحة مستقلة.
- معاينة Git diff وإنشاء نقاط حفظ محلية.
- محادثات ومشاريع دائمة في SQLite.
- OpenAI وAnthropic وأي API متوافق مع OpenAI.
- تشفير مفاتيح API في قاعدة البيانات باستخدام Fernet.
- حساب مالك واحد، جلسات HttpOnly، Rate Limiting، وSecurity Headers.

## التشغيل محلياً

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
export NOVA_APP_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export NOVA_SETUP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
export NOVA_COOKIE_SECURE=false
.venv/bin/uvicorn app.main:app --reload --port 8000
```

افتح `http://127.0.0.1:8000` واستخدم `NOVA_SETUP_TOKEN` عند إنشاء حساب المالك.

## متغيرات البيئة

| المتغير | الغرض |
|---|---|
| `NOVA_APP_SECRET` | مفتاح تشفير الجلسات والأسرار (إلزامي في الإنتاج) |
| `NOVA_SETUP_TOKEN` | يحمي إنشاء حساب المالك الأول |
| `NOVA_DATA_DIR` | قاعدة البيانات ومساحات العمل، افتراضياً `data` |
| `NOVA_COOKIE_SECURE` | كوكي HTTPS، افتراضياً `true` |
| `OPENAI_API_KEY` | مفتاح اختياري من بيئة الخادم |
| `ANTHROPIC_API_KEY` | مفتاح اختياري من بيئة الخادم |
| `NOVA_AI_MODEL` | النموذج الافتراضي |
| `NOVA_ALLOW_COMMANDS` | تشغيل الطرفية المقيدة، افتراضياً `true` |

## الأمان

الطرفية ليست Shell مفتوحة. الأوامر تمر عبر قائمة مسموحة، دون Shell expansion، ببيئة محدودة ومهلة. لا ينفذ الوكيل أمراً إلا عند تفعيل «تشغيل أوامر» لكل طلب. هذا الإصدار مخصص لمالك واحد ومساحات موثوقة؛ تنفيذ كود متعدد المستخدمين يحتاج Sandbox خارجياً معزولاً. مفاتيح API لا تعاد إلى المتصفح بعد حفظها. في Render يجب تركيب Persistent Disk على مسار `NOVA_DATA_DIR` للحفاظ على المشاريع بين عمليات النشر.

## الاختبارات

```bash
.venv/bin/pytest -q
```
