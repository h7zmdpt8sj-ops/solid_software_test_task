from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app import provider
from app.errors import (
    CartNotActiveError,
    CartNotFoundError,
    EmptyCartError,
    PaymentAlreadyStartedError,
    PaymentMethodNotFoundError,
)
from app.models import Cart, CartStatus, Payment, PaymentStatus, UserPaymentMethod
from app.totals import calculate_cart_total

OPEN_PAYMENT_STATUSES = (PaymentStatus.PENDING, PaymentStatus.SUCCEEDED)


def start_payment(
    session_factory: sessionmaker[Session],
    user_id: UUID,
    cart_id: UUID,
    payment_method_id: UUID | None,
) -> Payment:
    with session_factory.begin() as session:
        _lock_payable_cart(session, user_id, cart_id)
        payment_method = _find_payment_method(session, user_id, payment_method_id)
        total = calculate_cart_total(session, cart_id)
        if total is None:
            raise EmptyCartError
        payment = Payment(
            cart_id=cart_id,
            user_id=user_id,
            payment_method_id=payment_method.id,
            amount=total.amount,
            currency=total.currency,
        )
        session.add(payment)

    result = provider.charge(payment_method.provider_token, payment.amount, payment.currency)

    with session_factory.begin() as session:
        session.add(payment)
        payment.provider_payment_id = result.provider_payment_id
        payment.failure_reason = result.failure_reason
        if result.succeeded:
            payment.status = PaymentStatus.SUCCEEDED
            session.execute(
                update(Cart)
                .where(Cart.id == cart_id)
                .values(status=CartStatus.CHECKED_OUT, updated_at=func.now())
            )
        else:
            payment.status = PaymentStatus.FAILED

    return payment


def _lock_payable_cart(session: Session, user_id: UUID, cart_id: UUID) -> None:
    cart = session.scalars(
        select(Cart).where(Cart.id == cart_id, Cart.user_id == user_id).with_for_update()
    ).one_or_none()
    if cart is None:
        raise CartNotFoundError
    if cart.status != CartStatus.ACTIVE:
        raise CartNotActiveError
    has_open_payment = session.scalar(
        select(
            exists().where(
                Payment.cart_id == cart_id,
                Payment.status.in_(OPEN_PAYMENT_STATUSES),
            )
        )
    )
    if has_open_payment:
        raise PaymentAlreadyStartedError


def _find_payment_method(
    session: Session, user_id: UUID, payment_method_id: UUID | None
) -> UserPaymentMethod:
    query = select(UserPaymentMethod).where(UserPaymentMethod.user_id == user_id)
    if payment_method_id is None:
        query = query.where(UserPaymentMethod.is_default.is_(True))
    else:
        query = query.where(UserPaymentMethod.id == payment_method_id)
    payment_method = session.scalars(
        query.order_by(UserPaymentMethod.created_at.desc()).limit(1)
    ).first()
    if payment_method is None:
        raise PaymentMethodNotFoundError
    return payment_method
