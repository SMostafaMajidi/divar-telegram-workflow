# دیوار → تلگرام

Web UI for Divar filters. In Telegram, send `/best` or «۵ تا بهترین» to get the top listings from active filters instead of a flood of ads.

## Web UI

```bash
cd /home/mostafa/Documents/train/workflow
python3 main.py serve
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765)

The server also starts the Telegram bot when `.env` is set.

## Telegram

1. Put the bot token and chat id in `.env`.
2. Open the bot and send `/start`.
3. Send `۵ تا بهترین` or `/best` to receive 5 ranked ads (newer year, lower mileage, with photo).

```bash
python3 main.py test
python3 main.py once
```
