from typing import Any
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue

from app.errors import ApiError, InvalidRequestError, UnauthorizedError
from app.models import Payment, PaymentStatus
from app.payments import start_payment

USER_ID_HEADER = "X-User-Id"

payments_blueprint = Blueprint("payments", __name__)


@payments_blueprint.post("/carts/<uuid:cart_id>/payments")
def create_payment(cart_id: UUID) -> ResponseReturnValue:
    payment = start_payment(
        current_app.extensions["session_factory"],
        user_id=_authenticated_user_id(),
        cart_id=cart_id,
        payment_method_id=_requested_payment_method_id(),
    )
    http_status = 201 if payment.status == PaymentStatus.SUCCEEDED else 402
    return jsonify(_serialize(payment)), http_status


@payments_blueprint.errorhandler(ApiError)
def handle_api_error(error: ApiError) -> ResponseReturnValue:
    return jsonify(error=error.code), error.http_status


def _authenticated_user_id() -> UUID:
    try:
        return UUID(request.headers[USER_ID_HEADER])
    except (KeyError, ValueError) as error:
        raise UnauthorizedError from error


def _requested_payment_method_id() -> UUID | None:
    if not request.content_length:
        return None
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise InvalidRequestError
    payment_method_id = body.get("payment_method_id")
    if payment_method_id is None:
        return None
    try:
        return UUID(payment_method_id)
    except (TypeError, ValueError, AttributeError) as error:
        raise InvalidRequestError from error


def _serialize(payment: Payment) -> dict[str, Any]:
    return {
        "id": str(payment.id),
        "cart_id": str(payment.cart_id),
        "payment_method_id": str(payment.payment_method_id),
        "amount": str(payment.amount),
        "currency": payment.currency,
        "status": payment.status,
        "failure_reason": payment.failure_reason,
        "created_at": payment.created_at.isoformat(),
    }
