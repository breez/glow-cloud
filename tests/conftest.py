import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.index import app
from src.types import ApiKeyRecord


def _make_key_record(name="default", permissions=None, key_id=None):
    return ApiKeyRecord(
        id=key_id or str(uuid4()),
        name=name,
        max_amount_sats=None,
        budget_sats=None,
        budget_period=None,
        permissions=permissions or ["balance", "receive", "send", "admin"],
    )


ADMIN_KEY = _make_key_record("admin-key", ["balance", "receive", "send", "admin"])
NON_ADMIN_KEY = _make_key_record("user-key", ["balance", "receive"])
RAW_ADMIN_KEY = "test-admin-key-raw"
RAW_USER_KEY = "test-user-key-raw"
ADMIN_HASH = hashlib.sha256(RAW_ADMIN_KEY.encode()).hexdigest()
USER_HASH = hashlib.sha256(RAW_USER_KEY.encode()).hexdigest()


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    pool.execute = AsyncMock()
    return pool


@pytest.fixture
def mock_db(mock_pool):
    """Patch get_pool to return our mock pool."""
    with patch("src.middleware.auth.get_pool", return_value=mock_pool), \
         patch("src.routes.keys.get_pool", return_value=mock_pool):
        # Configure auth lookups
        async def auth_fetchrow(query, key_hash):
            now = datetime.now(timezone.utc)
            if key_hash == ADMIN_HASH:
                return {
                    "id": ADMIN_KEY.id,
                    "name": ADMIN_KEY.name,
                    "max_amount_sats": None,
                    "budget_sats": None,
                    "budget_period": None,
                    "permissions": ADMIN_KEY.permissions,
                }
            elif key_hash == USER_HASH:
                return {
                    "id": NON_ADMIN_KEY.id,
                    "name": NON_ADMIN_KEY.name,
                    "max_amount_sats": None,
                    "budget_sats": None,
                    "budget_period": None,
                    "permissions": NON_ADMIN_KEY.permissions,
                }
            return None

        mock_pool.fetchrow.side_effect = auth_fetchrow
        yield mock_pool


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
