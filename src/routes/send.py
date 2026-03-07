import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from breez_sdk_spark import (
    LnurlPayRequest,
    PrepareLnurlPayRequest,
    PrepareSendPaymentRequest,
    SendPaymentRequest,
)

from src.middleware.auth import require_permission
from src.services.budget import release_spend, reserve_spend
from src.services.sdk import get_sdk
from src.types import ApiKeyRecord, SendRequest

logger = logging.getLogger(__name__)

router = APIRouter()


async def _send_bolt11(sdk, body, api_key):
    """Send via BOLT11 invoice."""
    prepare_response = await sdk.prepare_send_payment(
        request=PrepareSendPaymentRequest(
            payment_request=body.destination,
            amount=body.amount_sats,
        )
    )

    amount_sats = body.amount_sats
    if amount_sats is None:
        pm = prepare_response.payment_method
        amount_sats = getattr(pm, "amount_sats", None) or getattr(pm, "amount", None)
    if amount_sats is None or amount_sats <= 0:
        raise HTTPException(status_code=400, detail="Could not determine payment amount")

    usage_id = await reserve_spend(api_key, amount_sats)

    try:
        send_response = await sdk.send_payment(
            request=SendPaymentRequest(prepare_response=prepare_response)
        )
    except Exception as e:
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


async def _send_lightning_address(sdk, body, api_key):
    """Send to a Lightning address via LNURL-pay."""
    if body.amount_sats is None:
        raise HTTPException(status_code=400, detail="amount_sats is required when sending to a Lightning address")

    parsed = await sdk.parse(input=body.destination)
    if parsed.is_lightning_address():
        details = parsed[0]
        pay_request = details.pay_request
    elif parsed.is_lnurl_pay():
        pay_request = parsed[0]
    else:
        raise HTTPException(status_code=400, detail="Could not parse Lightning address")

    prepare_response = await sdk.prepare_lnurl_pay(
        request=PrepareLnurlPayRequest(
            amount_sats=body.amount_sats,
            pay_request=pay_request,
        )
    )

    usage_id = await reserve_spend(api_key, body.amount_sats)

    try:
        result = await sdk.lnurl_pay(
            request=LnurlPayRequest(prepare_response=prepare_response)
        )
    except Exception as e:
        if usage_id is not None:
            await release_spend(usage_id)
        logger.error("LNURL pay error for key %s: %s", api_key.id, e)
        raise HTTPException(
            status_code=502,
            detail="Payment failed. Budget reservation released. Check node status before retrying.",
        )

    return {
        "amount_sats": body.amount_sats,
        "status": "sent",
    }


def _is_lightning_address(destination: str) -> bool:
    return "@" in destination and "." in destination.split("@")[-1]


@router.post("/send")
async def send(
    body: SendRequest,
    api_key: Annotated[ApiKeyRecord, Depends(require_permission("send"))],
):
    sdk = await get_sdk()

    if _is_lightning_address(body.destination):
        return await _send_lightning_address(sdk, body, api_key)
    return await _send_bolt11(sdk, body, api_key)
