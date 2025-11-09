# توثيق واجهة برمجة التطبيقات (API)

يوفّر تطبيق ضغط ملفات PDF واجهة REST ثابتة يمكن دمجها بسهولة مع أي نظام خارجي. يوضح هذا الدليل النقاط المتاحة ضمن نطاق
`/api` بالإضافة إلى نقطة الصحة العامة.

## نظرة عامة

- **نقطة الصحة:** `GET /healthz`
- **نقطة الضغط الأساسية:** `POST /api/compress`
- **نقطة الإصدار:** `GET /api/version`
- **صيغة الطلب:** `multipart/form-data`
- **نوع الاستجابة الافتراضي:** ملف PDF مضغوط (`application/pdf`)
- **استجابة JSON اختيارية:** أرسل الترويسة `Accept: application/json`
- **المصادقة:** اختيارية عبر مفتاح API (تُفعّل عند ضبط المتغير البيئي `API_KEYS`)
- **معدّل الطلبات الافتراضي:** `10 طلبات في الدقيقة` لكل عنوان IP (قابل للتعديل عبر المتغيّر `COMPRESS_RATE_LIMIT`)

## نقطة الصحة `GET /healthz`

تعيد JSON يحتوي على حالة الخدمة، ومسار/اسم ملف Ghostscript، ورقم إصدار التطبيق.

```json
{
  "status": "ok",
  "ghostscript": "gs",
  "version": "1.0.0"
}
```

## نقطة الضغط `POST /api/compress`

| الحقل | النوع | إجباري؟ | الوصف |
| --- | --- | --- | --- |
| `file` | ملف (PDF) | نعم | ملف PDF المراد ضغطه. تُرفض الملفات غير الـ PDF أو التي تتجاوز 100 ميغابايت. |
| `profile` | سلسلة نصية | لا (القيمة الافتراضية `medium`) | تحدّد إعداد ضغط Ghostscript. القيم المدعومة: `low` (`/printer`)، `medium` (`/ebook`)، `high` (`/screen`). |
| `keep_images` | منطقية (`true`/`false`) | لا | عند تفعيلها تُعطّل خيارات خفض جودة الصور للحفاظ على الدقّة البصرية. |

### أوضاع الاستجابة

| الترويسة `Accept` | نوع الاستجابة | الوصف |
| --- | --- | --- |
| غير محدد أو `application/pdf` | ملف PDF | يتم تنزيل الملف المضغوط مباشرة مع ترويسة `Content-Disposition`. |
| `application/json` | JSON | معلومات عن عملية الضغط (أحجام الملفات، النسبة، المعرّف الفريد). |

### مثال استجابة JSON ناجحة

```json
{
  "ok": true,
  "original_bytes": 5242880,
  "compressed_bytes": 2621440,
  "ratio": 0.5,
  "profile": "medium",
  "request_id": "8f5b6a3c2d7e4a9f9b0c1d2e3f4a5b6c"
}
```

### أمثلة باستخدام `curl`

#### تنزيل الملف المضغوط

```bash
curl -s -X POST http://localhost:8080/api/compress \
  -F "file=@/path/to/input.pdf" -F "profile=medium" \
  --output compressed.pdf
```

#### الحصول على استجابة JSON

```bash
curl -s -X POST http://localhost:8080/api/compress \
  -H "Accept: application/json" \
  -F "file=@/path/to/input.pdf" -F "profile=high"
```

#### استخدام مفتاح API

```bash
curl -s -X POST http://localhost:8080/api/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@/path/to/input.pdf" \
  --output compressed.pdf
```

### أمثلة على الأخطاء الشائعة (JSON)

| الرمز | السبب | نموذج استجابة |
| --- | --- | --- |
| 400 | ملف مفقود أو قيمة `profile` غير صحيحة | `{ "ok": false, "error": "invalid_profile", "detail": "Profile must be one of: low, medium, high." }` |
| 401 | مفتاح API مفقود أو غير صحيح (عند التفعيل) | `{ "ok": false, "error": "unauthorized", "detail": "A valid API key must be supplied via the X-API-Key header." }` |
| 413 | تجاوز حد الحجم الأقصى (100 ميغابايت) | `{ "ok": false, "error": "payload_too_large", "detail": "The uploaded file exceeds the 100 MiB limit." }` |
| 415 | ملف غير PDF | `{ "ok": false, "error": "unsupported_media_type", "detail": "Only PDF documents are supported for compression." }` |
| 429 | تجاوز الحد المسموح للطلبات | `{ "ok": false, "error": "rate_limited", "detail": "Too many requests, please try again later." }` |
| 500 | خطأ داخلي أثناء تنفيذ Ghostscript | `{ "ok": false, "error": "ghostscript_error", "detail": "Ghostscript failed while compressing the file." }` |
| 503 | Ghostscript غير متوفر على الخادم | `{ "ok": false, "error": "ghostscript_unavailable", "detail": "Ghostscript is not available on the server. Please install it and ensure it can be executed." }` |

## نقطة الإصدار `GET /api/version`

تعيد معلومات الإصدار بشكل JSON. تتضمن الحقول `version` (إلزامي)، و`commit` و`build_time` (اختياريان حسب توفر بيانات البناء).

```json
{
  "version": "1.0.0",
  "commit": "d34db33f",
  "build_time": "2024-05-15T12:00:00Z"
}
```

## المصادقة باستخدام مفاتيح API

- اضبط المتغير البيئي `API_KEYS` بقائمة مفصولة بفواصل (مثل `API_KEYS=key1,key2`).
- يجب تضمين الترويسة `X-API-Key` في كل طلب عند تفعيل المفاتيح.
- في حال عدم ضبط المتغير تبقى الواجهة مفتوحة بدون مصادقة.

## إعدادات قابلة للتخصيص

| المتغيّر | الوصف |
| --- | --- |
| `COMPRESS_RATE_LIMIT` | يغيّر الحد الأقصى لعدد الطلبات (صيغة مثل `20 per minute` أو `100 per hour`). |
| `RATELIMIT_STORAGE_URI` | يحدّد مخزن بيانات المعدّل (افتراضيًا ذاكرة مؤقتة؛ يُنصح باستخدام Redis في الإنتاج). |
| `GHOSTSCRIPT_COMMAND` | مسار تنفيذ Ghostscript عند عدم تواجده في متغير `PATH`. |
| `MAX_CONTENT_LENGTH` | حد الحجم الأقصى للملفات (افتراضيًا 100 ميغابايت داخل الحاوية). |
| `API_KEYS` | مفاتيح الوصول المسموح بها للواجهة البرمجية. |

## أفضل ممارسات الأمن والنشر

- ضع التطبيق خلف وكيـل عكسي (مثل Nginx) مع تفعيل HTTPS.
- استخدم مفاتيح API أو قوائم IP بيضاء لحماية الواجهة عند تقديم الخدمة لطرف ثالث.
- راقب السجلات والأخطاء (يمكن دمج حلول مثل Sentry أو Elastic Stack).
- فعّل التخزين المؤقت والـ CDN عند مشاركة الخدمة على نطاق واسع لتقليل الحمل.

## اختبار واجهة الـ API

1. شغّل الخادم عبر Docker Compose:
   ```bash
   ./run.sh
   ```
2. أرسل أي من طلبات `curl` الموضّحة أعلاه.
3. تحقّق من أن الاستجابات تأتي بصيغة PDF أو JSON كما هو متوقع وأن رسائل الأخطاء تتبع البنية القياسية (`ok`, `error`, `detail`).

> لتشغيل اختبارات PyTest محليًا:
> ```bash
> pytest
> ```

بهذا تكون واجهة الـ API جاهزة للاستخدام من أي عميل خارجي (خدمة، تطبيق موبايل، أو نظام إدارة مستندات).
