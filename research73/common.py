"""Versioned evaluation IO; no execution or score repair."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/stage73-evaluation'


def read(path: Path):return json.loads(path.read_text(encoding='utf8'))
def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def value_hash(value) -> str:return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def write(path: Path,value):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)
def verify_protocol():
    protocol=read(DATA/'protocol.json');assert digest(DATA/'protocol.json')==(DATA/'protocol.sha256').read_text().strip()
    for name,h in protocol['frozen_files'].items():
        if digest(ROOT/name)!=h:raise ValueError('Frozen evaluation input changed: '+name)
    return protocol
