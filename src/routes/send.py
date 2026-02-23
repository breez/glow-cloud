import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from breez_sdk_spark import PrepareSendPaymentRequest, SendPaymentRequest

from src.middleware.auth import require_permission
from src.services.budget import release_spend, reserve_spend
from src.services.sdk import get_sdk
from src.types import ApiKeyRecord, SendRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/send")
async def send(
    body: SendRequest,
    api_key: Annotated[ApiKeyRecord, Depends(require_permission("send"))],
):
    sdk = await get_sdk()

    prepare_response = await sdk.prepare_send_payment(
        request=PrepareSendPaymentRequest(
            payment_request=body.destination,
            amount=body.amount_sats,
        )
    )

    # Resolve actual amount from prepare response (handles invoices with encoded amounts)
    amount_sats = body.amount_sats
    if amount_sats is None:
        # Try to extract from prepare_response
        pm = prepare_response.payment_method
        amount_sats = getattr(pm, "amount_sats", None) or getattr(pm, "amount", None)
    if amount_sats is None or amount_sats <= 0:
        raise HTTPException(status_code=400, detail="Could not determine payment amount")

    # Atomically check budget and reserve spend before sending
    usage_id = await reserve_spend(api_key, amount_sats)

    try:
        send_response = await sdk.send_payment(
            request=SendPaymentRequest(prepare_response=prepare_response)
        )
    except Exception as e:
        # Payment failed or status uncertain — release the budget reservation
        if usage_id is not None:
            await release_spend(usage_id)
        logger.error("Send payment error for key %s: %s", api_key.id, e)
        raise HTTPException(
            status_code=502,
            detail="Payment failed. Budget reservation released. Check node status before retrying.",
        )

    payment = send_response.payment
    return {
        "payment_id": getattr(payment, "id", None),
        "amount_sats": amount_sats,
        "status": "sent",
    }
