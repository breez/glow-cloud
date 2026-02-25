from typing import Annotated

from fastapi import APIRouter, Depends

from breez_sdk_spark import GetInfoRequest, ListPaymentsRequest, SyncWalletRequest

from src.middleware.auth import require_permission
from src.services.sdk import get_sdk
from src.types import ApiKeyRecord

router = APIRouter()


@router.get("/balance")
async def balance(
    _api_key: Annotated[ApiKeyRecord, Depends(require_permission("balance"))],
):
    sdk = await get_sdk()
    await sdk.sync_wallet(request=SyncWalletRequest())
    info = await sdk.get_info(request=GetInfoRequest(ensure_synced=False))

    return {
        "balance_sats": info.balance_sats,
        "identity_pubkey": info.identity_pubkey,
    }


@router.get("/payments")
async def payments(
    _api_key: Annotated[ApiKeyRecord, Depends(require_permission("balance"))],
):
    sdk = await get_sdk()
    result = await sdk.list_payments(request=ListPaymentsRequest(limit=10))
    return {"payments": [str(p) for p in result.payments]}
