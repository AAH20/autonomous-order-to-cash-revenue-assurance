from __future__ import annotations
from .models import Finding


def economics(findings: list[Finding], recovered: dict[str,float], platform_cost_usd: float) -> dict[str,float|None]:
    exposed=sum(item.exposed_value_usd for item in findings)
    recovered_value=sum(min(item.exposed_value_usd,max(0,recovered.get(item.idempotency_key,0))) for item in findings)
    net=recovered_value-platform_cost_usd
    return {"exposed_value_usd":round(exposed,2),"verified_recovered_usd":round(recovered_value,2),"platform_cost_usd":round(platform_cost_usd,2),"net_recovered_usd":round(net,2),"cost_per_recovered_dollar":round(platform_cost_usd/recovered_value,4) if recovered_value else None,"recovery_rate":round(recovered_value/exposed,4) if exposed else 0.0}

