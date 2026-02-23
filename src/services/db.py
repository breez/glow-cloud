import asyncio
import os

import asyncpg

_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _lock:
        if _pool is not None:
            return _pool
        _pool = await asyncpg.create_pool(
            os.environ["DATABASE_URL"],
            min_size=1,
            max_size=5,
            statement_cache_size=0,
        )
        return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
