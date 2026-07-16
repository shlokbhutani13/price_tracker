# Price Tracker

Price Tracker is a small FastAPI application for saving product-price snapshots from public web pages. It demonstrates the parts of scraping that matter in a backend project: URL validation, bounded HTTP requests, structured metadata parsing, controlled failures, SQLite history, and a server-rendered interface.

[View the live application](https://price-tracker-3sjc.onrender.com)

## What it does

- accepts public HTTP and HTTPS product URLs
- blocks local, private, link-local, reserved, and credential-bearing destinations
- validates every redirect before following it
- limits responses to HTML pages up to 2 MiB
- reads Books to Scrape pages reliably
- prefers JSON-LD and product metadata on other sites
- stores price snapshots in SQLite
- shows the lowest observed price and the latest movement
- keeps the last valid price when a later check fails

It does not attempt to bypass CAPTCHAs, authentication, rate limits, or store anti-bot systems. Support for arbitrary retail sites is best effort because page structure and access policies differ.

## Run locally

Use Python 3.12 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`. A working sample URL is available in the form.

The database defaults to `tracker.db`. Set `PRICE_TRACKER_DB_PATH` to use another location:

```bash
PRICE_TRACKER_DB_PATH=/tmp/price-tracker.db uvicorn app:app
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests use mocked HTTP transports and temporary SQLite files. They cover unsafe URL rejection, redirects, response limits, metadata extraction, database history, duplicate watches, and route behavior.

## Structure

```text
app.py                 FastAPI routes and presentation helpers
scraper.py             URL safety, fetching, and product extraction
db.py                  SQLite records and price-history queries
templates/index.html   Server-rendered interface
static/styles.css      Responsive styling
tests/                  Scraper, database, and route tests
```

## Deployment notes

The application exposes `GET /health` and starts with:

```bash
uvicorn app:app --host 0.0.0.0 --port "$PORT"
```

SQLite is suitable for this single-instance demonstration. A production service with multiple instances would need shared persistent storage and a distributed rate limit.

## License

MIT
