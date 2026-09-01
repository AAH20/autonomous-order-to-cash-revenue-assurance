from __future__ import annotations
import argparse,json
from pathlib import Path
from .engine import RevenueAssuranceEngine
from .io import load_case
def main()->None:
    p=argparse.ArgumentParser(description="Analyze order-to-cash leakage and verified recovery");p.add_argument("case");p.add_argument("--output");a=p.parse_args()
    result=RevenueAssuranceEngine().analyze(*load_case(a.case));rendered=json.dumps(result,indent=2,sort_keys=True)
    if a.output:Path(a.output).write_text(rendered+"\n",encoding="utf-8")
    print(rendered)
if __name__=="__main__":main()

