from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Transaction:
    order_id: str
    customer_id: str
    currency: str
    ordered_usd: float
    fulfilled_usd: float
    invoiced_usd: float
    paid_usd: float
    applied_usd: float
    ledger_usd: float
    expected_price_usd: float
    invoiced_price_usd: float
    order_accepted: bool
    shipment_complete: bool
    invoice_created: bool
    payment_received: bool
    dispute_open: bool
    credit_hold: bool
    age_days: int
    duplicate_invoice_count: int = 0
    duplicate_payment_count: int = 0


@dataclass(frozen=True)
class Finding:
    order_id: str
    finding_type: str
    severity: str
    exposed_value_usd: float
    recovery_action: str
    approval_required: bool
    idempotency_key: str

    def as_dict(self) -> dict[str, object]: return self.__dict__.copy()

