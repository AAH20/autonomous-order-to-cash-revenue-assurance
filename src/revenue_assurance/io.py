from __future__ import annotations
import json
from pathlib import Path
from .models import Transaction
def load_case(path:str|Path):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    return [Transaction(**item) for item in data["transactions"]],{str(k):float(v) for k,v in data.get("verified_recovery",{}).items()},float(data["platform_cost_usd"])

