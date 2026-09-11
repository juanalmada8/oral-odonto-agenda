"""Inbound provider notifications."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_payment_service
from app.core.exceptions import DomainError
from app.db.session import get_db
from app.integrations.fake_payments import FakePaymentGateway
from app.integrations.payments import PaymentGatewayError
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


@router.post("/webhooks/mercadopago")
def mercadopago_webhook(
    request: Request,
    db: Session = Depends(get_db),
    payment_service: PaymentService = Depends(get_payment_service),
):
    params = request.query_params
    topic = params.get("type") or params.get("topic")
    data_id = params.get("data.id") or params.get("id")
    if topic != "payment" or not data_id:
        # Merchant orders and other topics carry nothing we act on; acknowledge so MP stops retrying.
        return Response(status_code=200)

    gateway = payment_service.gateway
    if gateway is None or isinstance(gateway, FakePaymentGateway):
        return Response(status_code=404)
    if not gateway.verify_notification(
        signature=request.headers.get("x-signature"),
        request_id=request.headers.get("x-request-id"),
        data_id=data_id,
    ):
        logger.warning("Rejected Mercado Pago notification with an invalid signature (payment %s)", data_id)
        return Response(status_code=401)

    try:
        payment_service.sync_provider_payment(db, data_id)
    except PaymentGatewayError as exc:
        db.rollback()
        logger.error("Mercado Pago notification for payment %s could not be processed: %s", data_id, exc)
        return Response(status_code=502)  # non-2xx makes Mercado Pago retry later
    except DomainError as exc:
        db.rollback()
        logger.warning("Mercado Pago notification for payment %s ignored: %s", data_id, exc.detail)
    return Response(status_code=200)
