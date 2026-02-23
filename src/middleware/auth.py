import hashlib
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from src.services.db import get_pool
from src.types import ApiKeyRecord


async def get_api_key(
    x_api_key: Annotated[str, Header()],
) -> ApiKeyRecord:
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    pool = await get_pool()

    row = await pool.fetchrow(
        """
        SELECT id, name, max_amount_sats, budget_sats, budget_period, permissions
        FROM api_keys
        WHERE key_hash = $1 AND is_active = true
        """,
        key_hash,
    )

    if row is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return ApiKeyRecord(
        id=str(row["id"]),
        name=row["name"],
        max_amount_sats=row["max_amount_sats"],
        budget_sats=row["budget_sats"],
        budget_period=row["budget_period"],
        permissions=row["permissions"],
    )


def require_permission(operation: str):
    async def check(
        api_key: Annotated[ApiKeyRecord, Depends(get_api_key)],
    ) -> ApiKeyRecord:
        if operation not in api_key.permissions:
            raise HTTPException(
                status_code=403,
                detail=f"API key lacks '{operation}' permission",
            )
        return api_key

    return check
