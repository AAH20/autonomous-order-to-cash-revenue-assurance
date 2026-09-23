from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from revenue_assurance.reconcile import reconcile


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "reconciliation"


class ReconcileTests(unittest.TestCase):
    def test_review_queue_never_calls_exposure_recovery(self):
        report = reconcile(EXAMPLES / "invoices.csv", EXAMPLES / "payments.csv", date(2026, 9, 23))
        self.assertEqual(report["issue_counts"], {
            "identity_or_currency_mismatch": 1,
            "overapplied_invoice": 1,
            "overdue_balance": 1,
            "unapplied_payment": 1,
            "unknown_invoice": 1,
        })
        overdue = next(item for item in report["review_queue"] if item["kind"] == "overdue_balance")
        self.assertEqual(overdue["amount"], "50.00")
        self.assertNotIn("recovered_usd", report)
        self.assertEqual(len(report["input_sha256"]["invoices"]), 64)

    def test_duplicate_payment_rejected(self):
        with TemporaryDirectory() as directory:
            payments = Path(directory) / "payments.csv"
            payments.write_text("payment_id,customer_id,currency,amount,invoice_id\n"
                                "p1,c,USD,1.00,\np1,c,USD,1.00,\n")
            with self.assertRaisesRegex(ValueError, "duplicate payment_id"):
                reconcile(EXAMPLES / "invoices.csv", payments, date(2026, 9, 23))

    def test_fractional_cent_rejected(self):
        with TemporaryDirectory() as directory:
            payments = Path(directory) / "payments.csv"
            payments.write_text("payment_id,customer_id,currency,amount,invoice_id\n"
                                "p1,c,USD,1.001,\n")
            with self.assertRaisesRegex(ValueError, "at most two decimals"):
                reconcile(EXAMPLES / "invoices.csv", payments, date(2026, 9, 23))


if __name__ == "__main__":
    unittest.main()
