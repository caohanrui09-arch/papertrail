"""Temporal/cold-start audit rules; no recommendation fitting or candidate label selection."""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

CACHE=Path('.cache/stage12')
DATA=Path('data/stage12-audit')
REPORT=Path('reports/stage12')
SOURCE=Path('.cache/stage10/mirror/parquet-source.json')
LIGHT=('paper_id','first_version_date','latest_version_date','n_versions')
TEXT=(*LIGHT,'title','abstract','arxiv_abs_url')
SAMPLE_GROUPS=(40,43,44,45)
SAMPLE_N=6
SEED='stage12-time-audit-20261026'

def read(path: Path) -> object:
    return json.loads(path.read_text(encoding='utf-8'))

def stamp(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        t=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
    except (ValueError,TypeError):
        return None

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def arrow() -> object:
    target=Path('.cache/stage10/deps').resolve()
    if str(target) not in sys.path:
        sys.path.insert(0,str(target))
    import pyarrow as pa
    if pa.__version__!='26.0.0' or not Path(pa.__file__).resolve().is_relative_to(target):
        raise ValueError('Expected existing isolated Arrow26 runtime')
    return pa

class CountedFile(io.RawIOBase):
    """Count bytes delivered to Arrow; not HTTP/TLS traffic or API metadata requests."""
    def __init__(self, handle: object):
        self.handle=handle
        self.returned_bytes=0
        self.read_calls=0
    def readable(self) -> bool:
        return True
    def seekable(self) -> bool:
        return True
    def seek(self,offset: int,whence: int=0) -> int:
        return self.handle.seek(offset,whence)
    def tell(self) -> int:
        return self.handle.tell()
    def read(self,size: int=-1) -> bytes:
        if size<0:
            raise ValueError('Refuse unbounded whole-file read')
        body=self.handle.read(size)
        self.returned_bytes+=len(body)
        self.read_calls+=1
        return body
    def readinto(self,buffer: bytearray) -> int:
        body=self.read(len(buffer))
        buffer[:len(body)]=body
        return len(body)

def reason(doc: str, meta: dict | None, event: datetime, cutoff: datetime,
           train_likes: set[str], catalog: set[str], old_catalog: set[str]) -> str:
    first=stamp(meta.get('first_version_date')) if meta else None
    if first is None:
        return 'unknown_metadata_or_first_date'
    if first>event:
        return 'source_first_date_after_feedback'
    if first>=cutoff:
        return 'published_after_train_cutoff'
    if doc in catalog:
        return 'inside_current_catalog'
    if doc in train_likes:
        return 'old_trainliked_version_excluded' if doc in old_catalog else 'old_trainliked_topk_truncated'
    return 'old_without_training_likes'

def sample_stratum(row: dict, cutoff: datetime, end: datetime, likes: set[str]) -> str | None:
    first,latest=stamp(row.get('first_version_date')),stamp(row.get('latest_version_date'))
    if first is None or latest is None or latest<first:
        return None
    if first<cutoff:
        if latest>=cutoff:
            return 'old_updated_after_cutoff'
        return 'old_trainliked_text_pre_cutoff' if row['paper_id'] in likes else 'old_no_trainlike_text_pre_cutoff'
    return 'new_between_cutoff_and_log_end' if first<=end else None

def sample_key(doc: str) -> str:
    return hashlib.sha256((SEED+':'+doc).encode()).hexdigest()
