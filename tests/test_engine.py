import unittest
from revenue_assurance.detect import detect
from revenue_assurance.engine import RevenueAssuranceEngine
from revenue_assurance.models import Transaction

def tx(**updates):
    base=dict(order_id="o",customer_id="c",currency="USD",ordered_usd=100,fulfilled_usd=100,invoiced_usd=100,paid_usd=100,applied_usd=100,ledger_usd=100,expected_price_usd=100,invoiced_price_usd=100,order_accepted=True,shipment_complete=True,invoice_created=True,payment_received=True,dispute_open=False,credit_hold=False,age_days=1)
    base.update(updates);return Transaction(**base)

class Tests(unittest.TestCase):
    def test_shipped_not_invoiced_requires_approval(self):
        finding=detect(tx(invoice_created=False,invoiced_usd=0))[0]
        self.assertEqual(finding.finding_type,"shipped-not-invoiced");self.assertTrue(finding.approval_required)
    def test_unapplied_cash_can_be_verified(self):
        finding=detect(tx(applied_usd=0))[0]
        result=RevenueAssuranceEngine().analyze([tx(applied_usd=0)],{finding.idempotency_key:80},10)
        self.assertEqual(result["payload"]["economics"]["verified_recovered_usd"],80)
        self.assertEqual(result["payload"]["economics"]["net_recovered_usd"],70)
    def test_recovery_cannot_exceed_exposure(self):
        finding=detect(tx(applied_usd=0))[0]
        result=RevenueAssuranceEngine().analyze([tx(applied_usd=0)],{finding.idempotency_key:1000},0)
        self.assertEqual(result["payload"]["economics"]["verified_recovered_usd"],100)
    def test_duplicate_payment_is_critical(self):
        finding=detect(tx(duplicate_payment_count=1))[0]
        self.assertEqual(finding.severity,"critical")
if __name__=="__main__":unittest.main()

