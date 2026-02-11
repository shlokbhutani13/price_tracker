import re
import json
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

class ScrapeBlocked(Exception):
    pass

class ScrapeFailed(Exception):
    pass


def _clean_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _parse_money(s: str | None) -> tuple[float | None, str | None]:
    if not s:
        return None, None
    s = _clean_text(s)
    m = re.search(r"(US\s*\$|\$|£|€)\s*([0-9][0-9,]*\.?[0-9]*)", s)
    if not m:
        return None, None
    cur = m.group(1).replace(" ", "")
    num = m.group(2).replace(",", "")
    try:
        return float(num), cur
    except:
        return None, cur


async def _fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=20) as client:
        r = await client.get(url)
        text = r.text

        lowered = text.lower()
        if r.status_code in (401, 403, 429):
            raise ScrapeBlocked(f"Blocked by site (HTTP {r.status_code}).")
        if "captcha" in lowered or "verify you are human" in lowered or "robot check" in lowered:
            raise ScrapeBlocked("Blocked by site (captcha/robot check).")

        if r.status_code >= 400:
            raise ScrapeFailed(f"Failed to fetch page (HTTP {r.status_code}).")

        return text


def _generic_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return _clean_text(og["content"])
    if soup.title and soup.title.text:
        return _clean_text(soup.title.text)
    h1 = soup.find("h1")
    if h1 and h1.get_text():
        return _clean_text(h1.get_text())
    return "Product"


def _generic_price(soup: BeautifulSoup) -> tuple[float | None, str | None]:
    # Try OpenGraph product price tags if present
    for prop in ["product:price:amount", "og:price:amount"]:
        m = soup.find("meta", property=prop)
        if m and m.get("content"):
            try:
                price = float(str(m["content"]).replace(",", "").strip())
                curm = soup.find("meta", property="product:price:currency") or soup.find("meta", property="og:price:currency")
                cur = curm.get("content") if curm and curm.get("content") else None
                return price, cur
            except:
                pass

    # Try JSON-LD offers
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except:
            continue
        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            offers = obj.get("offers")
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict):
                p = offers.get("price")
                cur = offers.get("priceCurrency")
                if p is not None:
                    try:
                        return float(str(p).replace(",", "").strip()), cur
                    except:
                        return None, cur

    # Fallback: scan visible text for a money pattern (best-effort)
    text = soup.get_text(" ", strip=True)
    return _parse_money(text)


async def scrape_product(url: str) -> dict:
    if not url.startswith("http"):
        raise ScrapeFailed("URL must start with http/https")

    host = (urlparse(url).netloc or "").lower()
    html = await _fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    # ✅ Guaranteed demo site: books.toscrape.com
    if "books.toscrape.com" in host:
        title_el = soup.select_one("div.product_main h1")
        price_el = soup.select_one("p.price_color")
        title = _clean_text(title_el.get_text()) if title_el else "Book"
        price_txt = _clean_text(price_el.get_text()) if price_el else None
        price, currency = _parse_money(price_txt)
        if price is None:
            raise ScrapeFailed("Could not read price from the page.")
        return {"url": url, "title": title, "price": price, "currency": currency or "£", "in_stock": True}

    # ✅ Best-effort for other pages (may be blocked)
    title = _generic_title(soup)
    price, currency = _generic_price(soup)

    if price is None:
        raise ScrapeFailed("Unsupported page or price not detectable (some stores block scrapers).")

    return {"url": url, "title": title, "price": price, "currency": currency or "$", "in_stock": True}
