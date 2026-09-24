import csv
import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from revenue_assurance.pilot import followup, run
from revenue_assurance.review_desk import ReviewDesk

ROOT = Path(__file__).resolve().parents[1] / "examples" / "recovery"
MANIFEST = ROOT / "pilot-manifest.json"


class ReviewDeskTests(unittest.TestCase):
    def test_full_review_and_followup(self):
        with TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run(MANIFEST, run_dir)
            desk = ReviewDesk(run_dir, create=True)
            finding = next(iter(desk.findings))
            result = desk.review(finding, "confirmed_uninvoiced", "Finance Reviewer", 12)
            self.assertEqual(result["evidence_class"], "OPERATOR_DECLARED_UNAUTHENTICATED")
            metrics = desk.metrics("60.00")
            self.assertEqual(metrics["review_minutes"], 12)
            self.assertEqual(metrics["review_cost_usd"], "12.00")
            self.assertEqual(metrics["modeled_review_cost_per_confirmed_finding_usd"], "12.00")
            self.assertIsNone(metrics["verified_recovered_cash_usd"])
            reviews = Path(temp) / "reviews.csv"
            desk.export(reviews)
            with reviews.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["decision"], "confirmed_uninvoiced")
            report = followup(run_dir / "scan.json", reviews, ROOT / "invoices-followup.csv",
                              ROOT / "payments-followup.csv", ROOT / "ledger-followup.csv",
                              Path(temp) / "followup.json")
            # The committed follow-up invoice predates this newly recorded review.
            # The engine correctly refuses to present that cash as post-review.
            self.assertEqual(report["totals_by_currency"], {})
            self.assertEqual(report["findings"][0]["status"], "REVIEWED_NO_CONFIRMED_CASH")
            with self.assertRaisesRegex(ValueError, "already reviewed"):
                desk.review(finding, "not_an_issue", "Finance Reviewer", 1)
            with self.assertRaisesRegex(ValueError, "already exists"):
                desk.export(reviews)

    def test_wrong_finding_and_invalid_rate(self):
        with TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run(MANIFEST, run_dir)
            desk = ReviewDesk(run_dir, create=True)
            with self.assertRaisesRegex(ValueError, "locked scan"):
                desk.review("unknown", "confirmed_uninvoiced", "A", 10)
            with self.assertRaisesRegex(ValueError, "hourly rate"):
                desk.metrics("NaN")
            with self.assertRaisesRegex(ValueError, "review desk already exists"):
                ReviewDesk(run_dir, create=True)

    def test_scan_tamper_blocks_existing_journal(self):
        with TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run(MANIFEST, run_dir)
            ReviewDesk(run_dir, create=True)
            scan_path = run_dir / "scan.json"
            scan = json.loads(scan_path.read_text())
            scan["boundary"] = "changed"
            scan_path.write_text(json.dumps(scan))
            with self.assertRaisesRegex(ValueError, "different scan"):
                ReviewDesk(run_dir)

    def test_pilot_excludes_other_month_even_when_old_enough(self):
        with TemporaryDirectory() as temp:
            temp_path = Path(temp)
            orders = temp_path / "orders.csv"
            orders.write_text((ROOT / "orders.csv").read_text().replace("2026-09-07", "2026-09-01"))
            manifest = deepcopy(json.loads(MANIFEST.read_text()))
            manifest["sources"]["orders"]["path"] = "orders.csv"
            manifest["sources"]["invoices"]["path"] = str(ROOT / "invoices-scan.csv")
            path = temp_path / "manifest.json"
            path.write_text(json.dumps(manifest))
            run_dir = temp_path / "run"
            summary = run(path, run_dir)
            self.assertEqual(summary["finding_count"], 1)
            self.assertEqual(summary["in_scope_fulfilled_orders"], 3)
            scan = json.loads((run_dir / "scan.json").read_text())
            self.assertEqual(scan["order_period"], "2026-08")
            self.assertEqual({item["order_id"] for item in scan["findings"]}, {"O100"})


if __name__ == "__main__":
    unittest.main()
