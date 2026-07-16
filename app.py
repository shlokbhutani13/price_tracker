import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db import (
    add_watch,
    delete_watch,
    get_price_stats,
    get_watch,
    init_db,
    list_watches,
    mark_check_failed,
    update_watch,
)
from scraper import ScrapeBlocked, ScrapeFailed, scrape_product

BASE_DIR = Path(__file__).resolve().parent
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Price Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query, doseq=True),
            "",
        )
    )


def redirect_home(notice: str, kind: str) -> RedirectResponse:
    query = urlencode({"notice": notice, "kind": kind})
    return RedirectResponse(f"/?{query}", status_code=303)


def format_price(currency: str | None, value: float | None) -> str:
    if value is None:
        return "—"
    label = currency or ""
    separator = "" if label in {"$", "£", "€"} else " "
    return f"{label}{separator}{value:.2f}".strip()


def trend_text(stats, currency: str | None) -> str:
    if stats.direction == "down":
        return f"Down {format_price(currency, stats.change)} since the last check"
    if stats.direction == "up":
        return f"Up {format_price(currency, stats.change)} since the last check"
    if stats.direction == "stable":
        return "No change since the last check"
    return "Add another snapshot to see a trend"


def chart_bars(stats) -> list[dict]:
    if len(stats.points) < 2:
        return []
    values = [point.price for point in stats.points]
    minimum = min(values)
    maximum = max(values)
    spread = maximum - minimum
    return [
        {
            "height": 55 if spread == 0 else 28 + ((point.price - minimum) / spread) * 62,
            "price": point.price,
            "checked_at": point.checked_at,
        }
        for point in stats.points
    ]


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    notice: str | None = None,
    kind: str | None = None,
):
    tracked = []
    for watch in await list_watches():
        stats = await get_price_stats(watch.id, limit=20)
        tracked.append(
            {
                "watch": watch,
                "stats": stats,
                "price_text": format_price(watch.currency, watch.last_price),
                "lowest_text": format_price(watch.currency, stats.lowest),
                "trend_text": trend_text(stats, watch.currency),
                "bars": chart_bars(stats),
            }
        )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "tracked": tracked,
            "notice": notice,
            "notice_kind": kind if kind in {"success", "error", "info"} else "info",
        },
    )


@app.post("/add")
async def add(url: str = Form(...)):
    candidate = canonicalize_url(url)
    try:
        product = await scrape_product(candidate)
        _, created = await add_watch(
            url=product.url,
            title=product.title,
            price=product.price,
            currency=product.currency,
            in_stock=product.in_stock,
        )
    except (ScrapeBlocked, ScrapeFailed) as exc:
        return redirect_home(str(exc), "error")
    except Exception:
        logger.exception("Unexpected error while adding a product watch")
        return redirect_home("The product could not be added right now.", "error")

    if not created:
        return redirect_home("That product is already being tracked.", "info")
    return redirect_home("Product added.", "success")


@app.post("/refresh/{watch_id}")
async def refresh(watch_id: int):
    watch = await get_watch(watch_id)
    if watch is None:
        return redirect_home("That watch no longer exists.", "info")

    try:
        product = await scrape_product(watch.url)
        await update_watch(
            watch_id=watch_id,
            title=product.title,
            price=product.price,
            currency=product.currency,
            in_stock=product.in_stock,
        )
    except (ScrapeBlocked, ScrapeFailed) as exc:
        await mark_check_failed(watch_id, str(exc))
        return redirect_home(str(exc), "error")
    except Exception:
        logger.exception("Unexpected error while refreshing watch %s", watch_id)
        message = "The product could not be checked right now."
        await mark_check_failed(watch_id, message)
        return redirect_home(message, "error")

    return redirect_home("Price refreshed.", "success")


@app.post("/delete/{watch_id}")
async def delete(watch_id: int):
    await delete_watch(watch_id)
    return redirect_home("Watch removed.", "success")
