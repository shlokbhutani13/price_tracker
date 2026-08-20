from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import app as app_module
from db import configure_database
from scraper import ProductResult, ScrapeFailed


@pytest.fixture
def client(tmp_path):
    configure_database(tmp_path / "app.db")
    with TestClient(app_module.app) as test_client:
        yield test_client


def redirect_notice(response):
    assert response.status_code == 303
    return parse_qs(urlparse(response.headers["location"]).query)


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_home_has_clear_empty_state(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Track a product" in response.text
    assert "No products tracked yet" in response.text


def test_invalid_url_returns_public_message_without_saving(client):
    response = client.post(
        "/add",
        data={"url": "http://127.0.0.1/private"},
        follow_redirects=False,
    )

    query = redirect_notice(response)
    assert query["kind"] == ["error"]
    assert "public website" in query["notice"][0]
    assert client.get("/").text.count("watch-card") == 0


def test_successful_add_and_duplicate(monkeypatch, client):
    async def fake_scrape(url):
        return ProductResult(url, "Desk Lamp", 34.9, "USD", True)

    monkeypatch.setattr(app_module, "scrape_product", fake_scrape)

    first = client.post(
        "/add",
        data={"url": "https://example.com/lamp?utm_source=test"},
        follow_redirects=False,
    )
    second = client.post(
        "/add",
        data={"url": "https://example.com/lamp?utm_source=again"},
        follow_redirects=False,
    )

    assert redirect_notice(first)["kind"] == ["success"]
    assert redirect_notice(second)["kind"] == ["info"]
    html = client.get("/").text
    assert "Desk Lamp" in html
    assert "USD 34.90" in html
    assert "mini-chart" not in html

    client.post("/refresh/1")
    assert "mini-chart" in client.get("/").text


def test_refresh_missing_watch_returns_info(client):
    response = client.post("/refresh/999", follow_redirects=False)
    query = redirect_notice(response)
    assert query["kind"] == ["info"]
    assert query["notice"] == ["That watch no longer exists."]


def test_refresh_failure_keeps_existing_price(monkeypatch, client):
    async def first_scrape(url):
        return ProductResult(url, "Desk Lamp", 34.9, "USD", True)

    monkeypatch.setattr(app_module, "scrape_product", first_scrape)
    client.post("/add", data={"url": "https://example.com/lamp"})

    async def failed_scrape(url):
        raise ScrapeFailed("No reliable product price was found on this page.")

    monkeypatch.setattr(app_module, "scrape_product", failed_scrape)
    response = client.post("/refresh/1", follow_redirects=False)

    assert redirect_notice(response)["kind"] == ["error"]
    html = client.get("/").text
    assert "USD 34.90" in html
    assert "Check failed" in html
    assert "Out of stock" not in html


def test_delete_removes_watch(monkeypatch, client):
    async def fake_scrape(url):
        return ProductResult(url, "Desk Lamp", 34.9, "USD", True)

    monkeypatch.setattr(app_module, "scrape_product", fake_scrape)
    client.post("/add", data={"url": "https://example.com/lamp"})

    response = client.post("/delete/1", follow_redirects=False)

    assert redirect_notice(response)["kind"] == ["success"]
    assert "No products tracked yet" in client.get("/").text


def test_api_add_refresh_history_and_delete_watch(monkeypatch, client):
    async def first_scrape(url):
        return ProductResult(url, "Desk Lamp", 34.9, "USD", True)

    monkeypatch.setattr(app_module, "scrape_product", first_scrape)
    created = client.post(
        "/api/watches",
        json={"url": "https://example.com/lamp?utm_source=test"},
    )

    assert created.status_code == 201
    watch_id = created.json()["watch"]["id"]
    assert created.json()["watch"]["url"] == "https://example.com/lamp"

    async def refreshed_scrape(url):
        return ProductResult(url, "Desk Lamp", 29.9, "USD", True)

    monkeypatch.setattr(app_module, "scrape_product", refreshed_scrape)
    refreshed = client.post(f"/api/watches/{watch_id}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["watch"]["last_price"] == 29.9

    history = client.get(f"/api/watches/{watch_id}/history")
    assert history.status_code == 200
    assert [point["price"] for point in history.json()["history"]] == [34.9, 29.9]

    deleted = client.delete(f"/api/watches/{watch_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/watches/{watch_id}/history").status_code == 404


def test_api_rejects_unsafe_product_url(client):
    response = client.post("/api/watches", json={"url": "http://127.0.0.1/private"})

    assert response.status_code == 422
    assert "public website" in response.json()["detail"]
