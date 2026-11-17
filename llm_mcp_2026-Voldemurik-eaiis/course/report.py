"""Minimal helpers for students who want standardized safe audit entries."""
from __future__ import annotations
import json,datetime
from pathlib import Path
SENSITIVE=('token','secret','credential','password','authorization','api_key')

def audit(path:Path,event:str,**data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    safe={k:('[REDACTED]' if any(s in k.lower() for s in SENSITIVE) else v) for k,v in data.items()}
    rec={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'event':event,**safe}
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(rec,ensure_ascii=False,default=str)+'\n')
