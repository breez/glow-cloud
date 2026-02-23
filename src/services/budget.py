from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException

from src.services.db import get_pool
from src.types import ApiKeyRecord


def _period_start(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "daily":
        return today
    elif period == "weekly":
        return today - timedelta(days=today.weekday())
    elif period == "monthly":
        return today.replace(day=1)
    raise ValueError(f"Unknown budget period: {period}")


async def reserve_spend(api_key: ApiKeyRecord, amount_sats: int) -> UUID | None:
    """Atomically check budget and reserve spend. Returns usage row ID if reserved.

    Uses pg_advisory_xact_lock to prevent concurrent budget checks for the same key.
    """
    if api_key.max_amount_sats is not None and amount_sats > api_key.max_amount_sats:
        raise HTTPException(
            status_code=403,
            detail=f"Amount {amount_sats} exceeds per-transaction limit of {api_key.max_amount_sats} sats",
        )

    if api_key.budget_sats is None or api_key.budget_period is None:
        return None

    pool = await get_pool()
    period_start = _period_start(api_key.budget_period)
    key_id = UUID(api_key.id)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Lock per API key to prevent concurrent budget race
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1::text))", str(key_id)
            )

            row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(amount_sats), 0) AS total_spent
                FROM budget_usage
                WHERE api_key_id = $1 AND period_start = $2
                """,
                key_id,
                period_start,
            )
            total_spent = row["total_spent"]

            if total_spent + amount_sats > api_key.budget_sats:
                remaining = max(0, api_key.budget_sats - total_spent)
                raise HTTPException(
                    status_code=403,
                    detail=f"Budget exceeded. {remaining} sats remaining this {api_key.budget_period} period",
                )

            # Reserve the spend atomically
            usage_row = await conn.fetchrow(
                """
                INSERT INTO budget_usage (api_key_id, amount_sats, operation, period_start)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                key_id,
                amount_sats,
                "send",
                period_start,
            )
            return usage_row["id"]


async def release_spend(usage_id: UUID) -> None:
    """Roll back a reserved spend (e.g. if payment fails after reservation)."""
    pool = await get_pool()
    await pool.execute("DELETE FROM budget_usage WHERE id = $1", usage_id)
