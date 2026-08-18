# دیوار → تلگرام

Watch sends every new ad to Telegram. Send `/best` or «۵ تا بهترین» for a ranked shortlist from active filters.

```
config/     filters and send settings
data/       seen ads and city cache
src/        Python app
web/        UI
deploy/     Docker
.env        Telegram token and chat id
```

## Run

```bash
cp .env.example .env   # fill TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
docker compose -f deploy/docker-compose.yml up -d --build
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765)

Start watch from the web page. In Telegram, send `/start`, then `/best` or «۵ تا بهترین».

```bash
docker compose -f deploy/docker-compose.yml logs -f
docker compose -f deploy/docker-compose.yml down
```
