from __future__ import annotations
from collections import Counter
from typing import Any
from .detect import detect
from .economics import economics
from .evidence import receipt
from .models import Transaction


class RevenueAssuranceEngine:
    def analyze(self,transactions:list[Transaction],recovered:dict[str,float],platform_cost_usd:float)->dict[str,Any]:
        findings=[f for tx in transactions for f in detect(tx)]
        payload={"transactions":len(transactions),"findings":[f.as_dict() for f in findings],"finding_counts":dict(Counter(f.finding_type for f in findings)),"approval_queue":sum(f.approval_required for f in findings),"economics":economics(findings,recovered,platform_cost_usd),"decision_boundary":"recovery is counted only from supplied verification evidence; approval-required actions are not executed by this engine"}
        return receipt(payload)
