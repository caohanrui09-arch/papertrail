"""Strict, untrusted presentation handoff. Does not create a plan, job or tool call."""
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field


class Handoff(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    version:Literal[76]
    source:Literal['papertrail-reading-workbench']
    original_need:str=Field(min_length=1,max_length=1000)
    executed_query:str=Field(max_length=2000)
    query_reviewed:bool
    intent:Literal['search','recommend','mixed']
    source_scope:Literal['all','core','generative','cold','bias','multimodal','unclassified']
    source_year:str=Field(pattern=r'^(|(?:19|20)\d{2})$')


def register(app,custom):
    @app.post('/lab/v76/handoff')
    def validate_handoff(body:Handoff):
        if not body.original_need.strip() or any(ord(c)<32 and c not in '\n\r\t' for c in body.original_need):raise HTTPException(422,'原始需求无效')
        if any(ord(c)<32 for c in body.executed_query):raise HTTPException(422,'检索词必须为单行有效文本')
        if body.intent!='recommend' and not body.executed_query.strip():raise HTTPException(422,'请从工作台带入非空检索词')
        filters=[]
        if body.source_scope!='all':filters.append('来源主题范围：'+body.source_scope)
        if body.source_year:filters.append('来源年份：'+body.source_year)
        draft=body.original_need+('\n工作台附加筛选意图（目标目录不同，需重新核对，未程序化执行）：'+'；'.join(filters) if filters else '')
        if len(draft)>1000:raise HTTPException(422,'附加筛选后超过1000字；请精简原需求，不会静默截断')
        return {'version':76,'handoff':body.model_dump(),'draft_need':draft,'target_scope':custom.scope,
                'profiles':custom.choices()['profiles'],'source_trust':'client_asserted_not_authenticated',
                'requires_target_review':True,'created_plan':False,'started_job':False,
                'warning':'来源工作台筛选及访客画像不自动作用于Agent。目标是冻结万篇目录；年份/主题限定保留供确认，未程序化执行。'}
