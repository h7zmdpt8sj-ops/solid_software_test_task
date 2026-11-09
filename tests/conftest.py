import os
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine, create_engine, text, update
from sqlalchemy.orm import Session, sessionmaker

from app import create_app
from app.models import Cart, CartItem, Product, User, UserPaymentMethod

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://shop:shop@localhost:5432/shop_test"
)
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
TABLES = "payments, user_payment_methods, cart_items, carts, products, users"


@dataclass(frozen=True)
class Customer:
    user_id: UUID
    cart_id: UUID
    payment_method_id: UUID


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        driver_connection = connection.connection.driver_connection
        assert driver_connection is not None
        driver_connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            driver_connection.execute(migration.read_text())
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app(engine: Engine) -> Flask:
    return create_app(TEST_DATABASE_URL)


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def client(app: Flask, session_factory: sessionmaker[Session]) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def customer(session_factory: sessionmaker[Session]) -> Customer:
    return create_customer(session_factory, "alice@example.com")


def create_customer(session_factory: sessionmaker[Session], email: str) -> Customer:
    with session_factory.begin() as session:
        user = User(email=email, name=email.split("@")[0])
        kettle = Product(name="Blue Kettle", price=Decimal("45.00"), currency="USD")
        mug = Product(name="Ceramic Mug", price=Decimal("12.50"), currency="USD")
        session.add_all([user, kettle, mug])
        session.flush()
        cart = Cart(user_id=user.id)
        payment_method = UserPaymentMethod(
            user_id=user.id, provider_token="tok_test_visa", last_four="4242", is_default=True
        )
        session.add_all([cart, payment_method])
        session.flush()
        session.add_all(
            [
                CartItem(
                    cart_id=cart.id, product_id=kettle.id, quantity=1, unit_price=kettle.price
                ),
                CartItem(cart_id=cart.id, product_id=mug.id, quantity=2, unit_price=mug.price),
            ]
        )
        return Customer(user_id=user.id, cart_id=cart.id, payment_method_id=payment_method.id)


def add_payment_method(
    session_factory: sessionmaker[Session],
    user_id: UUID,
    provider_token: str,
    is_default: bool = False,
) -> UUID:
    with session_factory.begin() as session:
        if is_default:
            session.execute(
                update(UserPaymentMethod)
                .where(UserPaymentMethod.user_id == user_id)
                .values(is_default=False)
            )
        payment_method = UserPaymentMethod(
            user_id=user_id, provider_token=provider_token, is_default=is_default
        )
        session.add(payment_method)
        session.flush()
        return payment_method.id
