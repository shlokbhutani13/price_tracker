import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

DATABASE_PATH = Path(os.getenv("PRICE_TRACKER_DB_PATH", "tracker.db"))


@dataclass(frozen=True)
class Watch:
    id: int
    url: str
    title: str
    last_price: float | None
    currency: str | None
    in_stock: bool | None
    last_checked: str
    last_error: str | None


@dataclass(frozen=True)
class PricePoint:
    price: float
    checked_at: str


@dataclass(frozen=True)
class PriceStats:
    count: int
    lowest: float | None
    latest: float | None
    previous: float | None
    direction: str
    change: float | None
    points: tuple[PricePoint, ...]


def configure_database(path: str | Path) -> None:
    global DATABASE_PATH
    DATABASE_PATH = Path(path)


@asynccontextmanager
async def _connection():
    database = await aiosqlite.connect(DATABASE_PATH)
    database.row_factory = aiosqlite.Row
    await database.execute("PRAGMA foreign_keys = ON")
    try:
        yield database
    finally:
        await database.close()


def _availability(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _watch(row: aiosqlite.Row) -> Watch:
    return Watch(
        id=row["id"],
        url=row["url"],
        title=row["title"] or "Product",
        last_price=row["last_price"],
        currency=row["currency"],
        in_stock=_availability(row["in_stock"]),
        last_checked=row["last_checked"],
        last_error=row["last_error"],
    )


async def init_db() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with _connection() as database:
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                last_price REAL,
                currency TEXT,
                in_stock INTEGER,
                last_checked TEXT,
                last_error TEXT
            )
            """
        )
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_id INTEGER NOT NULL,
                price REAL,
                currency TEXT,
                in_stock INTEGER,
                checked_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (watch_id) REFERENCES watches(id) ON DELETE CASCADE
            )
            """
        )

        columns = {
            row["name"]
            for row in await (
                await database.execute("PRAGMA table_info(watches)")
            ).fetchall()
        }
        if "last_error" not in columns:
            await database.execute("ALTER TABLE watches ADD COLUMN last_error TEXT")

        await database.execute(
            "CREATE INDEX IF NOT EXISTS idx_watches_url ON watches(url)"
        )
        await database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_price_history_watch_checked
            ON price_history(watch_id, checked_at)
            """
        )
        await database.commit()


async def add_watch(
    url: str,
    title: str,
    price: float | None,
    currency: str | None,
    in_stock: bool | None,
    last_error: str | None = None,
) -> tuple[int, bool]:
    async with _connection() as database:
        existing = await (
            await database.execute(
                "SELECT id FROM watches WHERE url = ? ORDER BY id LIMIT 1",
                (url,),
            )
        ).fetchone()
        if existing:
            return existing["id"], False

        cursor = await database.execute(
            """
            INSERT INTO watches(
                url, title, last_price, currency, in_stock, last_checked, last_error
            )
            VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
            """,
            (
                url,
                title,
                price,
                currency,
                None if in_stock is None else int(in_stock),
                last_error,
            ),
        )
        watch_id = cursor.lastrowid
        await database.execute(
            """
            INSERT INTO price_history(watch_id, price, currency, in_stock)
            VALUES (?, ?, ?, ?)
            """,
            (
                watch_id,
                price,
                currency,
                None if in_stock is None else int(in_stock),
            ),
        )
        await database.commit()
        return watch_id, True


async def get_watch(watch_id: int) -> Watch | None:
    async with _connection() as database:
        row = await (
            await database.execute(
                """
                SELECT id, url, title, last_price, currency, in_stock,
                       last_checked, last_error
                FROM watches
                WHERE id = ?
                """,
                (watch_id,),
            )
        ).fetchone()
    return _watch(row) if row else None


async def list_watches() -> list[Watch]:
    async with _connection() as database:
        rows = await (
            await database.execute(
                """
                SELECT id, url, title, last_price, currency, in_stock,
                       last_checked, last_error
                FROM watches
                ORDER BY id DESC
                """
            )
        ).fetchall()
    return [_watch(row) for row in rows]


async def update_watch(
    watch_id: int,
    title: str,
    price: float | None,
    currency: str | None,
    in_stock: bool | None,
    last_error: str | None = None,
) -> None:
    async with _connection() as database:
        await database.execute(
            """
            UPDATE watches
            SET title = ?, last_price = ?, currency = ?, in_stock = ?,
                last_checked = datetime('now'), last_error = ?
            WHERE id = ?
            """,
            (
                title,
                price,
                currency,
                None if in_stock is None else int(in_stock),
                last_error,
                watch_id,
            ),
        )
        await database.execute(
            """
            INSERT INTO price_history(watch_id, price, currency, in_stock)
            SELECT ?, ?, ?, ?
            WHERE EXISTS (SELECT 1 FROM watches WHERE id = ?)
            """,
            (
                watch_id,
                price,
                currency,
                None if in_stock is None else int(in_stock),
                watch_id,
            ),
        )
        await database.commit()


async def mark_check_failed(watch_id: int, message: str) -> None:
    async with _connection() as database:
        await database.execute(
            """
            UPDATE watches
            SET in_stock = NULL, last_checked = datetime('now'), last_error = ?
            WHERE id = ?
            """,
            (message, watch_id),
        )
        await database.commit()


async def delete_watch(watch_id: int) -> None:
    async with _connection() as database:
        await database.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
        await database.commit()


async def get_price_stats(watch_id: int, limit: int = 20) -> PriceStats:
    async with _connection() as database:
        rows = await (
            await database.execute(
                """
                SELECT price, checked_at
                FROM price_history
                WHERE watch_id = ? AND price IS NOT NULL
                ORDER BY id DESC
                LIMIT ?
                """,
                (watch_id, limit),
            )
        ).fetchall()

    points = tuple(
        PricePoint(price=row["price"], checked_at=row["checked_at"])
        for row in reversed(rows)
    )
    if not points:
        return PriceStats(0, None, None, None, "none", None, ())

    latest = points[-1].price
    previous = points[-2].price if len(points) > 1 else None
    if previous is None:
        direction = "new"
        change = None
    elif abs(latest - previous) < 0.001:
        direction = "stable"
        change = 0.0
    elif latest < previous:
        direction = "down"
        change = previous - latest
    else:
        direction = "up"
        change = latest - previous

    return PriceStats(
        count=len(points),
        lowest=min(point.price for point in points),
        latest=latest,
        previous=previous,
        direction=direction,
        change=change,
        points=points,
    )
