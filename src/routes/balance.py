from typing import Annotated

from fastapi import APIRouter, Depends

from breez_sdk_spark import GetInfoRequest

from src.middleware.auth import require_permission
from src.services.sdk import get_sdk
from src.types import ApiKeyRecord

router = APIRouter()


@router.get("/balance")
async def balance(
    _api_key: Annotated[ApiKeyRecord, Depends(require_permission("balance"))],
):
    sdk = await get_sdk()
    info = await sdk.get_info(request=GetInfoRequest(ensure_synced=True))

    return {
        "balance_sats": info.balance_sats,
        "pending_incoming_sats": info.pending_incoming_sats,
        "pending_outgoing_sats": info.pending_outgoing_sats,
        "max_payable_sats": info.max_payable_sats,
        "max_receivable_sats": info.max_receivable_sats,
    }
