"""Bounded, inspectable terminology assistance using Python's native regex engine."""
import hashlib
import json
from pathlib import Path
import re
from fastapi import FastAPI,HTTPException,Query

RAW=(Path(__file__).resolve().parents[1]/'query-glossary.json').read_bytes()
GLOSSARY=json.loads(RAW)
VERSION=GLOSSARY['version']
SHA=hashlib.sha256(RAW).hexdigest()
ENTRIES={ch:en for ch,en in GLOSSARY['entries']}
if len(ENTRIES)!=len(GLOSSARY['entries']):raise ValueError('Duplicate glossary entry')
PATTERN=re.compile('|'.join(re.escape(s) for s in sorted(ENTRIES,key=lambda s:(-len(s),s))),re.IGNORECASE)
LOOKUP={s.casefold():v for s,v in ENTRIES.items()}
FILLERS=['帮我','我想','希望','需要','了解','学习','有哪些','一篇','一些','几篇','关于','相关','论文','研究','一下','如何','怎样','怎么','方面','方向','方法','问题','请','的','我','想','找','和','与','中','是','有','在','用','做','能','吗','呢']
FILLER=re.compile('|'.join(re.escape(s) for s in sorted(FILLERS,key=lambda s:-len(s))))
NEGATION=re.compile(r'不想|不要|排除|不是|而非|不包括|除外|\b(?:not|without|excluding|except)\b',re.IGNORECASE)

def plan_query(need:str,executed:str|None=None,reviewed:bool=False)->dict:
    if not isinstance(need,str) or not need.strip() or len(need)>1000:raise HTTPException(422,'请输入不超过1000字符的原始需求')
    mappings=[];parts=[];remaining=list(need)
    for hit in PATTERN.finditer(need):
        value=LOOKUP[hit.group().casefold()]
        mappings.append({'phrase':hit.group(),'english':value,'start':hit.start(),'end':hit.end()})
        parts.append(value)
        remaining[hit.start():hit.end()]=[' ']*(hit.end()-hit.start())
    english=re.findall(r'[A-Za-z][A-Za-z0-9_-]*',need)
    parts+=english
    words=list(dict.fromkeys(word.casefold() for part in parts for word in part.split()))[:128]
    rest=FILLER.sub('', ''.join(remaining))
    unknown=list(dict.fromkeys(re.findall(r'[\u3400-\u9fff]+',rest)))[:16]
    negation=bool(NEGATION.search(need));warnings=[]
    if unknown:warnings.append('部分中文未识别，请自行补充英文词：'+ '、'.join(unknown))
    if negation:warnings.append('检测到否定或排除表达；当前关键词检索不表达这些筛选关系，请检查并修改检索词。')
    proposed=' '.join(words)
    if not proposed:warnings.append('没有可用英文建议，请手动填写检索词。')
    return {'original_need':need,'proposed_query':proposed,'executed_query':executed,
        'edited':executed is not None and executed.strip()!=proposed,
        'mappings':mappings[:64],'mappings_truncated':len(mappings)>64,
        'retained_english':list(dict.fromkeys(english))[:64],'unrecognized':unknown,'warnings':warnings,
        'review_required':bool(warnings),'reviewed':reviewed,'glossary_version':VERSION,'glossary_sha256':SHA,
        'method':'domain_glossary_native_regex','scope':GLOSSARY['scope']}

def install_querybridge(app:FastAPI)->None:
    @app.get('/api/query-plan')
    def query_plan(need:str=Query(min_length=1,max_length=1000)):
        return plan_query(need)
