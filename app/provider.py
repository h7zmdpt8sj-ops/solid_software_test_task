from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

DECLINED_TOKEN_PREFIX = "tok_declined"
CARD_DECLINED = "card_declined"


@dataclass(frozen=True)
class ChargeResult:
    provider_payment_id: str
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure_reason is None


def charge(provider_token: str, amount: Decimal, currency: str) -> ChargeResult:
    provider_payment_id = f"mock_{uuid4().hex}"
    if provider_token.startswith(DECLINED_TOKEN_PREFIX):
        return ChargeResult(provider_payment_id, failure_reason=CARD_DECLINED)
    return ChargeResult(provider_payment_id)
