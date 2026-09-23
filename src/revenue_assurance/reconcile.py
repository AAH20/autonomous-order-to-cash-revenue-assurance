"""Conservative reconciliation of normalized invoice and payment exports."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path


INVOICE_FIELDS = {"invoice_id", "customer_id", "currency", "total", "due_date"}
PAYMENT_FIELDS = {"payment_id", "customer_id", "currency", "amount", "invoice_id"}
CENT = Decimal("0.01")


def _rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"{path.name}: required columns: {', '.join(sorted(required))}")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"{path.name}: duplicate column header")
        rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError(f"{path.name}: row has more fields than header")
    return rows


def _money(raw: str, field: str) -> Decimal:
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError):
        raise ValueError(f"invalid {field} amount") from None
    if not value.is_finite() or value < 0 or value.quantize(CENT) != value:
        raise ValueError(f"{field} must be a nonnegative amount with at most two decimals")
    return value


def _required(row: dict[str, str], field: str) -> str:
    value = row.get(field)
    if value is None or not value.strip():
        raise ValueError(f"missing {field}")
    return value.strip()


def reconcile(invoices_path: Path, payments_path: Path, as_of: date) -> dict:
    invoices = {}
    payments = []
    payment_ids = set()
    for row in _rows(invoices_path, INVOICE_FIELDS):
        invoice_id = _required(row, "invoice_id")
        if invoice_id in invoices:
            raise ValueError(f"duplicate invoice_id: {invoice_id}")
        due_date = date.fromisoformat(_required(row, "due_date"))
        invoices[invoice_id] = {
            "customer_id": _required(row, "customer_id"),
            "currency": _required(row, "currency").upper(),
            "total": _money(row["total"], "invoice total"),
            "due_date": due_date,
        }
    for row in _rows(payments_path, PAYMENT_FIELDS):
        payment_id = _required(row, "payment_id")
        if payment_id in payment_ids:
            raise ValueError(f"duplicate payment_id: {payment_id}; split allocations require distinct allocation IDs")
        payment_ids.add(payment_id)
        payments.append({
            "payment_id": payment_id,
            "invoice_id": (row["invoice_id"] or "").strip(),
            "customer_id": _required(row, "customer_id"),
            "currency": _required(row, "currency").upper(),
            "amount": _money(row["amount"], "payment"),
        })
    applied = {invoice_id: Decimal("0") for invoice_id in invoices}
    issues = []

    def issue(kind: str, subject: str, currency: str, amount: Decimal, detail: str) -> None:
        issues.append({"kind": kind, "subject_id": subject, "currency": currency,
                       "amount": str(amount.quantize(CENT)), "detail": detail})

    for payment in payments:
        invoice_id = payment["invoice_id"]
        if not invoice_id:
            issue("unapplied_payment", payment["payment_id"], payment["currency"],
                  payment["amount"], "No invoice reference; review in source system")
            continue
        invoice = invoices.get(invoice_id)
        if invoice is None:
            issue("unknown_invoice", payment["payment_id"], payment["currency"],
                  payment["amount"], f"Referenced invoice {invoice_id} absent from export")
        elif (invoice["customer_id"], invoice["currency"]) != (payment["customer_id"], payment["currency"]):
            issue("identity_or_currency_mismatch", payment["payment_id"], payment["currency"],
                  payment["amount"], f"Reference to {invoice_id} cannot be safely applied")
        else:
            applied[invoice_id] += payment["amount"]

    for invoice_id, invoice in invoices.items():
        balance = invoice["total"] - applied[invoice_id]
        if balance < 0:
            issue("overapplied_invoice", invoice_id, invoice["currency"], -balance,
                  "Applied payments exceed invoice total")
        elif balance > 0 and invoice["due_date"] < as_of:
            issue("overdue_balance", invoice_id, invoice["currency"], balance,
                  f"Due {invoice['due_date'].isoformat()}; verify current source balance")

    issues.sort(key=lambda item: (item["kind"], item["subject_id"]))
    counts = {kind: sum(item["kind"] == kind for item in issues)
              for kind in sorted({item["kind"] for item in issues})}
    return {
        "schema_version": "1.0", "as_of": as_of.isoformat(),
        "input_sha256": {"invoices": sha256(invoices_path.read_bytes()).hexdigest(),
                         "payments": sha256(payments_path.read_bytes()).hexdigest()},
        "invoice_count": len(invoices), "payment_count": len(payments),
        "issue_counts": counts, "review_queue": issues,
        "boundary": "Read-only export comparison. No write-back, live balance verification, collection, or recovered-cash claim.",
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Build a read-only finance reconciliation queue")
    parser.add_argument("invoices", type=Path)
    parser.add_argument("payments", type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = reconcile(args.invoices, args.payments, args.as_of)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
