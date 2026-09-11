"""Inbound provider notifications (Mercado Pago payments, WhatsApp messages)."""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_followup_agent, get_payment_service, get_whatsapp_bot
from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.db.session import get_db
from app.integrations.fake_payments import FakePaymentGateway
from app.integrations.payments import PaymentGatewayError
from app.services.followup_agent import FollowUpAgent
from app.services.payment_service import PaymentService
from app.services.whatsapp_bot import WhatsAppBot
from app.tasks.notifications import dispatch_due_notifications

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


@router.post("/webhooks/mercadopago")
def mercadopago_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    payment_service: PaymentService = Depends(get_payment_service),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
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
    background_tasks.add_task(dispatch_due_notifications, followup_agent)
    return Response(status_code=200)


@router.get("/webhooks/whatsapp")
def whatsapp_verification(request: Request):
    """Meta calls this once when the webhook URL is registered."""
    params = request.query_params
    expected = get_settings().whatsapp_verify_token
    if params.get("hub.mode") == "subscribe" and expected and params.get("hub.verify_token") == expected:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return Response(status_code=403)


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    bot: WhatsAppBot = Depends(get_whatsapp_bot),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    raw_body = await request.body()
    if not bot.whatsapp.verify_signature(raw_body, request.headers.get("x-hub-signature-256")):
        logger.warning("Rejected WhatsApp webhook with an invalid signature")
        return Response(status_code=401)
    try:
        payload = json.loads(raw_body or b"{}")
    except ValueError:
        return Response(status_code=400)
    await run_in_threadpool(bot.handle_webhook, db, payload)
    background_tasks.add_task(dispatch_due_notifications, followup_agent)
    return Response(status_code=200)
