# دیوار واچر — سرویس چندمستأجری

پایش آگهی‌های دیوار و ارسال به تلگرام، صفحه اختصاصی و API.

## اجرا

```bash
cp .env.example .env
# TELEGRAM_BOT_TOKEN، ADMIN_USERNAME / ADMIN_PASSWORD و PUBLIC_BASE_URL را پر کنید
docker compose -f deploy/docker-compose.yml up -d --build
```

- خانه: http://127.0.0.1:8765/
- ادمین: http://127.0.0.1:8765/admin/login
- ورود مشتری: http://127.0.0.1:8765/app/login

پایش و ربات با بالا آمدن سرویس خودکار شروع می‌شوند.

## ثبت‌نام مشتری (خودکار)

1. در ربات `/start` بزند.
2. یوزرنیم و رمز دلخواه پنل را بفرستد.
3. با همان مشخصات وارد `/app/login` شود و فیلتر بسازد.
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
