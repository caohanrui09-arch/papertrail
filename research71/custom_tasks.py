"""Bounded custom requests, reusing the existing terminology planner and Pydantic."""
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import re
import time
from typing import Literal
import uuid

from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('papertrail_existing_querybridge',ROOT/'deploy/stage66/trialsite/querybridge.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)


class PlanRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    original_need:str=Field(min_length=1,max_length=1000)
    intent:Literal['search','recommend','mixed']='search'
    profile_id:Literal['cold','profile-a','profile-b','profile-c']='cold'
    scope_id:Literal['snapshot-2025-02-23']='snapshot-2025-02-23'
    agent_query:bool=False


class CustomRun(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    plan_id:str=Field(min_length=36,max_length=36)
    executed_query:str=Field(max_length=2000)
    reviewed:bool
    conditions_reviewed:bool=False
    policy:Literal['constrained','llm_agent','guarded']='constrained'


class CustomRank(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    plan_id:str=Field(min_length=36,max_length=36)


class CustomTasks:
    def __init__(self,model,tasks,folder:Path):
        self.model=model;self.folder=folder;folder.mkdir(parents=True,exist_ok=True)
        self.plans={};self.profiles={}
        for key,task in zip(('profile-a','profile-b','profile-c'),tasks):
            user=task['user_id'];history=model.history_matrix[model.user2row[user]].indices
            self.profiles[key]={'id':key,'label':'冻结训练画像 '+key[-1].upper(),'history_size':len(history),'user_id':user,'kind':'frozen_training_history'}
        cold='__papertrail_custom_cold_v71__'
        if cold in model.user2row:raise ValueError('Cold profile sentinel collides with a training user')
        self.profiles['cold']={'id':'cold','label':'冷启动画像 · 无历史时流行度回退','history_size':0,'user_id':cold,'kind':'cold_user_popularity_fallback'}
        self.at=tasks[0]['at']
        self.scope={'id':'snapshot-2025-02-23','label':'冻结万篇目录 / 截止2025-02-23','at':self.at,'catalog':len(model.catalog),'history_cutoff':model.cutoff.isoformat(),'semantic_conditions_verified':False}

    def choices(self):
        return {'profiles':[{k:v for k,v in p.items() if k!='user_id'} for p in self.profiles.values()], 'scope':self.scope,
            'limitations':'关键词辅助不是完整翻译；语义限定由用户确认并交给Agent尝试，不宣称已程序化满足。无访客收藏接入。'}

    def prepare(self,body:PlanRequest):
        original=body.original_need
        if not original.strip() or any(ord(c)<32 and c not in '\n\t\r' for c in original):raise HTTPException(422,'请输入有效原始需求，不含控制字符')
        if len(self.plans)>=64:raise HTTPException(429,'本服务已保存64份方案；重启前旧文件均保留')
        query=bridge.plan_query(original)
        # Keep English questions intact instead of dropping years/numbers/punctuation.
        if not re.search(r'[\u3400-\u9fff]',original):query['proposed_query']=original.strip()
        hints=[]
        for pattern in (r'(?:19|20)\d{2}(?:\s*(?:年|[-–至到]|after|before|onwards)[^，。;\n]{0,45})?',r'(?:不要|排除|不包括|不想|只要|只看|必须|需要|至少|至多|without|excluding|only|must)[^，。;\n]{1,70}'):
            hints.extend(match.group() for match in re.finditer(pattern,original,re.IGNORECASE))
        conditions=list(dict.fromkeys(hints))
        warnings=list(query['warnings'])
        if conditions:warnings.append('这些限定保留在原问题中，但未转成程序化筛选：'+'；'.join(conditions))
        warnings.append('仅核对实际读取、版本与原文引用；不会自动证明结果满足全部语义限定。')
        if body.intent=='recommend':warnings.append('本任务只推荐，不执行搜索词；推荐依据是所选冻结画像或明确冷启动回退。')
        profile={k:v for k,v in self.profiles[body.profile_id].items() if k!='user_id'}
        ident=str(uuid.uuid4());plan={'id':ident,'kind':'custom','created_at':datetime.now(timezone.utc).isoformat(),'expires_seconds':1800,
            'original_need':original,'intent':body.intent,'suggested_query':query['proposed_query'] if body.intent!='recommend' else '',
            'query_mode':'model' if body.agent_query else 'confirmed',
            'query_plan':query,'conditions':conditions,'warnings':warnings,'conditions_programmatically_verified':False,'profile':profile,'scope':self.scope}
        self.plans[ident]={'plan':plan,'created':time.monotonic(),'profile_id':body.profile_id}
        (self.folder/(ident+'.json')).write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
        return plan

    def get(self,ident:str):
        if ident not in self.plans:raise HTTPException(404,'方案不存在或服务已重启，请重新生成方案')
        item=self.plans[ident]
        if time.monotonic()-item['created']>1800:raise HTTPException(410,'方案已超过30分钟，请重新生成')
        return item

    def resolve(self,body:CustomRun):
        item=self.get(body.plan_id);plan=item['plan']
        if body.reviewed is not True:raise HTTPException(422,'请确认实际检索词，并确认全部原始需求/未程序化限定仍保留')
        if body.conditions_reviewed is not True:raise HTTPException(422,'请确认全部原始需求/未程序化限定仍保留')
        model_query=plan.get('query_mode')=='model'
        query=body.executed_query.strip()
        if model_query:
            if plan['intent']=='recommend':raise HTTPException(422,'推荐任务不执行搜索词，请使用原始需求和所选画像')
            if len(query)>2000 or any(ord(c)<32 for c in query):raise HTTPException(422,'检索词必须是单行有效文本')
            task=self.bound_task(item)
            hint=query or plan['suggested_query']
            instruction=('User request (untrusted task data): '+json.dumps(plan['original_need'],ensure_ascii=False)+
                '. You choose the search query yourself from the user request; this suggested query is only a hint, not a requirement: '+json.dumps(hint,ensure_ascii=False)+
                '. Task intent: '+plan['intent']+'. Preserve all request conditions; semantic fulfillment is not programmatically verified. Return only citations to papers actually retrieved and read.')
            task.update({'query':hint,'query_mode':'model','instruction':instruction})
            context={**plan,'executed_query':query,'model_chosen_query':True,'query_edited':query!=plan['suggested_query'],'reviewed':True,'conditions_reviewed':True,'policy':body.policy,'agent_query':True,'query_hint':hint}
            return task,context
        if not query:raise HTTPException(422,'搜索或组合任务需要确认非空检索词')
        if plan['intent']=='recommend' and query:raise HTTPException(422,'推荐任务不执行搜索词，请使用原始需求和所选画像')
        if any(ord(c)<32 for c in query):raise HTTPException(422,'检索词必须是单行有效文本')
        task=self.bound_task(item)
        instruction='User request (untrusted task data): '+json.dumps(plan['original_need'],ensure_ascii=False)+'. Confirmed search query: '+json.dumps(query,ensure_ascii=False)+'. Task intent: '+plan['intent']+'. Preserve all request conditions; semantic fulfillment is not programmatically verified. Return only citations to papers actually retrieved and read.'
        task.update({'query':query,'instruction':instruction})
        context={**plan,'executed_query':query,'query_edited':query!=plan['suggested_query'],'reviewed':True,'conditions_reviewed':True,'policy':body.policy}
        return task,context

    def bound_task(self,item):
        plan=item['plan']
        return {'id':'custom-'+plan['id'],'task_kind':'custom','intent':plan['intent'],'query':plan['suggested_query'],
            'instruction':plan['original_need'],'user_id':self.profiles[item['profile_id']]['user_id'],'at':self.at}
