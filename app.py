from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from db import init_db, add_watch, list_watches, update_watch, delete_watch, get_price_stats
from scraper import scrape_product, ScrapeBlocked, ScrapeFailed

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    await init_db()




@app.get('/health')
async def health():
    return {'ok': True}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    rows = await list_watches()

    # attach stats per watch_id
    enriched = []
    for r in rows:
        wid = r[0]
        stats = await get_price_stats(wid, limit=20)
        enriched.append((r, stats))

    return templates.TemplateResponse("index.html", {"request": request, "rows": enriched})


def canonicalize_url(url: str) -> str:
    url = url.strip()
    # strip tracking params (keeps base path)
    if "?" in url:
        base, _ = url.split("?", 1)
        return base
    return url


@app.post("/add")
async def add(url: str = Form(...)):
    url = canonicalize_url(url)

    try:
        data = await scrape_product(url)
        await add_watch(
            url=data["url"],
            title=data["title"],
            price=data["price"],
            currency=data["currency"],
            in_stock=data["in_stock"],
            last_error=None
        )
    except ScrapeBlocked as e:
        await add_watch(url=url, title="Blocked by site", price=None, currency=None, in_stock=False, last_error=str(e))
    except ScrapeFailed as e:
        await add_watch(url=url, title="Could not parse page", price=None, currency=None, in_stock=False, last_error=str(e))
    except Exception as e:
        await add_watch(url=url, title="Error", price=None, currency=None, in_stock=False, last_error=f"Unexpected error: {e}")

    return RedirectResponse("/", status_code=303)


@app.post("/refresh/{watch_id}")
async def refresh(watch_id: int):
    rows = await list_watches()
    row = next((r for r in rows if r[0] == watch_id), None)
    if not row:
        return RedirectResponse("/", status_code=303)

    url = canonicalize_url(row[1])

    try:
        data = await scrape_product(url)
        await update_watch(watch_id, data["price"], data["currency"], data["in_stock"], last_error=None)
    except ScrapeBlocked as e:
        await update_watch(watch_id, None, None, False, last_error=str(e))
    except ScrapeFailed as e:
        await update_watch(watch_id, None, None, False, last_error=str(e))
    except Exception as e:
        await update_watch(watch_id, None, None, False, last_error=f"Unexpected error: {e}")

    return RedirectResponse("/", status_code=303)


@app.post("/delete/{watch_id}")
async def delete(watch_id: int):
    await delete_watch(watch_id)
    return RedirectResponse("/", status_code=303)
