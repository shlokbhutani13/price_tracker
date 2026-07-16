import pytest
import pytest_asyncio

from db import (
    add_watch,
    configure_database,
    delete_watch,
    get_price_stats,
    get_watch,
    init_db,
    list_watches,
    update_watch,
)


@pytest_asyncio.fixture(autouse=True)
async def temporary_database(tmp_path):
    configure_database(tmp_path / "tracker.db")
    await init_db()
    yield


@pytest.mark.asyncio
async def test_add_list_and_get_watch():
    watch_id, created = await add_watch(
        url="https://example.com/lamp",
        title="Desk Lamp",
        price=34.9,
        currency="USD",
        in_stock=True,
    )

    watch = await get_watch(watch_id)
    watches = await list_watches()

    assert created is True
    assert watch is not None
    assert watch.title == "Desk Lamp"
    assert watch.in_stock is True
    assert watches == [watch]


@pytest.mark.asyncio
async def test_add_watch_returns_existing_record_for_duplicate_url():
    first_id, first_created = await add_watch(
        "https://example.com/lamp", "Lamp", 10, "USD", True
    )
    second_id, second_created = await add_watch(
        "https://example.com/lamp", "Lamp", 10, "USD", True
    )

    assert first_created is True
    assert second_created is False
    assert second_id == first_id
    assert len(await list_watches()) == 1


@pytest.mark.asyncio
async def test_update_builds_currency_neutral_price_history():
    watch_id, _ = await add_watch(
        "https://example.com/lamp", "Lamp", 30, "GBP", True
    )
    await update_watch(watch_id, "Lamp", 25, "GBP", True)

    stats = await get_price_stats(watch_id)

    assert stats.count == 2
    assert stats.lowest == 25
    assert stats.latest == 25
    assert stats.previous == 30
    assert stats.direction == "down"
    assert stats.change == 5
    assert [point.price for point in stats.points] == [30, 25]


@pytest.mark.asyncio
async def test_failed_refresh_does_not_create_false_out_of_stock_state():
    watch_id, _ = await add_watch(
        "https://example.com/lamp", "Lamp", 30, "USD", True
    )
    await update_watch(
        watch_id,
        title="Lamp",
        price=None,
        currency=None,
        in_stock=None,
        last_error="The page could not be checked.",
    )

    watch = await get_watch(watch_id)
    stats = await get_price_stats(watch_id)

    assert watch is not None
    assert watch.in_stock is None
    assert watch.last_error == "The page could not be checked."
    assert stats.count == 1


@pytest.mark.asyncio
async def test_delete_removes_watch_and_history():
    watch_id, _ = await add_watch(
        "https://example.com/lamp", "Lamp", 30, "USD", True
    )

    await delete_watch(watch_id)

    assert await get_watch(watch_id) is None
    assert (await get_price_stats(watch_id)).count == 0
