"""Local, application-level write-once reviews bound to one monthly pilot run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return value


class ReviewDesk:
    """Single-customer local reviewer workflow; reviewer identity is self-declared."""

    def __init__(self, run_dir: Path, *, create: bool = False):
        self.run_dir = Path(run_dir)
        scan_path = self.run_dir / "scan.json"
        self.scan, self.summary = _read(scan_path), _read(self.run_dir / "summary.json")
        if self.summary.get("input_sha256") != self.scan.get("input_sha256"):
            raise ValueError("scan and run summary source hashes differ")
        if self.summary.get("period") != self.scan.get("order_period") or self.summary.get("as_of") != self.scan.get("as_of"):
            raise ValueError("scan and summary scope differ")
        if self.scan.get("schema_version") != "1.0" or not isinstance(self.scan.get("findings"), list):
            raise ValueError("invalid scan report")
        self.findings = {item["finding_id"]: item for item in self.scan["findings"]}
        if len(self.findings) != len(self.scan["findings"]):
            raise ValueError("duplicate finding IDs")
        self.scan_sha256 = hashlib.sha256(scan_path.read_bytes()).hexdigest()
        self.db = self.run_dir / "finance-review.sqlite3"
        if create:
            if self.db.exists():
                raise ValueError("review desk already exists")
            with closing(sqlite3.connect(self.db)) as conn, conn:
                conn.execute("CREATE TABLE scope (scan_sha256 TEXT PRIMARY KEY, customer_key TEXT NOT NULL, period TEXT NOT NULL)")
                conn.execute("CREATE TABLE decisions (finding_id TEXT PRIMARY KEY, decision TEXT NOT NULL, reviewer TEXT NOT NULL, reviewed_at TEXT NOT NULL, review_minutes INTEGER NOT NULL, recorded_at TEXT NOT NULL)")
                conn.execute("INSERT INTO scope VALUES (?,?,?)", (self.scan_sha256, self.summary["customer_key"], self.summary["period"]))
            os.chmod(self.db, 0o600)
        elif not self.db.is_file():
            raise ValueError("review desk missing; initialize it first")
        with closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute("SELECT scan_sha256,customer_key,period FROM scope").fetchone()
        if row != (self.scan_sha256, self.summary["customer_key"], self.summary["period"]):
            raise ValueError("review desk is bound to a different scan or customer period")

    def review(self, finding_id: str, decision: str, reviewer: str, minutes: int) -> dict:
        if finding_id not in self.findings:
            raise ValueError("finding not in locked scan")
        if decision not in ("confirmed_uninvoiced", "not_an_issue"):
            raise ValueError("invalid review decision")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 128:
            raise ValueError("named reviewer required")
        if type(minutes) is not int or not 0 <= minutes <= 480:
            raise ValueError("review minutes must be an integer from 0 to 480")
        today = datetime.now(UTC).date()
        if today < date.fromisoformat(self.scan["as_of"]):
            raise ValueError("review cannot precede scan date")
        with closing(sqlite3.connect(self.db)) as conn, conn:
            try:
                conn.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?)",
                             (finding_id, decision, reviewer.strip(), today.isoformat(), minutes,
                              datetime.now(UTC).isoformat()))
            except sqlite3.IntegrityError:
                raise ValueError("finding already reviewed; correction requires a new controlled run") from None
        return {"finding_id": finding_id, "decision": decision, "reviewer": reviewer.strip(),
                "reviewed_at": today.isoformat(), "review_minutes": minutes,
                "evidence_class": "OPERATOR_DECLARED_UNAUTHENTICATED"}

    def decisions(self) -> list[dict]:
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM decisions ORDER BY finding_id").fetchall()
        return [dict(row) for row in rows]

    def export(self, output: Path) -> dict:
        if output.exists():
            raise ValueError("review export already exists")
        rows = self.decisions()
        with output.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["finding_id", "reviewer", "decision", "reviewed_at"])
            for row in rows:
                writer.writerow([row[key] for key in ("finding_id", "reviewer", "decision", "reviewed_at")])
        return {"export": str(output), "decisions": len(rows), "scan_sha256": self.scan_sha256,
                "evidence_class": "OPERATOR_DECLARED_UNAUTHENTICATED"}

    def metrics(self, hourly_rate_usd: str | None = None) -> dict:
        rows = self.decisions()
        minutes = sum(row["review_minutes"] for row in rows)
        result = {"customer_key": self.summary["customer_key"], "period": self.summary["period"],
                  "scan_sha256": self.scan_sha256, "findings": len(self.findings), "reviewed": len(rows),
                  "confirmed_uninvoiced": sum(row["decision"] == "confirmed_uninvoiced" for row in rows),
                  "not_an_issue": sum(row["decision"] == "not_an_issue" for row in rows),
                  "review_minutes": minutes, "review_cost_usd": None,
                  "modeled_review_cost_per_confirmed_finding_usd": None,
                  "verified_recovered_cash_usd": None,
                  "boundary": "Reviews and time are operator-declared; identity, source completeness, causal recovery and actual labor cost are not verified."}
        if hourly_rate_usd is not None:
            try:
                rate = Decimal(hourly_rate_usd)
            except (InvalidOperation, TypeError):
                raise ValueError("hourly rate must be a nonnegative USD amount") from None
            if not rate.is_finite() or rate < 0 or rate.as_tuple().exponent < -2:
                raise ValueError("hourly rate must be a nonnegative USD amount with at most two decimals")
            result["assumed_hourly_rate_usd"] = str(rate.quantize(Decimal("0.01")))
            result["review_cost_usd"] = str((rate * Decimal(minutes) / 60).quantize(Decimal("0.01")))
            if result["confirmed_uninvoiced"]:
                result["modeled_review_cost_per_confirmed_finding_usd"] = str(
                    (Decimal(result["review_cost_usd"]) / result["confirmed_uninvoiced"]).quantize(Decimal("0.01")))
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Finance review journal for one local recovery pilot")
    parser.add_argument("run_dir", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    review = commands.add_parser("review")
    review.add_argument("finding_id")
    review.add_argument("--decision", required=True, choices=("confirmed_uninvoiced", "not_an_issue"))
    review.add_argument("--reviewer", required=True)
    review.add_argument("--minutes", required=True, type=int)
    export = commands.add_parser("export")
    export.add_argument("--output", required=True, type=Path)
    metrics = commands.add_parser("metrics")
    metrics.add_argument("--hourly-rate-usd")
    args = parser.parse_args()
    desk = ReviewDesk(args.run_dir, create=args.command == "init")
    if args.command == "review":
        result = desk.review(args.finding_id, args.decision, args.reviewer, args.minutes)
    elif args.command == "export":
        result = desk.export(args.output)
    else:
        result = desk.metrics(getattr(args, "hourly_rate_usd", None))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
