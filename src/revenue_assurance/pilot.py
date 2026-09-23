"""Local, read-only monthly customer pilot packaging for revenue recovery."""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from .recovery_operator import _invoices, _orders, confirm, scan

CENT = Decimal("0.01")


def _money_map(rows: dict[str, dict], field: str) -> dict[str, str]:
    totals: dict[str, Decimal] = {}
    for row in rows.values():
        currency = row["currency"]
        totals[currency] = totals.get(currency, Decimal(0)) + row[field]
    return {key: str(value.quantize(CENT)) for key, value in sorted(totals.items())}


def _control(source: dict, rows: dict[str, dict], amount_field: str, label: str) -> None:
    if not isinstance(source, dict) or type(source.get("rows")) is not int or source["rows"] < 0:
        raise ValueError(f"{label} control requires a nonnegative integer row count")
    if source["rows"] != len(rows):
        raise ValueError(f"{label} row count differs from customer declaration")
    declared = source.get("totals_by_currency")
    if not isinstance(declared, dict):
        raise TypeError(f"{label} control requires totals_by_currency")
    normalized = {}
    for currency, amount in declared.items():
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError(f"{label} has an invalid currency code")
        try:
            value = Decimal(str(amount))
        except Exception as exc:
            raise ValueError(f"{label} has an invalid control amount") from exc
        if not value.is_finite() or value < 0 or value != value.quantize(CENT):
            raise ValueError(f"{label} has an invalid control amount")
        normalized[currency] = str(value.quantize(CENT))
    if normalized != _money_map(rows, amount_field):
        raise ValueError(f"{label} amount totals differ from customer declaration")


def _source_path(manifest_path: Path, source: dict, label: str) -> Path:
    if not isinstance(source, dict) or not isinstance(source.get("path"), str) or not source["path"]:
        raise ValueError(f"{label} source path is required")
    path = (manifest_path.parent / source["path"]).resolve()
    if not path.is_file():
        raise ValueError(f"{label} source file does not exist")
    return path


def prepare(manifest_path: Path) -> tuple[dict, dict]:
    """Validate operator declarations and prepare a scan plus non-PII run summary."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1.0":
        raise ValueError("pilot manifest schema_version must be 1.0")
    customer_key = manifest.get("customer_key")
    if not isinstance(customer_key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}", customer_key):
        raise ValueError("customer_key must be a pseudonymous slug of 3-64 characters")
    period = manifest.get("period")
    if not isinstance(period, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise ValueError("period must be YYYY-MM")
    as_of = date.fromisoformat(manifest["as_of"])
    year, month = map(int, period.split("-"))
    if as_of < date(year, month, calendar.monthrange(year, month)[1]):
        raise ValueError("scan date must not precede the closed pilot period")
    cutoff = date.fromisoformat(manifest["invoice_export_through"])
    sources = manifest.get("sources")
    if not isinstance(sources, dict):
        raise TypeError("sources are required")
    orders_source, invoices_source = sources.get("orders"), sources.get("invoices")
    orders_path = _source_path(manifest_path, orders_source, "orders")
    invoices_path = _source_path(manifest_path, invoices_source, "invoices")
    orders = _orders(orders_path)
    invoices = _invoices(invoices_path)
    _control(orders_source, orders, "total", "orders")
    _control(invoices_source, invoices, "total", "invoices")
    report = scan(orders_path, invoices_path, as_of=as_of,
                  invoice_export_through=cutoff, grace_days=manifest.get("grace_days", 7))
    exposed: dict[str, Decimal] = {}
    for finding in report["findings"]:
        currency = finding["currency"]
        exposed[currency] = exposed.get(currency, Decimal(0)) + Decimal(finding["exposed_amount"])
    summary = {
        "schema_version": "1.0", "customer_key": customer_key, "period": period,
        "as_of": report["as_of"], "input_sha256": report["input_sha256"],
        "declared_source_controls_passed": True,
        "orders": report["orders"], "invoices": report["invoices"],
        "finding_count": len(report["findings"]),
        "held_count": len(report["held_for_manual_review"]),
        "possible_exposure_by_currency": {
            key: str(value.quantize(CENT)) for key, value in sorted(exposed.items())},
        "boundary": "Customer-declared file controls passed, but origin and completeness are not independently attested. Exposure is not a receivable or recovered cash.",
    }
    return report, summary


def run(manifest_path: Path, output_dir: Path) -> dict:
    report, summary = prepare(manifest_path)
    if output_dir.exists():
        raise ValueError("output directory already exists; runs are never overwritten")
    output_dir.mkdir(parents=True)
    (output_dir / "scan.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    with (output_dir / "review-queue.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["finding_id", "order_id", "customer_id", "currency", "exposed_amount",
                         "fulfilled_at", "reviewer", "decision", "reviewed_at"])
        for item in report["findings"]:
            writer.writerow([item[key] for key in ("finding_id", "order_id", "customer_id", "currency",
                                                    "exposed_amount", "fulfilled_at")] + ["", "", ""])
    return summary


def followup(scan_path: Path, reviews_path: Path, invoices_path: Path,
             payments_path: Path, ledger_path: Path, output_path: Path) -> dict:
    if output_path.exists():
        raise ValueError("follow-up output already exists; reports are never overwritten")
    report = confirm(json.loads(scan_path.read_text(encoding="utf-8")), reviews_path,
                     invoices_path, payments_path, ledger_path)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Local read-only revenue recovery customer pilot")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run")
    run_cmd.add_argument("manifest", type=Path)
    run_cmd.add_argument("--output-dir", type=Path, required=True)
    follow_cmd = commands.add_parser("followup")
    for name in ("scan", "reviews", "invoices", "payments", "ledger"):
        follow_cmd.add_argument(name, type=Path)
    follow_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        result = run(args.manifest, args.output_dir)
        print(f"pilot: {result['finding_count']} findings; output={args.output_dir}")
    else:
        result = followup(args.scan, args.reviews, args.invoices, args.payments,
                          args.ledger, args.output)
        print(f"followup: {len(result['findings'])} findings; output={args.output}")


if __name__ == "__main__":
    main()
