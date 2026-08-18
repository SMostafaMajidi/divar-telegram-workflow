# دیوار → تلگرام

Web UI for Divar filters. Watch sends every new ad to Telegram. Send `/best` or «۵ تا بهترین» for a ranked shortlist from active filters.

## Docker

```bash
cp .env.example .env   # fill TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
docker compose up -d --build
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765)

`config.yaml`, `.env`, and `data/` stay on the host so filters, Telegram settings, and seen ads persist.

```bash
docker compose logs -f
docker compose down
```

## Without Docker

```bash
python3 main.py serve
```

The server starts the Telegram bot when `.env` is set.

## Telegram

1. Put the bot token and chat id in `.env`.
2. Open the bot and send `/start`.
3. Start watch from the web page to receive all new ads.
4. Send `۵ تا بهترین` or `/best` for ranked ads (newer year, lower mileage, with photo).

```bash
python3 main.py test
python3 main.py once
```
