"""Tests for the /keys admin API."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tests.conftest import (
    ADMIN_KEY,
    NON_ADMIN_KEY,
    RAW_ADMIN_KEY,
    RAW_USER_KEY,
)

pytestmark = pytest.mark.asyncio


# --- POST /keys ---


async def test_create_key(client, mock_db):
    created_id = str(uuid4())
    now = datetime.now(timezone.utc)

    # First call = auth fetchrow, second call = INSERT RETURNING
    original_side_effect = mock_db.fetchrow.side_effect

    async def fetchrow_dispatch(query, *args):
        if "INSERT INTO api_keys" in query:
            return {"id": created_id, "created_at": now}
        return await original_side_effect(query, *args)

    mock_db.fetchrow.side_effect = fetchrow_dispatch

    resp = await client.post(
        "/keys",
        json={"name": "myapp", "permissions": ["balance", "receive"]},
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "key" in data
    assert len(data["key"]) > 20
    assert data["name"] == "myapp"
    assert data["permissions"] == ["balance", "receive"]
    assert data["id"] == created_id


async def test_create_key_with_budget(client, mock_db):
    created_id = str(uuid4())
    now = datetime.now(timezone.utc)
    original_side_effect = mock_db.fetchrow.side_effect

    async def fetchrow_dispatch(query, *args):
        if "INSERT INTO api_keys" in query:
            return {"id": created_id, "created_at": now}
        return await original_side_effect(query, *args)

    mock_db.fetchrow.side_effect = fetchrow_dispatch

    resp = await client.post(
        "/keys",
        json={
            "name": "limited",
            "permissions": ["balance", "send"],
            "budget_sats": 10000,
            "budget_period": "daily",
            "max_amount_sats": 5000,
        },
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["budget_sats"] == 10000
    assert data["budget_period"] == "daily"
    assert data["max_amount_sats"] == 5000


async def test_create_key_defaults(client, mock_db):
    """Default permissions should be balance + receive."""
    created_id = str(uuid4())
    now = datetime.now(timezone.utc)
    original_side_effect = mock_db.fetchrow.side_effect

    async def fetchrow_dispatch(query, *args):
        if "INSERT INTO api_keys" in query:
            return {"id": created_id, "created_at": now}
        return await original_side_effect(query, *args)

    mock_db.fetchrow.side_effect = fetchrow_dispatch

    resp = await client.post(
        "/keys",
        json={"name": "default-perms"},
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 200
    assert resp.json()["permissions"] == ["balance", "receive"]


# --- Privilege escalation prevention ---


async def test_create_key_rejects_admin_permission(client, mock_db):
    resp = await client.post(
        "/keys",
        json={"name": "sneaky", "permissions": ["balance", "admin"]},
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 400
    assert "admin" in resp.json()["detail"].lower()


async def test_create_key_rejects_unknown_permission(client, mock_db):
    resp = await client.post(
        "/keys",
        json={"name": "bad", "permissions": ["balance", "delete_everything"]},
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 400
    assert "delete_everything" in resp.json()["detail"]


# --- Validation ---


async def test_create_key_budget_without_period(client, mock_db):
    resp = await client.post(
        "/keys",
        json={"name": "noperiod", "budget_sats": 5000},
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 400
    assert "budget_period" in resp.json()["detail"]


async def test_create_key_invalid_period(client, mock_db):
    resp = await client.post(
        "/keys",
        json={"name": "bad", "budget_sats": 5000, "budget_period": "yearly"},
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 422  # Pydantic validation


async def test_create_key_empty_name(client, mock_db):
    resp = await client.post(
        "/keys",
        json={"name": ""},
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 422


async def test_create_key_negative_budget(client, mock_db):
    resp = await client.post(
        "/keys",
        json={"name": "neg", "budget_sats": -1, "budget_period": "daily"},
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 422


# --- Auth: non-admin keys blocked ---


async def test_create_key_non_admin_forbidden(client, mock_db):
    resp = await client.post(
        "/keys",
        json={"name": "nope"},
        headers={"X-API-Key": RAW_USER_KEY},
    )
    assert resp.status_code == 403


async def test_list_keys_non_admin_forbidden(client, mock_db):
    resp = await client.get(
        "/keys",
        headers={"X-API-Key": RAW_USER_KEY},
    )
    assert resp.status_code == 403


async def test_revoke_key_non_admin_forbidden(client, mock_db):
    resp = await client.delete(
        f"/keys/{uuid4()}",
        headers={"X-API-Key": RAW_USER_KEY},
    )
    assert resp.status_code == 403


# --- Auth: no key at all ---


async def test_create_key_no_auth(client, mock_db):
    resp = await client.post("/keys", json={"name": "nope"})
    assert resp.status_code == 422  # missing X-API-Key header


async def test_list_keys_no_auth(client, mock_db):
    resp = await client.get("/keys")
    assert resp.status_code == 422


# --- GET /keys ---


async def test_list_keys(client, mock_db):
    now = datetime.now(timezone.utc)
    original_side_effect = mock_db.fetchrow.side_effect

    mock_db.fetch = AsyncMock(return_value=[
        {
            "id": ADMIN_KEY.id,
            "name": "default",
            "permissions": ["balance", "receive", "send", "admin"],
            "budget_sats": None,
            "budget_period": None,
            "max_amount_sats": None,
            "created_at": now,
        },
        {
            "id": str(uuid4()),
            "name": "myapp",
            "permissions": ["balance", "receive"],
            "budget_sats": 10000,
            "budget_period": "daily",
            "max_amount_sats": 5000,
            "created_at": now,
        },
    ])

    resp = await client.get(
        "/keys",
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["name"] == "default"
    assert data[1]["budget_sats"] == 10000
    # Verify no key_hash in response
    for key in data:
        assert "key_hash" not in key
        assert "key" not in key


# --- DELETE /keys/{key_id} ---


async def test_revoke_key(client, mock_db):
    target_id = str(uuid4())
    mock_db.execute = AsyncMock(return_value="UPDATE 1")

    resp = await client.delete(
        f"/keys/{target_id}",
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Key revoked"


async def test_revoke_key_not_found(client, mock_db):
    mock_db.execute = AsyncMock(return_value="UPDATE 0")

    resp = await client.delete(
        f"/keys/{uuid4()}",
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 404


async def test_revoke_own_key(client, mock_db):
    """Cannot revoke yourself — prevents lockout."""
    resp = await client.delete(
        f"/keys/{ADMIN_KEY.id}",
        headers={"X-API-Key": RAW_ADMIN_KEY},
    )
    assert resp.status_code == 400
    assert "own" in resp.json()["detail"].lower()
