from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CartItem, Product


@dataclass(frozen=True)
class CartTotal:
    amount: Decimal
    currency: str


def calculate_cart_total(session: Session, cart_id: UUID) -> CartTotal | None:
    rows = session.execute(
        select(CartItem.quantity, CartItem.unit_price, Product.currency)
        .join(Product, Product.id == CartItem.product_id)
        .where(CartItem.cart_id == cart_id)
    ).all()
    if not rows:
        return None
    amount = sum((row.unit_price * row.quantity for row in rows), Decimal("0"))
    return CartTotal(amount=amount, currency=rows[0].currency)
