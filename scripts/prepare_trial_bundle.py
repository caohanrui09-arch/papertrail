"""Prepare only redistributable trial assets, never copy a workspace or visitor DB."""
import ast
import hashlib
import json
from pathlib import Path
import shutil

from gsearch.quality_protocol import digest, save
from scripts.build_search_v2 import TOPICS, AT, load

DEST = Path('deploy/stage39')


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    sources = {
        'gsearch/visitor_profile.py': {'PreferenceConflict': None, 'Preferences': None,
                                      'PersonalModel': {'__init__', 'recommend', 'explain'}},
        'gsearch/unified_search.py': {'request_time': None, 'AsOfBM25': None},
        'gsearch/preference_backup.py': {k: None for k in ['StrictModel', 'BackupItem', 'Backup', 'ImportRequest', 'unique_object', 'parse_backup', 'merge_plan']},
        'gsearch/personal_search_v2.py': {'Feedback': None, 'Reset': None},
    }
    header = '''"""Generated unchanged local primitives; provenance in reuse-receipt.json. Do not hand edit."""
from __future__ import annotations
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
import hashlib, json, re, sqlite3, threading, time
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.preprocessing import normalize
from sklearn.metrics.pairwise import linear_kernel
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
MAX_FILE = 256 * 1024
MAX_REQUEST = 2 * MAX_FILE
def aware_timestamp(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None: raise ValueError('Timezone required')
    return d
'''
    code, receipt = [header], []
    for file, selection in sources.items():
        text = Path(file).read_text(encoding='utf-8')
        for node in ast.parse(text).body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef)) or node.name not in selection:
                continue
            if selection[node.name] is not None:
                node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in selection[node.name]]
            segment = ast.unparse(node)
            code.append(segment)
            receipt.append({'source': file, 'name': node.name, 'source_sha256': digest(Path(file)),
                            'methods': sorted(selection[node.name]) if selection[node.name] else 'all',
                            'ast_sha256': hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()})
    (DEST/'trialsite').mkdir(exist_ok=True)
    (DEST/'trialsite/__init__.py').write_text('', encoding='utf-8')
    (DEST/'trialsite/reuse.py').write_text('\n\n'.join(code)+'\n', encoding='utf-8')
    save(DEST/'reuse-receipt.json', {'primitives': receipt, 'generated_sha256': digest(DEST/'trialsite/reuse.py'),
                                   'adaptation': 'only selected named methods/classes, imports and aware timestamp validation; method ASTs unchanged'})
    rows = load(Path('data/stage39-trial/documents.json'))
    parser = __import__('gsearch.metadata_fetch', fromlist=['upstream']).upstream()
    catalog = DEST/'catalog'
    (catalog/'raw').mkdir(parents=True, exist_ok=True)
    parsed = {}
    for row in rows:
        provenance = row['provenance']
        raw = Path(provenance['raw_path'])
        if digest(raw) != provenance['raw_sha256']: raise ValueError('Source hash changed')
        if str(raw) not in parsed:
            parsed[str(raw)] = {r.entry_id.rsplit('/', 1)[-1]: r for r in parser._feed.parse(raw.read_bytes()).results}
        actual = parsed[str(raw)][row['doc_id']+'v1']
        if (actual.title, actual.summary, actual.published.isoformat()) != (row['title'], row['abstract'], row['published_at']):
            raise ValueError('Original v1 mismatch: '+row['doc_id'])
        target = catalog/'raw'/(provenance['raw_sha256']+'.xml')
        shutil.copyfile(raw, target)
        row['provenance'] = {k: v for k, v in provenance.items() if k != 'raw_path'}
        row['provenance']['raw_file'] = 'raw/'+target.name
    save(catalog/'documents.json', rows)
    scenes = load(Path('data/stage29-search-v2/synthetic-scenarios-reviewed.json'))
    save(catalog/'config.json', {'topics': TOPICS, 'at': AT, 'scenes': scenes,
                               'documents_sha256': digest(catalog/'documents.json'),
                               'params': {'ngram_range':[1,2], 'min_df':2, 'max_features':30000, 'stop_words':'english','sublinear_tf':True,'norm':'l2'}})
    frontend = DEST/'web'
    shutil.copytree('web/papertrail-v38/dist', frontend, dirs_exist_ok=True)
    main = (frontend/'main.mjs').read_text(encoding='utf-8')
    main = main.replace('当前是本机研究演示，目录共', '当前是小范围试用目录，共')
    main = main.replace('本机已连接 <small>LOCAL</small>', '试用空间已连接 <small>TRIAL</small>')
    main = main.replace('42 篇开发目录', '${meta.catalog} 篇试用目录').replace('aria-label="本地访客"', 'aria-label="独立访客空间"')
    main = main.replace('个人偏好单独存储在当前浏览器空间，', '每个浏览器使用独立随机凭据访问服务器上的偏好空间。清除 Cookie 后需用备份恢复；这不是登录账号。个人偏好')
    main = main.replace('预设主题等级是非独立模型摘要判断，不是真人相关性标注，不用于排名。自由查询没有对应标签。', '扩容目录已核验 v1 原摘要并做主题噪声审查，没有真人相关性评价。试用版不沿用旧 42 篇的模型等级，不宣称扩容提高了搜索质量。')
    start = main.index('<details><summary>当前主题的审查判据')
    end = main.index('</details>', start)+len('</details>')
    main = main[:start] + '<p>元数据（含摘要）依据 arXiv API CC0 条款展示；全文请前往论文来源阅读。本项目不由 arXiv 背书。</p><p><a href="/legal.html" target="_blank" rel="noopener">数据权限、开源许可与访客隐私说明 ↗</a></p>' + main[end:]
    (frontend/'main.mjs').write_text(main, encoding='utf-8')
    backup = (frontend/'backup.mjs').read_text(encoding='utf-8').replace('仅支持相同目录和论文版本；', '支持当前目录，以及经核验的旧 42 篇目录备份；')
    backup = backup.replace('导入会在本机校验，不读取外部链接。', '导入由当前服务校验，不读取外部链接。')
    backup = backup.replace('<h3>确认这些变化</h3><span>尚未保存</span></div>',
        '<h3>确认这些变化</h3><span>尚未保存</span></div>${preview.migrated_from&&html`<p class="backup-migration">这是旧 42 篇目录的备份；论文 ID、v1 版本、标题和来源已逐项核验。确认后迁入当前目录，其他偏好继续保留。</p>`}')
    (frontend/'backup.mjs').write_text(backup, encoding='utf-8')
    save(Path('reports/stage39/bundle-data.json'), {'documents': len(rows), 'raw_files': len(parsed),
         'raw_original_v1_checks': len(rows), 'documents_sha256': digest(catalog/'documents.json'),
         'old_backup_catalog': 'search-v2:'+digest(Path('data/stage29-search-v2/documents.json')),
         'old_ids': sorted(load(Path('data/stage29-search-v2/documents.json'))[i]['doc_id'] for i in range(42))})
    save(catalog/'migration.json', {'accepted_previous_catalog': 'search-v2:'+digest(Path('data/stage29-search-v2/documents.json')),
                                  'original_ids': sorted(r['doc_id'] for r in load(Path('data/stage29-search-v2/documents.json')))})
    print({'catalog': len(rows), 'reused_primitives': len(receipt), 'raw_files': len(parsed)})


if __name__ == '__main__':
    main()
