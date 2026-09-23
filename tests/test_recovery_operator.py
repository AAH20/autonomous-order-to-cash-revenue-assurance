import csv
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from revenue_assurance.recovery_operator import confirm, scan

ROOT = Path(__file__).resolve().parents[1] / "examples" / "recovery"
SCAN_DATE = date(2026, 9, 10)


def synthetic_scan():
    return scan(ROOT / "orders.csv", ROOT / "invoices-scan.csv",
                as_of=SCAN_DATE, invoice_export_through=SCAN_DATE)


class RecoveryOperatorTests(unittest.TestCase):
    def test_fulfilled_uninvoiced_queue_is_separate_from_mismatches(self):
        report = synthetic_scan()
        self.assertEqual([item["order_id"] for item in report["findings"]], ["O100"])
        self.assertEqual(report["findings"][0]["exposed_amount"], "100.00")
        self.assertEqual(report["held_for_manual_review"],
                         [{"order_id": "O400", "reason": "invoice_link_or_amount_mismatch"}])
        self.assertNotIn("recovered", report["boundary"].lower().split(". ")[0])

    def test_later_invoice_does_not_erase_historical_finding(self):
        report = scan(ROOT / "orders.csv", ROOT / "invoices-followup.csv",
                      as_of=SCAN_DATE, invoice_export_through=date(2026, 9, 12))
        self.assertEqual([item["order_id"] for item in report["findings"]], ["O100"])
        with self.assertRaisesRegex(ValueError, "cover the scan date"):
            scan(ROOT / "orders.csv", ROOT / "invoices-scan.csv", as_of=SCAN_DATE,
                 invoice_export_through=date(2026, 9, 9))

    def test_review_and_ledger_confirm_cash_after_finding(self):
        report = confirm(synthetic_scan(), ROOT / "reviews.csv", ROOT / "invoices-followup.csv",
                         ROOT / "payments-followup.csv", ROOT / "ledger-followup.csv")
        self.assertEqual(report["findings"][0]["status"], "LEDGER_CONFIRMED_CASH_AFTER_FINDING")
        self.assertEqual(report["totals_by_currency"], {"USD": "100.00"})
        self.assertIn("not proof", report["boundary"])

    def test_tampered_finding_and_missing_ledger_are_not_confirmed(self):
        altered = deepcopy(synthetic_scan())
        altered["findings"][0]["exposed_amount"] = "999.00"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            confirm(altered, ROOT / "reviews.csv", ROOT / "invoices-followup.csv",
                    ROOT / "payments-followup.csv", ROOT / "ledger-followup.csv")
        with TemporaryDirectory() as temp:
            empty = Path(temp) / "ledger.csv"
            with empty.open("w", newline="") as stream:
                csv.writer(stream).writerow(["entry_id", "payment_id", "currency", "amount", "posted_at"])
            report = confirm(synthetic_scan(), ROOT / "reviews.csv", ROOT / "invoices-followup.csv",
                             ROOT / "payments-followup.csv", empty)
            self.assertEqual(report["findings"][0]["status"], "REVIEWED_NO_CONFIRMED_CASH")
            self.assertEqual(report["totals_by_currency"], {})

    def test_duplicate_review_is_rejected(self):
        with TemporaryDirectory() as temp:
            duplicated = Path(temp) / "reviews.csv"
            text = (ROOT / "reviews.csv").read_text()
            duplicated.write_text(text + text.splitlines()[1] + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate review"):
                confirm(synthetic_scan(), duplicated, ROOT / "invoices-followup.csv",
                        ROOT / "payments-followup.csv", ROOT / "ledger-followup.csv")


if __name__ == "__main__":
    unittest.main()
