"""Read-only fulfilled-order leakage scan and later cash confirmation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .reconcile import _money, _required, _rows

ORDER_FIELDS = {"order_id", "customer_id", "currency", "total", "fulfilled_at", "status"}
INVOICE_FIELDS = {"invoice_id", "order_id", "customer_id", "currency", "total", "issued_at"}
PAYMENT_FIELDS = {"payment_id", "invoice_id", "customer_id", "currency", "amount", "received_at"}
LEDGER_FIELDS = {"entry_id", "payment_id", "currency", "amount", "posted_at"}
CENT = Decimal("0.01")


def _date(row: dict, field: str) -> date:
    try:
        return date.fromisoformat(_required(row, field))
    except ValueError:
        raise ValueError(f"invalid {field} date") from None


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finding_id(order: dict) -> str:
    raw = "\0".join((order["order_id"], order["customer_id"], order["currency"],
                      str(order["total"]), order["fulfilled_at"].isoformat()))
    return "F-" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def _orders(path: Path) -> dict[str, dict]:
    result = {}
    for row in _rows(path, ORDER_FIELDS):
        order_id = _required(row, "order_id")
        if order_id in result:
            raise ValueError(f"duplicate order_id: {order_id}")
        status = _required(row, "status").lower()
        if status not in {"fulfilled", "pending", "cancelled"}:
            raise ValueError("order status must be fulfilled, pending or cancelled")
        result[order_id] = {
            "order_id": order_id, "customer_id": _required(row, "customer_id"),
            "currency": _required(row, "currency").upper(),
            "total": _money(row["total"], "order total"),
            "fulfilled_at": _date(row, "fulfilled_at") if status == "fulfilled" else None,
            "status": status,
        }
    return result


def _invoices(path: Path) -> dict[str, dict]:
    result = {}
    for row in _rows(path, INVOICE_FIELDS):
        invoice_id = _required(row, "invoice_id")
        if invoice_id in result:
            raise ValueError(f"duplicate invoice_id: {invoice_id}")
        result[invoice_id] = {
            "invoice_id": invoice_id, "order_id": _required(row, "order_id"),
            "customer_id": _required(row, "customer_id"),
            "currency": _required(row, "currency").upper(),
            "total": _money(row["total"], "invoice total"),
            "issued_at": _date(row, "issued_at"),
        }
    return result


def scan(orders_path: Path, invoices_path: Path, *, as_of: date,
         invoice_export_through: date, grace_days: int = 7) -> dict:
    if type(grace_days) is not int or not 0 <= grace_days <= 90:
        raise ValueError("grace_days must be 0..90")
    if invoice_export_through < as_of:
        raise ValueError("invoice export must cover the scan date")
    orders = _orders(orders_path)
    invoices = _invoices(invoices_path)
    by_order: dict[str, list[dict]] = {}
    for invoice in invoices.values():
        if invoice["issued_at"] > invoice_export_through:
            raise ValueError("invoice dated after declared export cutoff")
        if invoice["issued_at"] <= as_of:
            by_order.setdefault(invoice["order_id"], []).append(invoice)
    findings = []
    held = []
    for order in orders.values():
        if order["status"] != "fulfilled":
            continue
        if order["fulfilled_at"] > as_of:
            raise ValueError("fulfilled order dated after scan date")
        linked = by_order.get(order["order_id"], [])
        if not linked and order["total"] > 0 and order["fulfilled_at"] + timedelta(days=grace_days) <= as_of:
            findings.append({"finding_id": _finding_id(order), "order_id": order["order_id"],
                             "customer_id": order["customer_id"], "currency": order["currency"],
                             "exposed_amount": str(order["total"].quantize(CENT)),
                             "fulfilled_at": order["fulfilled_at"].isoformat(),
                             "status": "FINANCE_REVIEW_REQUIRED"})
        elif linked and (len(linked) != 1 or any(
                (item["customer_id"], item["currency"], item["total"]) !=
                (order["customer_id"], order["currency"], order["total"]) for item in linked)):
            held.append({"order_id": order["order_id"], "reason": "invoice_link_or_amount_mismatch"})
    findings.sort(key=lambda item: item["finding_id"])
    held.sort(key=lambda item: item["order_id"])
    return {
        "schema_version": "1.0", "as_of": as_of.isoformat(),
        "invoice_export_through": invoice_export_through.isoformat(),
        "grace_days": grace_days, "orders": len(orders), "invoices": len(invoices),
        "input_sha256": {"orders": _hash(orders_path), "invoices": _hash(invoices_path)},
        "findings": findings, "held_for_manual_review": held,
        "boundary": "Export completeness is operator-declared. Findings are possible missing invoices, not verified receivables or recovered cash. No write-back.",
    }


def _payments(path: Path) -> dict[str, dict]:
    result = {}
    for row in _rows(path, PAYMENT_FIELDS):
        payment_id = _required(row, "payment_id")
        if payment_id in result:
            raise ValueError(f"duplicate payment_id: {payment_id}")
        result[payment_id] = {
            "invoice_id": _required(row, "invoice_id"), "customer_id": _required(row, "customer_id"),
            "currency": _required(row, "currency").upper(), "amount": _money(row["amount"], "payment"),
            "received_at": _date(row, "received_at"),
        }
    return result


def _ledger(path: Path) -> dict[str, dict]:
    result = {}
    for row in _rows(path, LEDGER_FIELDS):
        entry_id = _required(row, "entry_id")
        if entry_id in result:
            raise ValueError(f"duplicate entry_id: {entry_id}")
        result[entry_id] = {
            "payment_id": _required(row, "payment_id"), "currency": _required(row, "currency").upper(),
            "amount": _money(row["amount"], "ledger amount"), "posted_at": _date(row, "posted_at"),
        }
    return result


def confirm(scan_report: dict, reviews_path: Path, invoices_path: Path,
            payments_path: Path, ledger_path: Path) -> dict:
    if scan_report.get("schema_version") != "1.0" or not isinstance(scan_report.get("findings"), list):
        raise ValueError("scan report schema is invalid")
    as_of = date.fromisoformat(scan_report["as_of"])
    if not isinstance(scan_report.get("input_sha256"), dict):
        raise TypeError("scan input digests are missing")
    findings = {}
    for item in scan_report["findings"]:
        if not isinstance(item, dict) or item.get("status") != "FINANCE_REVIEW_REQUIRED":
            raise ValueError("scan finding is invalid")
        finding_id = _required(item, "finding_id")
        if finding_id in findings:
            raise ValueError("duplicate scan finding")
        for field in ("order_id", "customer_id", "currency"):
            _required(item, field)
        exposed = _money(item.get("exposed_amount"), "exposed amount")
        expected_id = _finding_id({"order_id": item["order_id"], "customer_id": item["customer_id"],
                                   "currency": item["currency"], "total": exposed,
                                   "fulfilled_at": _date(item, "fulfilled_at")})
        if finding_id != expected_id:
            raise ValueError("scan finding identity mismatch")
        findings[finding_id] = item
    reviews = {}
    for row in _rows(reviews_path, {"finding_id", "reviewer", "decision", "reviewed_at"}):
        finding_id = _required(row, "finding_id")
        if finding_id not in findings or finding_id in reviews:
            raise ValueError("unknown or duplicate review finding ID")
        decision = _required(row, "decision")
        if decision not in {"confirmed_uninvoiced", "not_an_issue"}:
            raise ValueError("review decision is invalid")
        reviewed_at = _date(row, "reviewed_at")
        if reviewed_at < as_of:
            raise ValueError("review predates scan")
        reviews[finding_id] = {"reviewer": _required(row, "reviewer"), "decision": decision,
                               "reviewed_at": reviewed_at}
    invoices = _invoices(invoices_path)
    payments = _payments(payments_path)
    ledger = _ledger(ledger_path)
    by_payment: dict[str, list[dict]] = {}
    for entry in ledger.values():
        by_payment.setdefault(entry["payment_id"], []).append(entry)
    results = []
    totals: dict[str, Decimal] = {}
    for finding_id, finding in sorted(findings.items()):
        review = reviews.get(finding_id)
        amount = Decimal(0)
        status = "UNREVIEWED" if review is None else "REJECTED_BY_REVIEWER"
        if review and review["decision"] == "confirmed_uninvoiced":
            status = "REVIEWED_NO_CONFIRMED_CASH"
            matching = [inv for inv in invoices.values()
                        if inv["order_id"] == finding["order_id"] and inv["customer_id"] == finding["customer_id"]
                        and inv["currency"] == finding["currency"] and inv["total"] == Decimal(finding["exposed_amount"])
                        and inv["issued_at"] > review["reviewed_at"]]
            if len(matching) == 1:
                invoice = matching[0]
                for payment_id, payment in payments.items():
                    entries = by_payment.get(payment_id, [])
                    if (payment["invoice_id"] == invoice["invoice_id"]
                            and payment["customer_id"] == finding["customer_id"]
                            and payment["currency"] == finding["currency"]
                            and payment["received_at"] >= invoice["issued_at"]
                            and len(entries) == 1 and entries[0]["currency"] == finding["currency"]
                            and entries[0]["amount"] == payment["amount"]
                            and entries[0]["posted_at"] >= payment["received_at"]):
                        amount += payment["amount"]
                if amount > Decimal(finding["exposed_amount"]):
                    amount = Decimal(0)
                    status = "OVERPAYMENT_REQUIRES_REVIEW"
                elif amount > 0:
                    status = "LEDGER_CONFIRMED_CASH_AFTER_FINDING"
                    totals[finding["currency"]] = totals.get(finding["currency"], Decimal(0)) + amount
        results.append({"finding_id": finding_id, "order_id": finding["order_id"], "status": status,
                        "currency": finding["currency"], "ledger_confirmed_cash_after_finding": str(amount.quantize(CENT))})
    return {
        "schema_version": "1.0", "scan_input_sha256": scan_report["input_sha256"],
        "followup_input_sha256": {"reviews": _hash(reviews_path), "invoices": _hash(invoices_path),
                                  "payments": _hash(payments_path), "ledger": _hash(ledger_path)},
        "findings": results,
        "totals_by_currency": {currency: str(value.quantize(CENT)) for currency, value in sorted(totals.items())},
        "boundary": "Reviews and exports are unauthenticated operator-supplied records. Ledger-linked cash after a finding is not proof the finding caused collection, nor a fee basis without customer agreement.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only order-to-cash recovery pilot")
    commands = parser.add_subparsers(dest="command", required=True)
    scan_cmd = commands.add_parser("scan")
    scan_cmd.add_argument("orders", type=Path)
    scan_cmd.add_argument("invoices", type=Path)
    scan_cmd.add_argument("--as-of", type=date.fromisoformat, required=True)
    scan_cmd.add_argument("--invoice-export-through", type=date.fromisoformat, required=True)
    scan_cmd.add_argument("--grace-days", type=int, default=7)
    scan_cmd.add_argument("--output", type=Path, required=True)
    confirm_cmd = commands.add_parser("confirm")
    confirm_cmd.add_argument("scan_report", type=Path)
    confirm_cmd.add_argument("reviews", type=Path)
    confirm_cmd.add_argument("invoices", type=Path)
    confirm_cmd.add_argument("payments", type=Path)
    confirm_cmd.add_argument("ledger", type=Path)
    confirm_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "scan":
        report = scan(args.orders, args.invoices, as_of=args.as_of,
                      invoice_export_through=args.invoice_export_through, grace_days=args.grace_days)
    else:
        report = confirm(json.loads(args.scan_report.read_text()), args.reviews,
                         args.invoices, args.payments, args.ledger)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"{args.command}: {len(report['findings'])} findings; output={args.output}")


if __name__ == "__main__":
    main()
