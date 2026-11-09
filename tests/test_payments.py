from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from flask.testing import FlaskClient
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from werkzeug.test import TestResponse

from app import provider
from app.models import Cart, CartItem, CartStatus, Payment, PaymentStatus, UserPaymentMethod
from tests.conftest import Customer, add_payment_method, create_customer


def pay(
    client: FlaskClient,
    cart_id: UUID | str,
    user_id: UUID | str | None,
    body: Any = None,
) -> TestResponse:
    headers = {} if user_id is None else {"X-User-Id": str(user_id)}
    return client.post(f"/carts/{cart_id}/payments", headers=headers, json=body)


def cart_status(session_factory: sessionmaker[Session], cart_id: UUID) -> str:
    with session_factory() as session:
        return session.get_one(Cart, cart_id).status


def payments_of(session_factory: sessionmaker[Session], cart_id: UUID) -> list[Payment]:
    with session_factory() as session:
        return list(session.scalars(select(Payment).where(Payment.cart_id == cart_id)))


def test_successful_payment_checks_out_cart(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    response = pay(client, customer.cart_id, customer.user_id)

    assert response.status_code == 201
    assert response.json is not None
    assert response.json["status"] == PaymentStatus.SUCCEEDED
    assert response.json["amount"] == "70.00"
    assert response.json["currency"] == "USD"
    assert response.json["cart_id"] == str(customer.cart_id)
    assert response.json["payment_method_id"] == str(customer.payment_method_id)
    assert response.json["failure_reason"] is None
    assert cart_status(session_factory, customer.cart_id) == CartStatus.CHECKED_OUT
    [payment] = payments_of(session_factory, customer.cart_id)
    assert str(payment.id) == response.json["id"]
    assert payment.provider_payment_id is not None


def test_provider_is_charged_with_cart_total_and_card_token(
    client: FlaskClient, customer: Customer, monkeypatch: pytest.MonkeyPatch
) -> None:
    charges: list[tuple[str, Decimal, str]] = []

    def fake_charge(provider_token: str, amount: Decimal, currency: str) -> provider.ChargeResult:
        charges.append((provider_token, amount, currency))
        return provider.ChargeResult("mock_payment")

    monkeypatch.setattr(provider, "charge", fake_charge)

    pay(client, customer.cart_id, customer.user_id)

    assert charges == [("tok_test_visa", Decimal("70.00"), "USD")]


def test_declined_card_fails_payment_and_keeps_cart_active(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    add_payment_method(session_factory, customer.user_id, "tok_declined_visa", is_default=True)

    response = pay(client, customer.cart_id, customer.user_id)

    assert response.status_code == 402
    assert response.json is not None
    assert response.json["status"] == PaymentStatus.FAILED
    assert response.json["failure_reason"] == provider.CARD_DECLINED
    assert cart_status(session_factory, customer.cart_id) == CartStatus.ACTIVE


def test_payment_can_be_retried_with_another_card_after_decline(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    declined_method_id = add_payment_method(session_factory, customer.user_id, "tok_declined_visa")

    declined = pay(
        client, customer.cart_id, customer.user_id, {"payment_method_id": str(declined_method_id)}
    )
    retried = pay(
        client,
        customer.cart_id,
        customer.user_id,
        {"payment_method_id": str(customer.payment_method_id)},
    )

    assert declined.status_code == 402
    assert retried.status_code == 201
    statuses = sorted(payment.status for payment in payments_of(session_factory, customer.cart_id))
    assert statuses == [PaymentStatus.FAILED, PaymentStatus.SUCCEEDED]


def test_paid_cart_cannot_be_paid_again(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    pay(client, customer.cart_id, customer.user_id)

    response = pay(client, customer.cart_id, customer.user_id)

    assert response.status_code == 409
    assert response.json == {"error": "cart_not_active"}
    assert len(payments_of(session_factory, customer.cart_id)) == 1


def test_abandoned_cart_cannot_be_paid(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    with session_factory.begin() as session:
        session.execute(
            update(Cart).where(Cart.id == customer.cart_id).values(status=CartStatus.ABANDONED)
        )

    response = pay(client, customer.cart_id, customer.user_id)

    assert response.status_code == 409
    assert response.json == {"error": "cart_not_active"}


def test_cart_with_pending_payment_cannot_be_paid_again(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    with session_factory.begin() as session:
        session.add(
            Payment(
                cart_id=customer.cart_id,
                user_id=customer.user_id,
                payment_method_id=customer.payment_method_id,
                amount=Decimal("70.00"),
                currency="USD",
            )
        )

    response = pay(client, customer.cart_id, customer.user_id)

    assert response.status_code == 409
    assert response.json == {"error": "payment_already_started"}


def test_database_rejects_second_open_payment_for_cart(
    session_factory: sessionmaker[Session], customer: Customer
) -> None:
    def open_payment() -> Payment:
        return Payment(
            cart_id=customer.cart_id,
            user_id=customer.user_id,
            payment_method_id=customer.payment_method_id,
            amount=Decimal("70.00"),
            currency="USD",
        )

    with pytest.raises(IntegrityError), session_factory.begin() as session:
        session.add_all([open_payment(), open_payment()])


def test_empty_cart_cannot_be_paid(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    with session_factory.begin() as session:
        session.execute(delete(CartItem).where(CartItem.cart_id == customer.cart_id))

    response = pay(client, customer.cart_id, customer.user_id)

    assert response.status_code == 422
    assert response.json == {"error": "cart_is_empty"}


def test_unknown_cart_returns_not_found(client: FlaskClient, customer: Customer) -> None:
    response = pay(client, uuid4(), customer.user_id)

    assert response.status_code == 404
    assert response.json == {"error": "cart_not_found"}


def test_cart_of_another_user_returns_not_found(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    other_customer = create_customer(session_factory, "bob@example.com")

    response = pay(client, customer.cart_id, other_customer.user_id)

    assert response.status_code == 404
    assert response.json == {"error": "cart_not_found"}
    assert cart_status(session_factory, customer.cart_id) == CartStatus.ACTIVE


def test_malformed_cart_id_returns_not_found(client: FlaskClient, customer: Customer) -> None:
    response = pay(client, "not-a-uuid", customer.user_id)

    assert response.status_code == 404


@pytest.mark.parametrize("user_id", [None, "", "not-a-uuid"])
def test_request_without_valid_user_is_unauthorized(
    client: FlaskClient, customer: Customer, user_id: str | None
) -> None:
    response = pay(client, customer.cart_id, user_id)

    assert response.status_code == 401
    assert response.json == {"error": "unauthorized"}


def test_user_without_default_payment_method_cannot_pay(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    with session_factory.begin() as session:
        session.execute(
            update(UserPaymentMethod)
            .where(UserPaymentMethod.user_id == customer.user_id)
            .values(is_default=False)
        )

    response = pay(client, customer.cart_id, customer.user_id)

    assert response.status_code == 422
    assert response.json == {"error": "payment_method_not_found"}


def test_payment_method_of_another_user_cannot_be_used(
    client: FlaskClient, session_factory: sessionmaker[Session], customer: Customer
) -> None:
    other_customer = create_customer(session_factory, "bob@example.com")

    response = pay(
        client,
        customer.cart_id,
        customer.user_id,
        {"payment_method_id": str(other_customer.payment_method_id)},
    )

    assert response.status_code == 422
    assert response.json == {"error": "payment_method_not_found"}
    assert payments_of(session_factory, customer.cart_id) == []


@pytest.mark.parametrize(
    "body",
    [["not", "an", "object"], {"payment_method_id": "not-a-uuid"}, {"payment_method_id": 42}],
)
def test_invalid_body_is_rejected(client: FlaskClient, customer: Customer, body: Any) -> None:
    response = pay(client, customer.cart_id, customer.user_id, body)

    assert response.status_code == 400
    assert response.json == {"error": "invalid_request"}


def test_mock_provider_declines_tokens_with_declined_prefix() -> None:
    result = provider.charge("tok_declined_card", Decimal("10.00"), "USD")

    assert not result.succeeded
    assert result.failure_reason == provider.CARD_DECLINED


def test_mock_provider_accepts_other_tokens() -> None:
    result = provider.charge("tok_test_visa", Decimal("10.00"), "USD")

    assert result.succeeded
    assert result.provider_payment_id.startswith("mock_")
