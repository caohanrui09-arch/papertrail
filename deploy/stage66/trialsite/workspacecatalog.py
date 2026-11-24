"""Live additive catalog over the immutable historical core and its frozen TF-IDF vocabulary."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from scipy.sparse import vstack
from .catalog import Catalog,sha
from .reuse import AsOfBM25

class WorkspaceCatalog(Catalog):
    def __init__(self,root:Path,supplement:Path):
        core=Catalog(root);self.core=core;self.root=root
        self.supplement=json.loads((supplement/'receipt.json').read_text(encoding='utf-8'))
        raw=(supplement/'documents.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.supplement['documents_sha256']:raise ValueError('Supplement hash changed')
        rows=json.loads(raw)
        if len(rows)!=self.supplement['count'] or not 1<=len(rows)<=50:raise ValueError('Supplement size mismatch')
        self.by_id=dict(core.by_id);self.catalog=list(core.catalog)
        for row in rows:
            doc=row['doc_id'];p=(root/row['provenance']['raw_file']).resolve()
            if doc in self.by_id or row['version']!=1 or row['version_key']!='arxiv:'+doc+'v1':raise ValueError('Supplement identity/version changed')
            if not p.is_relative_to((root/'raw').resolve()) or sha(p)!=row['provenance']['raw_sha256']:raise ValueError('Supplement original response changed')
            if row['source_url']!='https://arxiv.org/abs/'+doc+'v1' or not row['title'].strip() or not row['abstract'].strip():raise ValueError('Invalid supplemental source/text')
            self.by_id[doc]=row;self.catalog.append(doc)
        self.supplement_ids={r['doc_id'] for r in rows}
        self.at=self.supplement['at'];self.topics=core.topics;self.scenes=core.scenes;self.cutoff=core.cutoff
        self.position={d:i for i,d in enumerate(self.catalog)}
        self.available=np.array([datetime.fromisoformat(self.by_id[d]['available_at']).timestamp() for d in self.catalog])
        if not all(self.valid(d) for d in self.catalog):raise ValueError('Future supplement')
        self.vectorizer=core.vectorizer;self.features=core.features
        added=self.vectorizer.transform([r['title']+'\n'+r['abstract'] for r in rows])
        self.documents=vstack([core.documents,added],format='csr')
        self.popularity=np.zeros(len(self.catalog))
        combined=hashlib.sha256((core.catalog_key+'\n'+self.supplement['documents_sha256']).encode()).hexdigest()
        self.catalog_key='search-workspace-v4:'+combined
        self.signature=core.signature|{'catalog_sha256':combined,'core_catalog_sha256':core.signature['catalog_sha256'],
            'supplement_sha256':self.supplement['documents_sha256'],'content_policy':'frozen_core_vocabulary_transform_only'}
        self.model=SimpleNamespace(catalog=self.catalog,by_id=self.by_id,cutoff=self.cutoff,available=self.available,
            sar=SimpleNamespace(seen={'paired':set(self.scenes['shared_seen_filter'])}))
        self.bm25=AsOfBM25(self.model,max_snapshots=1);self.bm25.search('paired',self.at,'multimodal fast slow thinking',1)

    def compatible_key(self,key:str)->bool:return key in (self.catalog_key,self.core.catalog_key)

    def previews(self)->dict:
        value=super().previews()
        for doc in self.supplement_ids:value['papers'][doc]['catalog_group']='多模态快慢思考 · 新增专题'
        return value

    def close(self)->None:
        self.bm25.close();self.core.bm25.close()
