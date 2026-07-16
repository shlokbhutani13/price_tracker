import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4
USER_AGENT = "PriceTracker/1.0 (+https://github.com/shlokbhutani13/price_tracker)"


class ScrapeBlocked(Exception):
    pass


class ScrapeFailed(Exception):
    pass


@dataclass(frozen=True)
class ProductResult:
    url: str
    title: str
    price: float
    currency: str
    in_stock: bool | None


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_money(value: str | None) -> tuple[float | None, str | None]:
    if not value:
        return None, None

    match = re.search(
        r"(US\s*\$|USD|GBP|EUR|\$|£|€)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        clean_text(value),
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None

    currency = match.group(1).replace(" ", "")
    if currency.upper() == "US$":
        currency = "$"

    try:
        return float(match.group(2).replace(",", "")), currency
    except ValueError:
        return None, currency


def _is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def validate_public_url(url: str) -> str:
    value = clean_text(url)
    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"}:
        raise ScrapeFailed("Enter a valid HTTP or HTTPS product URL.")
    if not parsed.hostname:
        raise ScrapeFailed("The URL must include a host.")
    if parsed.username or parsed.password:
        raise ScrapeFailed("URLs containing credentials are not supported.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ScrapeFailed("The URL must point to a public website.")

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        if not literal.is_global:
            raise ScrapeFailed("The URL must point to a public website.")
        return value

    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, UnicodeError, ValueError) as exc:
        raise ScrapeFailed("The website address could not be resolved.") from exc

    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise ScrapeFailed("The URL must point to a public website.")

    return value


async def _read_bounded_html(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        raise ScrapeFailed("The URL did not return an HTML page.")

    declared_size = response.headers.get("content-length")
    if declared_size:
        try:
            if int(declared_size) > MAX_RESPONSE_BYTES:
                raise ScrapeFailed("The page is too large to inspect safely.")
        except ValueError:
            pass

    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ScrapeFailed("The page is too large to inspect safely.")

    encoding = response.encoding or "utf-8"
    return bytes(body).decode(encoding, errors="replace")


async def fetch_html(
    url: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    current_url = validate_public_url(url)
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)

    try:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                async with active_client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ScrapeFailed("The website returned an invalid redirect.")
                        current_url = validate_public_url(urljoin(current_url, location))
                        continue

                    if response.status_code in {401, 403, 429}:
                        raise ScrapeBlocked(
                            f"The website refused automated access (HTTP {response.status_code})."
                        )
                    if response.status_code >= 400:
                        raise ScrapeFailed(
                            f"The website returned HTTP {response.status_code}."
                        )

                    html = await _read_bounded_html(response)
            except ScrapeBlocked:
                raise
            except ScrapeFailed:
                raise
            except httpx.HTTPError as exc:
                raise ScrapeFailed("The website could not be reached.") from exc

            lowered = html.lower()
            if any(
                marker in lowered
                for marker in ("captcha", "verify you are human", "robot check")
            ):
                raise ScrapeBlocked("The website returned a bot-verification page.")

            return html, current_url

        raise ScrapeFailed("The website redirected too many times.")
    finally:
        if owns_client:
            await active_client.aclose()


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _availability(value: Any) -> bool | None:
    text = clean_text(str(value)).lower()
    if not text:
        return None
    if text.endswith("instock") or text.endswith("limitedavailability"):
        return True
    if text.endswith(("outofstock", "soldout", "discontinued")):
        return False
    return None


def _structured_product(
    soup: BeautifulSoup,
) -> tuple[str | None, float | None, str | None, bool | None]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        for item in _walk_json(data):
            offers = item.get("offers")
            if not offers:
                continue

            offer_list = offers if isinstance(offers, list) else [offers]
            for offer in offer_list:
                if not isinstance(offer, dict):
                    continue
                raw_price = offer.get("price", offer.get("lowPrice"))
                if raw_price is None:
                    continue
                try:
                    price = float(str(raw_price).replace(",", "").strip())
                except ValueError:
                    continue

                title = clean_text(item.get("name")) or None
                currency = clean_text(offer.get("priceCurrency")) or None
                return title, price, currency, _availability(offer.get("availability"))

    return None, None, None, None


def _page_title(soup: BeautifulSoup) -> str:
    open_graph = soup.find("meta", property="og:title")
    if open_graph and open_graph.get("content"):
        return clean_text(open_graph["content"])
    heading = soup.find("h1")
    if heading:
        return clean_text(heading.get_text())
    if soup.title:
        return clean_text(soup.title.get_text())
    return "Product"


def _meta_price(soup: BeautifulSoup) -> tuple[float | None, str | None]:
    for attribute, value in (
        ("property", "product:price:amount"),
        ("property", "og:price:amount"),
        ("itemprop", "price"),
    ):
        tag = soup.find("meta", attrs={attribute: value})
        if not tag or not tag.get("content"):
            continue
        try:
            price = float(str(tag["content"]).replace(",", "").strip())
        except ValueError:
            continue

        currency_tag = (
            soup.find("meta", property="product:price:currency")
            or soup.find("meta", property="og:price:currency")
            or soup.find("meta", itemprop="priceCurrency")
        )
        currency = (
            clean_text(currency_tag.get("content"))
            if currency_tag and currency_tag.get("content")
            else None
        )
        return price, currency
    return None, None


async def scrape_product(
    url: str,
    client: httpx.AsyncClient | None = None,
) -> ProductResult:
    html, final_url = await fetch_html(url, client=client)
    soup = BeautifulSoup(html, "lxml")
    hostname = (urlparse(final_url).hostname or "").lower()

    if hostname == "books.toscrape.com":
        title_element = soup.select_one("div.product_main h1")
        price_element = soup.select_one("p.price_color")
        stock_element = soup.select_one("p.instock.availability")
        title = clean_text(title_element.get_text()) if title_element else "Book"
        price, currency = parse_money(
            price_element.get_text() if price_element else None
        )
        if price is None:
            raise ScrapeFailed("The page did not contain a readable book price.")
        return ProductResult(
            url=final_url,
            title=title,
            price=price,
            currency=currency or "£",
            in_stock=bool(stock_element),
        )

    title, price, currency, in_stock = _structured_product(soup)
    if price is None:
        price, currency = _meta_price(soup)
    if price is None:
        price, currency = parse_money(soup.get_text(" ", strip=True))
    if price is None:
        raise ScrapeFailed("No reliable product price was found on this page.")

    return ProductResult(
        url=final_url,
        title=title or _page_title(soup),
        price=price,
        currency=currency or "$",
        in_stock=in_stock,
    )
