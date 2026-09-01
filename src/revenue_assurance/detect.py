from __future__ import annotations
import hashlib
from .models import Finding, Transaction


def _finding(tx: Transaction, kind: str, severity: str, value: float, action: str, approval: bool) -> Finding:
    key = hashlib.sha256(f"{tx.order_id}:{kind}:{round(value,2)}".encode()).hexdigest()[:24]
    return Finding(tx.order_id, kind, severity, round(max(0.0, value), 2), action, approval, key)


def detect(tx: Transaction) -> list[Finding]:
    findings: list[Finding] = []
    if tx.order_accepted and tx.credit_hold and tx.age_days >= 3:
        findings.append(_finding(tx,"stale-credit-hold","high",tx.ordered_usd,"review-credit-and-release",True))
    if tx.shipment_complete and not tx.invoice_created:
        findings.append(_finding(tx,"shipped-not-invoiced","critical",tx.fulfilled_usd,"create-missing-invoice",True))
    if tx.invoice_created and abs(tx.expected_price_usd-tx.invoiced_price_usd)>0.01:
        findings.append(_finding(tx,"pricing-mismatch","high",abs(tx.expected_price_usd-tx.invoiced_price_usd),"issue-corrected-invoice",True))
    if tx.payment_received and tx.paid_usd>tx.applied_usd:
        findings.append(_finding(tx,"unapplied-cash","high",tx.paid_usd-tx.applied_usd,"match-payment",False))
    if tx.applied_usd>tx.ledger_usd:
        findings.append(_finding(tx,"ledger-reconciliation-gap","critical",tx.applied_usd-tx.ledger_usd,"pause-and-reconcile-ledger",True))
    if tx.duplicate_invoice_count>0:
        findings.append(_finding(tx,"duplicate-invoice","high",tx.invoiced_usd,"void-duplicate-invoice",True))
    if tx.duplicate_payment_count>0:
        findings.append(_finding(tx,"duplicate-payment","critical",tx.paid_usd,"refund-or-credit-after-review",True))
    if tx.dispute_open and tx.age_days>=30:
        findings.append(_finding(tx,"aged-dispute","high",max(0,tx.invoiced_usd-tx.paid_usd),"assemble-dispute-evidence",False))
    return findings

