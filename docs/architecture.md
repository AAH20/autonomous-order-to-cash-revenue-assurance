# Architecture and evidence boundary

Production adapters emit normalized order, fulfillment, invoice, payment, cash-application and ledger events. The transaction twin identifies impossible or missing transitions. Agents may investigate and propose; deterministic policy controls execution. Recovery is counted only after a trusted source verifies the resulting cash or ledger state.

Implemented locally: detection, economics, idempotency and evidence receipts. Simulated: all transactions and recovery. Contract-only: SAP, Salesforce and Azure integrations.

