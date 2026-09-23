# Read-only reconciliation pilot

`o2c-reconcile` takes two **normalized CSV exports** and produces a daily finance review queue. It does not log in to QuickBooks, Stripe, a bank or an ERP; it does not send collection messages, change a ledger, or claim recovery. The included files are fictional.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
o2c-reconcile examples/reconciliation/invoices.csv examples/reconciliation/payments.csv \
  --as-of 2026-09-23 --output /tmp/o2c-review-queue.json
```

The invoice CSV requires `invoice_id,customer_id,currency,total,due_date`; the payment CSV requires `payment_id,customer_id,currency,amount,invoice_id`. Dates are ISO `YYYY-MM-DD`, amounts are nonnegative decimal units with at most two places, and each row must have a unique invoice or payment ID. A payment with no invoice reference becomes `unapplied_payment`. A payment with a reference is counted toward an invoice only when ID, customer and currency match. Unknown references and mismatches are held for review. Positive balances become `overdue_balance` only after the due date; excess applied amounts become `overapplied_invoice`.

The output includes input-file SHA-256 digests to identify the exact exports used, issue counts, and a sorted review queue. It intentionally omits an aggregate money total across currencies and any recovered-cash figure. The queue is a **lead for human review**, not a ledger balance or collection instruction.

## First customer pilot

1. Obtain written permission for a historical export and keep it in customer-controlled storage. Do not commit real exports to Git. Use a finance-approved mapping into the two CSV contracts and reconcile row counts and control totals before running the tool.
2. Run a single closed historical month. Finance reviews each issue against the source ledger, marks true/false positives and records disposition time. Compare the queue with their existing close process.
3. Only after read-only accuracy is established, design an authenticated QuickBooks connector and a separate approved write-back workflow. This release has neither. QuickBooks represents [invoices](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/most-commonly-used/invoice) and [payments](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/Payment) as distinct objects; its payment-to-invoice linkage and unapplied amounts must be mapped explicitly rather than inferred from equal dollar values.

Track precision of reviewed issues, missed issues found by finance, analyst minutes per resolved issue, close time, and cash actually confirmed in the ledger after an intervention. Do not treat an `unapplied_payment` amount as new cash: it may already have been received. The CSV contract cannot represent one payment allocated to multiple invoices, refunds, credit memos, reversals, multi-currency conversion, or partial unapplied amounts on a linked payment. Reject or pre-normalize those cases explicitly rather than silently folding them into this pilot.
