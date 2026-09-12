# دیوار واچر — سرویس چندمستأجری

پایش آگهی‌های دیوار و ارسال به تلگرام، صفحه اختصاصی و API.

## اجرا

```bash
cp .env.example .env
# TELEGRAM_BOT_TOKEN، ADMIN_USERNAME / ADMIN_PASSWORD و PUBLIC_BASE_URL را پر کنید
docker compose -f deploy/docker-compose.yml up -d --build
```

- خانه / ورود مشتری: https://est.rysh.ir/
- ادمین: https://est.rysh.ir/admin/login

پایش و ربات با بالا آمدن سرویس خودکار شروع می‌شوند.

## ثبت‌نام مشتری (خودکار)

1. در ربات `/start` بزند.
2. یوزرنیم و رمز دلخواه پنل را بفرستد.
3. با همان مشخصات در صفحه اصلی وارد شود و فیلتر بسازد.
4. آگهی‌های تازه به چت تلگرام همان کاربر می‌رود.

## API

مشتری کلید داخلی نمی‌بیند. از یوزرنیم/رمز پنل با Basic Auth استفاده می‌کند:

```http
GET /api/v1/listings?limit=50
Authorization: Basic base64(username:password)
```

مستندات داخل پنل: `/app/api`

## ادمین

ورود با `ADMIN_USERNAME` / `ADMIN_PASSWORD`. مدیریت مشتریان و تنظیمات سراسری از `/admin`.

## پوش نوتیف اندروید (FCM)

وقتی پایش آگهی تازه پیدا کند، علاوه بر تلگرام/بله/ایتا، به همهٔ دستگاه‌های ثبت‌شدهٔ همان کاربر push می‌زند (مستقل از `filter_destinations`).

کانفیگ در `.env`:

- `FCM_SERVICE_ACCOUNT_FILE` + `FCM_PROJECT_ID` (HTTP v1، پیشنهادی)
- یا `FCM_SERVER_KEY` (legacy)
- `FCM_DRY_RUN=1` برای تست بدون تماس با Google

اگر FCM تنظیم نباشد، پایش مثل قبل ادامه می‌دهد و فقط push را رد می‌کند.

API مشتری (کوکی `session`):

```http
POST /api/devices/register
{"token":"<fcm>","platform":"android","package":"ir.rysh.workflow"}

GET /api/devices
POST /api/devices/unregister
{"token":"<fcm>"}
DELETE /api/devices/{token}
```

تست دستی:

```bash
FCM_DRY_RUN=1 python scripts/test_fcm_push.py --token SAMPLE_TOKEN
```

