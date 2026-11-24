"""Private note search and bounded, previewable Markdown reports."""
from datetime import datetime,timezone
import hashlib
import html
import re
import sqlite3
from typing import Literal
from fastapi import FastAPI,HTTPException,Query,Request
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .notebook import note_snapshot
from .readinglog import reading_snapshot
from .querybridge import plan_query
from .reuse import MAX_FILE
from .catalogfilters import Scope,LABELS

class PaperRef(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    doc_id:str=Field(pattern=r'^\d{4}\.\d{4,5}$')
    version_key:str=Field(max_length=80)

class SearchContext(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    original_need:str=Field(default='',max_length=1000)
    executed_query:str=Field(min_length=1,max_length=1000)
    method:Literal['bm25','tfidf']='bm25'
    topic:Literal['generative','cold','bias']='generative'
    context:Literal['none','same','cross']='none'
    plan_reviewed:bool=False
    catalog_scope:Scope='all'
    year:int|None=Field(default=None,ge=1900,le=2100)

class ReportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    papers:list[PaperRef]=Field(min_length=1,max_length=20)
    catalog_key:str=Field(max_length=100)
    revision:int=Field(ge=0,strict=True)
    reading_revision:int=Field(ge=0,strict=True)
    notes_revision:int=Field(ge=0,strict=True)
    include_notes:bool=True
    search_context:SearchContext|None=None

    @model_validator(mode='after')
    def unique(self)->'ReportRequest':
        if len({p.doc_id for p in self.papers})!=len(self.papers):raise ValueError('Duplicate paper')
        return self

def md_text(value:str)->str:
    text=html.escape(' '.join(value.splitlines()),quote=False)
    return re.sub(r'([\\`*_{}\[\]()#+.!|])',r'\\\1',text)

def literal_block(value:str)->str:
    fence='`'*max(3,1+max((len(s) for s in re.findall(r'`+',value)),default=0))
    return fence+'text\n'+value+'\n'+fence+'\n'

def install_researchtools(app:FastAPI)->None:
    catalog,store=app.state.catalog,app.state.preferences

    @app.get('/api/profile/notes/search')
    def search_notes(request:Request,q:str=Query(min_length=1,max_length=200),revision:int=Query(ge=0)):
        terms=list(dict.fromkeys(q.casefold().split()))
        if not terms or len(terms)>12 or any(len(t)>100 for t in terms):raise HTTPException(422,'请输入1–12个关键词，每个不超过100字符')
        with store.connect() as db:db.execute('BEGIN');snapshot=note_snapshot(db,request.state.owner)
        if revision!=snapshot['revision']:raise HTTPException(409,'笔记已变化，请刷新笔记后重新搜索')
        rows=snapshot['items'];ranked=[];method='sqlite_fts5_trigram'
        # The disposable index contains this authenticated visitor's notes only.
        # No cross-visitor IDF, title-only hits, persisted query or stale FTS trigger.
        with sqlite3.connect(':memory:') as index:
            use_fts=all(len(t)>=3 for t in terms)
            if use_fts:
                try:index.execute("CREATE VIRTUAL TABLE notes USING fts5(doc_id UNINDEXED,problem,questions,tokenize='trigram')")
                except sqlite3.OperationalError as error:
                    if 'tokenizer' not in str(error):raise
                    use_fts=False
            if not use_fts:
                index.execute('CREATE TABLE notes(doc_id TEXT,problem TEXT,questions TEXT)');method='sqlite_instr_casefold'
            index.executemany('INSERT INTO notes VALUES(?,?,?)',[(d,v['problem'].casefold(),v['questions'].casefold()) for d,v in rows.items()])
            if use_fts:
                expression=' AND '.join('"'+t.replace('"','""')+'"' for t in terms)
                ranked=[r[0] for r in index.execute('SELECT doc_id FROM notes WHERE notes MATCH ? ORDER BY bm25(notes),doc_id',(expression,))]
            else:
                condition=' AND '.join('(instr(problem,?)>0 OR instr(questions,?)>0)' for _ in terms)
                ranked=[r[0] for r in index.execute('SELECT doc_id FROM notes WHERE '+condition+' ORDER BY doc_id',[t for term in terms for t in (term,term)])]
        papers=[]
        for rank,doc in enumerate(ranked,1):
            values=rows[doc]
            matches=[{'term':t,'fields':[k for k in ('problem','questions') if t in values[k].casefold()]} for t in terms]
            papers.append(catalog.paper(doc)|{'rank':rank,'review':None,'user_note':catalog.paper(doc)|values|
                {'updated_at':snapshot['updated'][doc]},'note_match':matches})
        return {'papers':papers,'query':q,'history':[],'review_applies':False,'notes_revision':snapshot['revision'],
            'catalog_key':catalog.catalog_key,'message':'仅搜索你已保存的问题与疑问；多个关键词同时匹配，可直接回到原论文。',
            'trace':[{'tool':'私有笔记检索','method':method,'notes_revision':snapshot['revision'],'keywords':terms,'returned':len(papers),'scope':'authenticated_visitor_notes_only'}]}

    @app.post('/api/profile/report/preview')
    def report(body:ReportRequest,request:Request):
        if body.catalog_key!=catalog.catalog_key:raise HTTPException(409,'目录已变化，请刷新后重新生成报告')
        for p in body.papers:
            if not catalog.valid(p.doc_id):raise HTTPException(422,'报告论文不在当前目录')
            if p.version_key!=catalog.by_id[p.doc_id]['version_key']:raise HTTPException(409,'报告论文版本不一致')
        with store.connect() as db:
            db.execute('BEGIN');prefs=store.snapshot(db,request.state.owner);reading=reading_snapshot(db,request.state.owner);notes=note_snapshot(db,request.state.owner)
        if (body.revision,body.reading_revision,body.notes_revision)!=(prefs['revision'],reading['revision'],notes['revision']):
            raise HTTPException(409,'收藏、阅读状态或笔记已变化，请刷新后重新生成报告')
        now=datetime.now(timezone.utc).isoformat();lines=['# Papertrail 阅读报告','','生成时间（UTC）：'+now,'',
            '本报告由选中的版本标识、来源和个人笔记整理，不自动生成论文结论。',
            '目录：'+catalog.catalog_key,'']
        if body.search_context:
            context=body.search_context
            lines+=['## 附带检索条件','','这是生成报告时页面提供的选文上下文，不是完整历史检索日志。','']
            if context.original_need.strip():
                plan=plan_query(context.original_need,context.executed_query,context.plan_reviewed)
                lines+=['原问题：','',literal_block(plan['original_need']),'术语建议：','',literal_block(plan['proposed_query']),
                    '转换方法：'+md_text(plan['glossary_version'])+'；非全文翻译。','']
                lines+=['- '+md_text(m['phrase'])+' → '+md_text(m['english']) for m in plan['mappings']]
                lines+=['- 提醒：'+md_text(w) for w in plan['warnings']]
                lines+=['','英文词已编辑：'+('是' if plan['edited'] else '否'),'']
            lines+=['实际检索词：','',literal_block(context.executed_query),'检索方式：'+context.method+'；候选上下文：'+context.context,
                '检索范围：'+LABELS[context.catalog_scope]+'；年份：'+str(context.year or '全部年份'),'']
        labels={'to_read':'待读','reading':'在读','read':'已读'};count=0
        for number,ref in enumerate(body.papers,1):
            row=catalog.read(ref.doc_id)  # Re-check the original cached response before export.
            year=catalog.by_id[ref.doc_id]['published_at'][:4]
            lines+=['## '+str(number)+'. '+md_text(row['title']),'',
                '- 论文 ID：'+ref.doc_id,'- 版本：'+md_text(ref.version_key),
                '- arXiv 首次提交年份：'+year,'- 来源：['+md_text(ref.version_key)+']('+row['source_url']+')',
                '- 阅读状态：'+labels.get(reading['items'].get(ref.doc_id),'未标记'),'']
            note=notes['items'].get(ref.doc_id) if body.include_notes else None
            if note:
                count+=1;lines+=['### 我的笔记','','以下是个人记录，不是论文原文或作者结论。','','这篇解决什么问题：','',literal_block(note['problem']),
                    '还有什么疑问：','',literal_block(note['questions'])]
            else:lines+=['未附个人笔记。','']
        markdown='\n'.join(lines).rstrip()+'\n'
        if len(markdown.encode())>MAX_FILE:raise HTTPException(413,'报告超过256 KiB，请减少选文或不附笔记')
        return {'markdown':markdown,'filename':'papertrail-reading-report.md','sha256':hashlib.sha256(markdown.encode()).hexdigest(),
            'papers':len(body.papers),'notes_included':count,'catalog_key':catalog.catalog_key,'generated_at':now,
            'revision':prefs['revision'],'reading_revision':reading['revision'],'notes_revision':notes['revision']}
