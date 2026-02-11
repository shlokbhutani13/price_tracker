import aiosqlite

DB_PATH = "tracker.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Watches table (now includes last_error)
        await db.execute("""
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
        """)

        # Price history table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watch_id INTEGER NOT NULL,
            price REAL,
            currency TEXT,
            in_stock INTEGER,
            checked_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (watch_id) REFERENCES watches(id) ON DELETE CASCADE
        )
        """)

        # If your old watches table exists without last_error, add it (safe migration)
        try:
            await db.execute("ALTER TABLE watches ADD COLUMN last_error TEXT")
        except Exception:
            pass

        await db.commit()


async def add_watch(url: str, title: str, price: float | None, currency: str | None, in_stock: bool, last_error: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO watches(url, title, last_price, currency, in_stock, last_checked, last_error)
               VALUES (?, ?, ?, ?, ?, datetime('now'), ?)""",
            (url, title, price, currency, 1 if in_stock else 0, last_error)
        )
        watch_id = cur.lastrowid

        # also insert first snapshot into history
        await db.execute(
            "INSERT INTO price_history(watch_id, price, currency, in_stock) VALUES (?, ?, ?, ?)",
            (watch_id, price, currency, 1 if in_stock else 0)
        )

        await db.commit()
        return watch_id


async def list_watches():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, url, title, last_price, currency, in_stock, last_checked, last_error
            FROM watches
            ORDER BY id DESC
        """)
        return await cur.fetchall()


async def update_watch(watch_id: int, price: float | None, currency: str | None, in_stock: bool, last_error: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE watches
               SET last_price=?, currency=?, in_stock=?, last_checked=datetime('now'), last_error=?
               WHERE id=?""",
            (price, currency, 1 if in_stock else 0, last_error, watch_id)
        )
        await db.execute(
            "INSERT INTO price_history(watch_id, price, currency, in_stock) VALUES (?, ?, ?, ?)",
            (watch_id, price, currency, 1 if in_stock else 0)
        )
        await db.commit()


async def delete_watch(watch_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM watches WHERE id=?", (watch_id,))
        await db.execute("DELETE FROM price_history WHERE watch_id=?", (watch_id,))
        await db.commit()


async def get_price_stats(watch_id: int, limit: int = 20):
    """
    Returns: (count, min_price, last_price, prev_price, trend_text)
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """SELECT price FROM price_history
               WHERE watch_id=?
               AND price IS NOT NULL
               ORDER BY checked_at DESC
               LIMIT ?""",
            (watch_id, limit)
        )
        rows = await cur.fetchall()

    prices = [r[0] for r in rows]
    if not prices:
        return (0, None, None, None, "No price data yet")

    last_price = prices[0]
    prev_price = prices[1] if len(prices) > 1 else None
    min_price = min(prices)
    count = len(prices)

    if prev_price is None:
        trend = "Not enough history"
    else:
        diff = last_price - prev_price
        if abs(diff) < 0.001:
            trend = "Stable"
        elif diff < 0:
            trend = f"Down ${abs(diff):.2f} since last check"
        else:
            trend = f"Up ${diff:.2f} since last check"

    return (count, min_price, last_price, prev_price, trend)
