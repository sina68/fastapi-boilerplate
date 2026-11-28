# گزارش انطباق ساختار — fastapi-boilerplate

تاریخ بررسی: ۲۰۲۶-۱۱-۲۸ · کامیت بررسی‌شده: `663196a first commit`

مرجع‌ها:

- سند «MCI Intelligence — سند فاز ۱» (Google Doc)، به‌خصوص «پیوست الف — متمم فنی».
- سرویس‌های مرجع تیم: `notification-python` و `translation`.
- چارت‌ها: `bw3-ops/prod/{notification-python,translation,url-reputation-*-job}` روی چارت مشترک `zarebin` (نسخه 2.2.0).
- [docs/architecture.md](architecture.md) — «سند معماری فنی پلتفرم جمع‌آوری و پایش منابع»، نسخه 1.0.

وضعیت فعلی: `make test` ۱۲۱ تست سبز، `make lint` (ruff + mypy strict) سبز.

علامت‌ها: 🔴 مغایرت ساختاری (قبل از شروع فیچرها حل شود) · 🟡 مغایرت متوسط · 🟢 مطابق یا بهتر از مرجع.

---

## ۱. خلاصه

boilerplate از نظر کیفیت کد، امنیت و تست از سرویس‌های مرجع جلوتر است، ولی **شکل** آن با تیم فرق دارد: چیدمان لایه‌ای `src/app/...` به‌جای slice-محور `src/api/<slice>/`، ابزار pip/hatchling به‌جای `uv` + `uv.lock`، پایتون ۳.۱۲ به‌جای ۳.۱۴، CI بدون build/scan/deploy، و هیچ چارت Helm. چون قرار است بیرون از شبکه MCI مستقر شود، وابستگی‌های داخلی تیم (`zarebin-common`، `repo.mci.dev`، `docker.mci.dev`، `cicd-template`، `bw3-ops`) هم باید با معادل داخل ریپو جایگزین شوند.

دو سند مرجع در ۱۷ مورد با هم تعارض دارند (بخش ۳)؛ چهار مورد تصمیم گرفته شد (تاپیک‌ها و تکرار بین منابع در همین فاز، صف بر اساس مسیر شبکه، ساختار تیم با uv). بقیه هنوز باز است؛ تا نام جدول‌ها و رابط connector تصمیم نگیرند، migration اول جدول‌های اصلی نباید ساخته شود. از الزامات architecture.md، fetcher امن در برابر SSRF هنوز در کد نیست و پیش‌نیاز همه connectorهاست.

پیشنهاد: قبل از هر فیچر، یک MR `refactor(structure)` بدون تغییر رفتار (بخش ۸).

---

## ۲. مقایسه با سرویس‌های مرجع

### چیدمان کد

| موضوع | مرجع (notification / translation) | boilerplate | وضعیت | اقدام |
|---|---|---|---|---|
| ریشه پکیج | `src/` با پکیج‌های تخت، import به شکل `from core.config import settings` | `src/app/...`، import به شکل `from app.core...` | 🔴 | انتقال به `src/<pkg>`؛ `PYTHONPATH=src` |
| ماژول‌بندی | slice: `src/api/<domain>/{router,schemas,models,repository,service,dependencies,metrics}.py` | لایه‌ای: `api/v1/`, `services/`, `repositories/`, `schemas/`, `models/` | 🔴 | هر resource یک پوشه زیر `src/api/` |
| service / repository | کلاس؛ repository با `session` در `__init__`، service با repository در `__init__`؛ وصل‌شده در `dependencies.py` | تابع‌های ماژولی که `session` را آرگومان می‌گیرند | 🔴 | کلاس + `dependencies.py` |
| application factory | `src/main.py` → `utils/app.py:create_app()` با `add_api_routers`, `add_offline_docs`, `add_general_exception_handlers` | `src/app/main.py` همه‌چیز در یک فایل | 🟡 | جدا کردن به `utils/app.py` |
| مدیریت DB | `adapters/database.py` → `DatabaseManager` (singleton، `yield_session` که آخر درخواست commit و در خطا rollback می‌کند، unique violation → 409) | `db/session.py` با engine تنبل؛ commit داخل service | 🔴 | `DatabaseManager` + قانون تراکنش AGENTS.md §۳ |
| Base مدل | `models/__init__.py:BaseModel`، naming: `%(table_name)s_pkey`, `_key`, `_fkey`, `_idx` | `db/base.py:Base`، naming: `pk_`, `uq_`, `fk_`, `ix_` | 🟡 | convention تیم؛ چون DB هنوز تولیدی نیست، مایگریشن‌ها بازتولید شوند |
| alembic | `src/alembic.ini` + `src/alembic/`، اجرا با `alembic -c src/alembic.ini` | ریشه ریپو | 🟡 | انتقال به `src/` |
| اسکریپت/CronJob | `src/scripts/*.py` با `python -m scripts.x` | ندارد (Celery beat) | 🟢/🟡 | `scripts/` برای کارهای یک‌باره؛ زمان‌بند دقیقه‌ای همان Celery بماند |
| تست‌ها | `tests/<domain>/...`، `conftest` مسیر `src` را اضافه می‌کند | تخت در `tests/` | 🟡 | همراه refactor |
| docs آفلاین | Swagger/ReDoc از `src/static/docs` (شبکه بدون اینترنت) | CDN پیش‌فرض FastAPI، در production خاموش | 🔴 | برای استقرار داخلی لازم است؛ کپی از notification |

### رفتار مشترک (در مرجع از `zarebin-common`)

| موضوع | مرجع | boilerplate | وضعیت | اقدام |
|---|---|---|---|---|
| هدر trace | `x-trace-id` (`TraceIdMiddleware`) | `X-Request-ID` | 🟡 | تغییر نام هدر |
| فرمت خطا | RFC 7807 (`type,title,status,detail,instance`)، `detail` فارسی | RFC 9457 + فیلد `code`، `detail` انگلیسی | 🟡 | `detail` فارسی برای پنل، `code` نگه داشته شود |
| کلاس خطا | `DetailedHTTPException` با `STATUS_CODE` | `AppError` با `status_code`, `code` | 🟡 | هم‌شکل کردن نام‌ها در `core/exceptions.py` |
| متریک HTTP | per-slice: `create_api_metrics_set` + `route_class`، `/metrics` با `make_asgi_app` | یک `MetricsMiddleware` سراسری | 🟡 | معادل داخلی per-slice |
| لاگ | JSON در `/home/app/logs/app.log` (loghandler چارت از فایل می‌خواند) + کنسول | JSON روی stdout | 🟡 | stdout پیش‌فرض، file handler با env برای collectorهای فایل‌محور |
| `zarebin-common` | dependency از `repo.mci.dev` | ندارد | ⚠️ | بیرون از MCI در دسترس نیست؛ معادل‌ها داخل ریپو با همان نام‌ها (فرض؛ تصمیم §۷) |

### پیکربندی

| موضوع | مرجع | boilerplate | وضعیت | اقدام |
|---|---|---|---|---|
| DB env | `POSTGRES_USER/PASSWORD/DB/HOST/PORT` (+ `POSTGRES_URL`)؛ password بدون پیش‌فرض | یک `DATABASE_URL` با پسورد پیش‌فرض `postgres` | 🔴 | متغیرهای جدا (با الگوی `secretKeyRef` چارت می‌خواند) |
| پروفایل | `ACTIVE_PROFILE` (dev/stage/prod) یا `ENVIRONMENT` | `ENVIRONMENT` (development/test/production) | 🟡 | افزودن `stage` |
| prefix | `BASE_PATH` واقعی (`/notification`) شامل health و metrics | `API_PREFIX=/api/v1` فقط برای API | 🟡 | تصمیم §۷ (به مسیریابی Kong بستگی دارد) |
| health | `/healthcheck/{liveness,readiness,postgres}` یا `/health/...` | `/health/{liveness,readiness}` | 🟢/🟡 | یکی از دو الگو، ثابت در چارت |

### ابزار، Docker، CI

| موضوع | مرجع | boilerplate | وضعیت | اقدام |
|---|---|---|---|---|
| Python | `3.14.7` در `.python-version`، `>=3.14,<3.15` | `>=3.11`، Docker و CI روی 3.12 | 🔴 | ۳.۱۴؛ سازگاری celery/sqladmin/argon2 چک شود |
| مدیریت پکیج | `uv` + `uv.lock` commit‌شده، `[dependency-groups]`، `package = false` | hatchling + `optional-dependencies`؛ بدون lock؛ `make install` با `uv pip install -e` | 🔴 | `uv sync --frozen` |
| فرمت/لینت | darker + isort + ruff، `ignore I001` | ruff check + ruff format، mypy strict | 🟢 | ruff خالص ساده‌تر است و mypy strict بهتر؛ نگه داریم |
| Dockerfile | `python:3.14.7-slim`، `WORKDIR /home/app`، `PYTHONPATH=/home/app/src`، `TZ=Asia/Tehran`، `uv sync --frozen --no-dev`، پوشه logs | `python:3.12-slim` از Docker Hub، `/app`، `pip install .`، بدون TZ | 🔴 | بازنویسی طبق `.claude/rules/ci-docker.md` |
| entrypoint | انتظار برای Postgres، `alembic -c src/alembic.ini upgrade head`، uvicorn | migration پیش‌فرض روشن، بدون انتظار DB، `exec "$@"` | 🟡 | `exec "$@"` (برای worker/beat) و یک worker (🟢) نگه داشته شود؛ انتظار DB اضافه؛ در k8s migration در Job |
| docker-compose | image از `docker.mci.dev` | Docker Hub | 🟡 | registry متغیر |
| GitLab CI | `quality → build → scan → deploy`؛ build روی dev/stage/tag؛ trigger به `bw3-ops` | فقط `lint`, `test`, `migrations` | 🔴 | افزودن build/scan/deploy (GitOps برای Argo CD)؛ تست‌ها حتماً بمانند |
| MR templates | `.gitlab/merge_request_templates/{feature,bugfix,improvement}.md` | نداشت | 🟢 | **اضافه شد** (با چک‌لیست) |
| Grafana | `grafana/<service>-dashboard.json` | ندارد؛ فقط `deploy/prometheus/alerts.yml` | 🟡 | داشبورد (WBS G2) |

### Helm

| موضوع | مرجع | boilerplate | وضعیت | اقدام |
|---|---|---|---|---|
| چارت | `bw3-ops/prod/<app>/` با dependency به `zarebin` 2.2.0 | **ندارد** | 🔴 | چارت مستقل در `deploy/helm/<service>/` با همان کلیدهای values (`.claude/rules/helm.md`) |
| componentها | فقط api (+ CronJob خام) | api + worker + beat در compose | 🔴 | چهار component: `api`، `scheduler` (۱ replica، Recreate)، `worker-domestic`، `worker-egress` |
| migration | داخل entrypoint هر pod | داخل entrypoint | 🟡 | Helm hook Job تا replicaها هم‌زمان migrate نکنند |

---

## ۳. تعارض‌های دو سند (Google Doc ↔ architecture.md)

این‌ها در AGENTS.md با **⚖ pending** علامت خورده‌اند و تا ستون «تصمیم» پر نشود، پیاده‌سازی نمی‌شوند. ستون «پیشنهاد» نظر من است، نه تصمیم.

| # | موضوع | Google Doc (پیوست الف) | architecture.md | پیشنهاد | تصمیم |
|---|---|---|---|---|---|
| 1 | تکرار بین منابع | پیوند با `duplicate_of` (canonical_url یا content_hash مشترک) — سناریوی ۴.۳ و قابلیت Must | هر دو نسخه نگه داشته می‌شود؛ خارج از MVP (§11) | — | ✅ **در همین فاز** (Google Doc): هر دو نسخه حفظ، دومی با `duplicate_of` به اولی پیوند؛ فقط تطابق دقیق canonical_url یا content_hash |
| 2 | تاپیک‌ها | `topic`، `source_topic`، `item_topic` با `origin`؛ فیلتر تاپیک Must | اصلاً نیست (فقط «دسته‌بندی در صورت تعریف دستی») | — | ✅ **در همین فاز** (Google Doc): `topic`، `source_topic`، `item_topic` با `origin` |
| 3 | موتور جستجو | OpenSearch/ES با analyzer فارسی (تصمیم در R4) | PostgreSQL FTS + GIN + trigram؛ موتور جدا فقط با benchmark (§14) | architecture.md با interface جدا؛ R4 همین benchmark باشد | |
| 4 | تفکیک صف | `domestic` / `egress` بر اساس مسیر شبکه (تلگرام فیلتر است) | `default` / `http_fetch` / `browser_fetch` فقط در صورت نیاز (§21) | — | ✅ **اجباری**: صف‌های `domestic` / `egress` بر اساس مسیر شبکه؛ صف browser فقط در صورت نیاز، جدا برای هر گروه |
| 5 | مسیر خروجی تلگرام | ریسک اصلی؛ پروکسی خروجی (R2) | ذکر نشده؛ روش دسترسی تلگرام تصمیم باز (§26.1) | باید در architecture.md اضافه شود | ✅ با تصمیم ۴ پوشش داده شد؛ روش دسترسی (t.me/s یا اکانت) هنوز باز |
| 6 | قفل scheduler | قفل توزیع‌شده، یک نمونه فعال | claim اتمیک در Postgres با `FOR UPDATE SKIP LOCKED`، قابل بازیابی (§6.2) | architecture.md + beat تک‌نمونه؛ ستون lease (مثل `claimed_until`) لازم است و در سند نیامده | فعلاً پیشنهاد در قوانین اعمال شده؛ قابل بازنگری |
| 7 | خطاهای پیاپی | ۲ → error، ۱۰ → stopped (غیرفعال خودکار) | آستانه → «نیازمند بررسی»؛ غیرفعال‌سازی خودکار الزامی نیست و قابل تنظیم (§17.4) | architecture.md با آستانه‌های Google Doc به‌عنوان مقدار پیش‌فرض | |
| 8 | نام جدول‌ها | `source`، `item`، `crawl_run`، cursor داخل `source` | `sources`، `items`، `source_runs`، جدول جدا `source_checkpoints` | architecture.md (جمع + checkpoint جدا) | |
| 9 | فیلدهای منبع | `locator`، `network_group`، `interval_seconds`، `backfill_limit`، `health_status` | `url`، `enabled`، `interval_minutes`، `last_run_at`؛ سلامت از تاریخچه محاسبه می‌شود | اجتماع هر دو: `locator` (تلگرام URL ندارد)، `backfill_limit`، صف/گروه شبکه | |
| 10 | رابط Connector | `type`, `config_schema`, `network_group`, `test()`, `fetch(config, cursor) -> (items, cursor)` | `fetch(source, checkpoint)` + `parse(raw)` (§8.1) | ترکیب: `fetch` + `parse` + `config_schema` (فرم پنل از آن ساخته می‌شود) — در `.claude/rules/connectors.md` | |
| 11 | Retry روی 429 | فقط شبکه و 5xx؛ 4xx نه | 429 هم موقت است (§6.3) | architecture.md (با `Retry-After`) | |
| 12 | Playwright | نیست (trafilatura و selector) | برای سایت‌های JS، آخرین اولویت، worker جدا (§8.5) | architecture.md، فقط وقتی منبع واقعی نیازش دارد | |
| 13 | نسخه‌های محتوا | ویرایش پست → به‌روزرسانی و ایندکس مجدد | جدول نسخه فقط برای تغییر واقعی + مقایسه در پنل (§12، §15.5) | architecture.md | |
| 14 | ذخیره خام | `raw_ref` + MinIO اختیاری؛ D4 تصویر بندانگشتی | `raw_data` در Postgres؛ بدون Object Storage و بدون رسانه | architecture.md | |
| 15 | استقرار | Kubernetes، Helm، Argo CD، GitLab CI، Kong، EFK | فقط فهرست componentها؛ از k8s/CI/Helm حرفی نیست | Google Doc + چارت مستقل (`.claude/rules/helm.md`) | |
| 16 | نقش‌ها | Admin و Viewer، شاید SSO | تصمیم باز (§26.8) | Google Doc | |
| 17 | ساختار پوشه backend | — | `backend/app/{api/routes, modules/, services/, connectors/, processing/, tasks/, scheduler/}` + `migrations/` + `requirements/` (§18) | — | ✅ ساختار تیم با `uv` + `uv.lock` (AGENTS.md §2)؛ `connectors/` و `processing/` پکیج جدا |

### ایرادهای خود architecture.md (برای نویسنده سند)

- §18 منطق را در سه جا پخش می‌کند (`modules/`، `services/`، `api/routes`) و `requirements/` با `pyproject.toml` + `uv.lock` تیم نمی‌خواند.
- §6.2 می‌گوید claim باید «قابل بازیابی» باشد ولی ستون یا مکانیزم lease در مدل `sources` / `source_runs` نیامده.
- §6.4 وضعیت `partial` تعریف ندارد (چه زمانی partial است و نه failed؟).
- §11 unique روی `source_id + content_hash`، دو پست واقعاً یکسان از یک منبع (مثلاً اطلاعیه تکراری با تاریخ متفاوت) را رد می‌کند؛ رفتار مطلوب مشخص شود.
- unique روی `source_id + content_hash` (§11): رفتار برای دو پست واقعاً یکسان از یک منبع **باید مشخص شود** (رد شود، به‌عنوان آیتم جدید ثبت شود، یا به‌روزرسانی حساب شود). تا مشخص شدن، در قوانین `content_hash` ایندکس است نه unique.
- `rss` و `atom` دو type جدا شده‌اند، در حالی که یک connector (feedparser) هر دو را پوشش می‌دهد.
- فیلتر بودن تلگرام و مسدودسازی IP خارجی توسط سایت‌های ایرانی (دو ریسک اصلی Google Doc) اصلاً مطرح نشده.
- §20.4 تست Celery با broker واقعی را می‌خواهد؛ باید در job جدای integration باشد تا `make test` سریع و بدون سرویس بماند (همین در قوانین آمده).

### architecture.md ↔ کد فعلی

| مورد | وضعیت در boilerplate |
|---|---|
| FastAPI، SQLAlchemy async، PostgreSQL، Redis، Celery + beat، Pytest (§3) | 🟢 موجود |
| Liveness / Readiness (§17.3) | 🟢 API؛ 🔴 health check برای worker و beat نیست |
| Metrics و alerting (§17.2) | 🟢 زیرساخت هست؛ متریک‌های pipeline نیست |
| HTTPX در runtime (§3) | 🔴 فقط dev dependency است |
| Fetcher امن در برابر SSRF (§16) | 🔴 نیست — از الزامات فاز ۱ |
| Rate limit دامنه با Redis (§16.3) | 🟡 rate limit فقط برای ورودی API (per IP) |
| Playwright (§8.5) | ندارد (فقط در صورت نیاز) |
| مدل `items` (§9) | 🔴 تعارض با نمونه `items` مالک‌دار boilerplate |
| `source_runs`، `source_checkpoints`، claim با `SKIP LOCKED` | ندارد |
| Retry تسک‌ها | 🔴 `autoretry_for=(Exception,)` — با تفکیک موقت/دائمی §6.3 جور نیست |
| Auth / نقش‌ها (§26.8) | JWT + RBAC کامل؛ اگر تصمیم سبک‌تر باشد بیش از نیاز است |
| آپلود فایل | خارج از محدوده (§2.2: دانلود رسانه و Object Storage نه) |
| sqladmin | پنل اصلی React است (§15)؛ sqladmin فقط ابزار ops |

## ۴. چیزهایی که در boilerplate بهتر از مرجع است (نگه داریم)

- اجرای `pytest` و `mypy --strict` در CI (CI مرجع‌ها فقط ruff دارد).
- job `migrations` روی Postgres واقعی: `upgrade` / `check` / `downgrade` / `upgrade`، و چک یک head.
- `redact()` برای لاگ‌ها، هدرهای امنیتی، سقف حجم body، CORS سخت در production، secret بدون پیش‌فرض.
- `tests/test_alerting.py` که alert و نام متریک را هم‌گام نگه می‌دارد.
- کاربر non-root در image، `WEB_CONCURRENCY=1` (همان درسی که notification در `b5eac5a` گرفت).
- مستند قوانین برای agent (حالا به `AGENTS.md` تیمی تبدیل شد).

## ۵. ایرادهای پروژه‌های مرجع (کپی نشوند)

- `translation/entrypoint.sh` هنگام انتظار برای DB مقدار `POSTGRES_PASSWORD` را در stderr چاپ می‌کند؛ پسورد وارد لاگ‌های pod می‌شود. باید در خود translation هم اصلاح شود.
- `translation` با `--workers 2` اجرا می‌شود؛ همان مشکل شمارنده‌های per-process که notification رفع کرد.
- `translation` Dockerfile کاربر non-root ندارد و `chmod 777 logs` می‌زند؛ `mypy.ini` روی 3.12 است با runtime 3.14.
- `notification-python`: `NotFoundException` کد 403 برمی‌گرداند (برای سازگاری با Java)؛ در این پروژه 404 درست است.
- مقدارهای `bw3-ops`: `SENTRY_DSN` متن ساده در values است؛ اینجا از Secret خوانده شود.
- CI هر دو سرویس `pytest` را اجرا نمی‌کند.

## ۶. ایرادهای خود boilerplate (غیر از شکل)

- `CLAUDE.md` فقط **لینک** به `AGENTS.md` داشت؛ Claude Code لینک را خودکار نمی‌خواند. **اصلاح شد** (`@AGENTS.md` import).
- 🔴 **باید درست شود:** کامنت `entrypoint.sh` می‌گوید «alembic advisory lock می‌گیرد»؛ Alembic به‌طور پیش‌فرض قفل نمی‌گیرد، پس migration هم‌زمان چند replica واقعاً race دارد. اصلاح: `pg_advisory_lock` داخل `alembic/env.py` دور `run_migrations()`، کامنت اصلاح شود، و در Kubernetes migration فقط در Helm Job.
- `DATABASE_URL` پیش‌فرض با پسورد `postgres` در `Settings` (در production باید fail-closed باشد، مثل `JWT_SECRET`).
- retry تسک‌ها روی `autoretry_for=(Exception,)` است؛ برای crawl طبق سند فقط خطای شبکه و 5xx retry شود.

## ۷. تصمیم‌های باز

اول تعارض‌های باز §۳ (مهم‌ترها: ۳، ۸، ۹، ۱۰، و unique روی content_hash). بعد این‌ها (پیش‌فرض داخل پرانتز در AGENTS.md اعمال شده):

1. **`zarebin-common` و زیرساخت داخلی MCI** در محیط جدید در دسترس است؟ (پیش‌فرض: نه؛ معادل داخل ریپو با همان نام‌ها.)
2. **احراز هویت**: خود سرویس (JWT/RBAC فعلی + نقش `viewer`) یا Kong/SSO جلوی سرویس؟ (پیش‌فرض: فعلی + `viewer`.)
3. **prefix مسیرها**: `BASE_PATH` به سبک notification، `/api/v1` فعلی، یا بدون prefix مطابق Google Doc؟ (پیش‌فرض: `BASE_PATH` واحد که health و metrics هم زیرش باشند.)
4. **محل چارت**: داخل همین ریپو (`deploy/helm/`) یا ریپوی ops جدا برای Argo CD؟ (پیش‌فرض: همین ریپو.)
5. **registry و package index** محیط جدید؟ (در CI و Dockerfile به‌صورت متغیر.)
6. موارد §26 architecture.md (روش دسترسی تلگرام، بازه‌ها، batch، retention، آستانه‌ها، robots، کتابخانه extraction).

## ۸. ترتیب پیشنهادی MRها

1. `refactor(structure): move to src/<pkg> slice layout` — بدون تغییر رفتار، همه تست‌ها سبز؛ نقشه مسیر بخش ۹.
2. `build(deps): switch to uv lockfile and python 3.14` — `uv.lock`، `.python-version`، Makefile با `uv run`.
3. `fix(migrations): take a postgres advisory lock while migrating` — رفع race مایگریشن هم‌زمان و اصلاح کامنت غلط `entrypoint.sh`.
4. `refactor(core): align trace id, errors, metrics, db manager, config with team services` — `x-trace-id`، problem-details فارسی، metrics per-slice، `DatabaseManager`، متغیرهای `POSTGRES_*`، docs آفلاین.
5. `build(docker): align Dockerfile and entrypoint` — `/home/app`، TZ، انتظار DB، `RUN_MIGRATIONS`.
6. `feat(helm): add self-contained chart` + `ci: add build, scan and deploy stages`.
7. `refactor(item): drop example items/uploads slices` (یا تغییر نام) قبل از ساخت جدول `items` سند.
8. `feat(fetcher): ssrf-safe http adapter` — پیش‌نیاز همه connectorها (architecture.md §16).
9. فیچرها به ترتیب §24 architecture.md (Source Registry ← Scheduler/Runs ← Connectors ← Processing ← Persistence ← Search)، بعد از ثبت تصمیم‌های §۳.

## ۹. نقشه مسیر قدیم → جدید

| فعلی | هدف |
|---|---|
| `src/app/main.py` | `src/main.py` + `src/utils/app.py` |
| `src/app/core/*` | `src/core/*` |
| `src/app/db/session.py` | `src/adapters/database.py` (`DatabaseManager`) |
| `src/app/db/redis.py` | `src/adapters/redis.py` |
| `src/app/db/base.py` | `src/models/__init__.py` (`BaseModel`) |
| `src/app/middlewares/*` | `src/middlewares/*` |
| `src/app/api/v1/health.py` | `src/core/healthcheck.py` |
| `src/app/api/v1/<x>.py` | `src/api/<x>/router.py` |
| `src/app/services/<x>.py` | `src/api/<x>/service.py` |
| `src/app/repositories/<x>.py` | `src/api/<x>/repository.py` |
| `src/app/schemas/<x>.py` | `src/api/<x>/schemas.py` |
| `src/app/models/<x>.py` | `src/api/<x>/models.py` |
| `src/app/api/deps.py` | `src/api/<x>/dependencies.py` + `src/api/auth/dependencies.py` (`CurrentUser`, `AdminUser`) |
| `src/app/admin/` | `src/admin/` |
| `src/app/worker/` | `src/worker/` |
| `src/app/cli.py` | `src/scripts/promote.py` (`python -m scripts.promote`) |
| `alembic.ini`, `alembic/` | `src/alembic.ini`, `src/alembic/` |
| `tests/test_<x>.py` | `tests/<x>/test_*.py` |
