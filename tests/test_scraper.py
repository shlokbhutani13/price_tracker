import httpx
import pytest

from scraper import (
    MAX_RESPONSE_BYTES,
    ProductResult,
    ScrapeBlocked,
    ScrapeFailed,
    fetch_html,
    parse_money,
    scrape_product,
    validate_public_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/product",
        "http://",
        "http://user:pass@example.com/product",
        "http://localhost/product",
        "http://127.0.0.1/product",
        "http://10.0.0.1/product",
        "http://169.254.1.1/product",
        "http://[::1]/product",
        "http://[fc00::1]/product",
    ],
)
def test_validate_public_url_rejects_unsafe_destinations(url):
    with pytest.raises(ScrapeFailed):
        validate_public_url(url)


def test_validate_public_url_accepts_public_ip():
    assert validate_public_url("https://93.184.216.34/product") == (
        "https://93.184.216.34/product"
    )


@pytest.mark.asyncio
async def test_fetch_html_revalidates_redirect_destinations():
    def handler(request: httpx.Request):
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ScrapeFailed, match="public"):
            await fetch_html("https://93.184.216.34/product", client=client)


@pytest.mark.asyncio
async def test_fetch_html_rejects_non_html_responses():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"price": 12},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ScrapeFailed, match="HTML"):
            await fetch_html("https://93.184.216.34/product", client=client)


@pytest.mark.asyncio
async def test_fetch_html_limits_response_size():
    body = b"x" * (MAX_RESPONSE_BYTES + 1)

    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=body,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ScrapeFailed, match="large"):
            await fetch_html("https://93.184.216.34/product", client=client)


def test_parse_money_handles_symbols_and_commas():
    assert parse_money("Now US $1,299.50") == (1299.50, "$")
    assert parse_money("£51.77") == (51.77, "£")


@pytest.mark.asyncio
async def test_scrape_books_to_scrape_product():
    html = """
    <html>
      <div class="product_main">
        <h1>A Light in the Attic</h1>
        <p class="price_color">£51.77</p>
        <p class="instock availability">In stock</p>
      </div>
    </html>
    """

    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=html,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await scrape_product(
            "https://books.toscrape.com/catalogue/a-light_1/index.html",
            client=client,
        )

    assert result == ProductResult(
        url="https://books.toscrape.com/catalogue/a-light_1/index.html",
        title="A Light in the Attic",
        price=51.77,
        currency="£",
        in_stock=True,
    )


@pytest.mark.asyncio
async def test_scrape_product_reads_nested_json_ld_offer():
    html = """
    <html>
      <head><title>Fallback title</title></head>
      <body>
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@graph": [
              {
                "@type": "Product",
                "name": "Desk Lamp",
                "offers": [{
                  "@type": "Offer",
                  "price": "34.90",
                  "priceCurrency": "USD",
                  "availability": "https://schema.org/InStock"
                }]
              }
            ]
          }
        </script>
      </body>
    </html>
    """

    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=html,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await scrape_product(
            "https://93.184.216.34/lamp?ref=home",
            client=client,
        )

    assert result.title == "Desk Lamp"
    assert result.price == 34.90
    assert result.currency == "USD"
    assert result.in_stock is True


@pytest.mark.asyncio
async def test_scrape_product_reports_block_pages():
    def handler(request: httpx.Request):
        return httpx.Response(
            403,
            headers={"content-type": "text/html"},
            text="Verify you are human",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ScrapeBlocked):
            await scrape_product("https://93.184.216.34/product", client=client)
