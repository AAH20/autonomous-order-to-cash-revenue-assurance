import csv
import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from revenue_assurance.pilot import followup, prepare, run

ROOT = Path(__file__).resolve().parents[1] / "examples" / "recovery"
MANIFEST = ROOT / "pilot-manifest.json"


class PilotTests(unittest.TestCase):
    def test_declared_controls_and_review_queue(self):
        with TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            summary = run(MANIFEST, output)
            self.assertEqual(summary["finding_count"], 1)
            self.assertEqual(summary["possible_exposure_by_currency"], {"USD": "100.00"})
            self.assertTrue(summary["declared_source_controls_passed"])
            with (output / "review-queue.csv").open(newline="") as stream:
                queue = list(csv.DictReader(stream))
            self.assertEqual(queue[0]["order_id"], "O100")
            self.assertEqual(queue[0]["decision"], "")
            with self.assertRaisesRegex(ValueError, "never overwritten"):
                run(MANIFEST, output)

    def test_control_mismatch_fails_before_output(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            manifest = deepcopy(json.loads(MANIFEST.read_text()))
            for source in manifest["sources"].values():
                source["path"] = str(ROOT / source["path"])
            manifest["sources"]["orders"]["rows"] = 5
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "row count"):
                run(path, Path(temp) / "out")
            self.assertFalse((Path(temp) / "out").exists())
            manifest["sources"]["orders"]["rows"] = 6
            manifest["sources"]["orders"]["totals_by_currency"]["USD"] = "1.00"
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "amount totals"):
                prepare(path)

    def test_followup_preserves_noncausal_cash_boundary(self):
        with TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            run(MANIFEST, output)
            report = followup(output / "scan.json", ROOT / "reviews.csv",
                              ROOT / "invoices-followup.csv", ROOT / "payments-followup.csv",
                              ROOT / "ledger-followup.csv", Path(temp) / "followup.json")
            self.assertEqual(report["totals_by_currency"], {"USD": "100.00"})
            self.assertIn("not proof", report["boundary"])


if __name__ == "__main__":
    unittest.main()
