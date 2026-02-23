import base64
import hashlib
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.middleware.auth import require_permission
from src.services.db import get_pool
from src.types import ApiKeyRecord, CreateKeyRequest

router = APIRouter()

ALLOWED_PERMISSIONS = {"balance", "receive", "send"}


@router.post("/keys")
async def create_key(
    body: CreateKeyRequest,
    api_key: Annotated[ApiKeyRecord, Depends(require_permission("admin"))],
):
    invalid = set(body.permissions) - ALLOWED_PERMISSIONS
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid permissions: {', '.join(sorted(invalid))}. Admin keys can only be created via the setup wizard.",
        )

    if body.budget_sats is not None and body.budget_period is None:
        raise HTTPException(
            status_code=400,
            detail="budget_period is required when budget_sats is set",
        )

    raw_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO api_keys (key_hash, name, max_amount_sats, budget_sats, budget_period, permissions)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, created_at
        """,
        key_hash,
        body.name,
        body.max_amount_sats,
        body.budget_sats,
        body.budget_period,
        body.permissions,
    )

    return {
        "key": raw_key,
        "id": str(row["id"]),
        "name": body.name,
        "permissions": body.permissions,
        "budget_sats": body.budget_sats,
        "budget_period": body.budget_period,
        "max_amount_sats": body.max_amount_sats,
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/keys")
async def list_keys(
    _api_key: Annotated[ApiKeyRecord, Depends(require_permission("admin"))],
):
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, permissions, budget_sats, budget_period, max_amount_sats, created_at
        FROM api_keys
        WHERE is_active = true
        ORDER BY created_at
        """,
    )

    return [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "permissions": row["permissions"],
            "budget_sats": row["budget_sats"],
            "budget_period": row["budget_period"],
            "max_amount_sats": row["max_amount_sats"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


@router.delete("/keys/{key_id}")
async def revoke_key(
    key_id: str,
    api_key: Annotated[ApiKeyRecord, Depends(require_permission("admin"))],
):
    if key_id == api_key.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot revoke your own API key",
        )

    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE api_keys SET is_active = false
        WHERE id = $1::uuid AND is_active = true
        """,
        key_id,
    )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Key not found or already revoked")

    return {"detail": "Key revoked"}
