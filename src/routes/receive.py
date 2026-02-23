from typing import Annotated

from fastapi import APIRouter, Depends

from breez_sdk_spark import ReceivePaymentMethod, ReceivePaymentRequest

from src.middleware.auth import require_permission
from src.services.sdk import get_sdk
from src.types import ApiKeyRecord, ReceiveRequest

router = APIRouter()


@router.post("/receive")
async def receive(
    body: ReceiveRequest,
    _api_key: Annotated[ApiKeyRecord, Depends(require_permission("receive"))],
):
    sdk = await get_sdk()

    payment_method = ReceivePaymentMethod.BOLT11_INVOICE(
        description=body.description,
        amount_sats=body.amount_sats,
    )
    response = await sdk.receive_payment(
        request=ReceivePaymentRequest(payment_method=payment_method)
    )

    return {
        "payment_request": response.payment_request,
        "fee_sats": response.fee,
    }
