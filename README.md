# Price Tracker

[![CI](https://github.com/shlokbhutani13/price_tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/shlokbhutani13/price_tracker/actions/workflows/ci.yml)

Paste a product link, save its price, and check back later to see if it dropped. It's a small FastAPI app, and most of the work went into making the scraping safe and reliable.

**Try it:** [live app](https://price-tracker-3sjc.onrender.com) (free hosting, so the first load can take up to a minute)

## What it does

- Saves a price snapshot from a public product page and keeps the history in SQLite.
- Shows the lowest price seen and the latest change.
- Keeps the last good price if a later check fails.
- Reads [Books to Scrape](https://books.toscrape.com) reliably. On other shops it looks for standard product data (JSON-LD and meta tags), so results vary.

## The safety part

A scraper that fetches any URL a user types can be tricked into hitting internal servers. So it:

- only allows public http/https addresses, and blocks private, local and reserved IPs
- checks every redirect before following it
- only reads HTML pages, up to 2 MB

It doesn't try to get around CAPTCHAs, logins or anti-bot systems.

## API

The web page and the API share the same code.

| Method | Route | What it does |
| --- | --- | --- |
| `POST` | `/api/watches` | Track a product. Body: `{"url": "https://..."}` |
| `POST` | `/api/watches/{id}/refresh` | Check the price again |
| `GET` | `/api/watches/{id}/history` | Price history, latest and lowest price |
| `DELETE` | `/api/watches/{id}` | Stop tracking and delete the history |

Bad or unreadable URLs return `422`. Unknown IDs return `404`.

## Run it locally

You need Python 3.12 or newer.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`. The form has a sample link you can try. To store the database somewhere else, set `PRICE_TRACKER_DB_PATH`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests run fully offline with mocked HTTP and temporary databases. They cover unsafe URLs, redirects, size limits, price parsing, history and the API routes.

## Limits

SQLite is fine for one small server. Running several copies would need a shared database and rate limiting.

## License

MIT
