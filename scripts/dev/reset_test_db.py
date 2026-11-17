"""Drop and recreate the public schema of a disposable test database.

Usage:  python scripts/dev/reset_test_db.py postgresql://user:pass@host:5432/omniosint_e2e

Refuses any database whose name does not contain "test" or "e2e", so it cannot
be pointed at a real installation by mistake.
"""

from __future__ import annotations

import asyncio
import sys

import asyncpg
from sqlalchemy import make_url


async def reset(url_text: str) -> None:
    url = make_url(url_text)
    name = url.database or ""
    if "test" not in name and "e2e" not in name:
        raise SystemExit(f"Refusing to reset {name!r}: the name must contain 'test' or 'e2e'.")
    connection = await asyncpg.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=name,
    )
    try:
        await connection.execute("DROP SCHEMA public CASCADE")
        await connection.execute("CREATE SCHEMA public")
    finally:
        await connection.close()
    print(f"Reset schema of {name}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    asyncio.run(reset(sys.argv[1]))
