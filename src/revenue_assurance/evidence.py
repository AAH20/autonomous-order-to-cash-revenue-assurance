from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from typing import Any
def receipt(payload:dict[str,Any])->dict[str,Any]:
    envelope={"schema":"o2c.revenue-assurance.v1","evidence_class":"simulated","generated_at":datetime.now(timezone.utc).isoformat(),"payload":payload}
    envelope["sha256"]=hashlib.sha256(json.dumps(envelope,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    envelope["integrity_note"]="Digest detects envelope changes; it does not prove ERP access, attribution, custody or cash recovery."
    return envelope

