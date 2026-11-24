/* Task report format adapter. Uses only public tool records, never private model messages. */
(() => {
 'use strict';
 const clone=x=>JSON.parse(JSON.stringify(x)),pick=(x,keys)=>Object.fromEntries(keys.filter(k=>x&&Object.hasOwn(x,k)).map(k=>[k,x[k]]));
 const finite=n=>typeof n==='number'&&Number.isFinite(n)?n:null;
 const metadataKeys=['llm_usage','error','framework_steps_exhausted','constraint_snapshots','proposal_events','wire_attempts','charged_application_attempts','no_automatic_calls_or_fallback','schema_instances_isolated','native_default_schema_unchanged','constraint_kind','prompt_sha256'];
 function publicRecord(row){
  const value=pick(row,['task_id','policy','seconds','completed_protocol','error']);
  value.trace={trace:(row.trace?.trace||[]).map(e=>pick(e,['attempt','tool','arguments','result','seconds']))};
  value.metadata=pick(row.metadata,metadataKeys);value.metadata.steps=(row.metadata?.steps||[]).map(s=>pick(s,['step_number','timing','tool_calls','error','token_usage','is_final_answer']));
  return clone(value);
 }
 function quoteChecks(row){
  const entries=row.trace?.trace||[];
  return (row.answer?.citations||[]).map(c=>{
   const read=entries.find(e=>e.tool==='read_paper'&&!e.result?.error&&e.result?.doc_id===c.doc_id&&e.result?.version===c.version&&e.result?.version_key===c.version_key&&e.result?.source_url===c.source_url&&typeof c.quote==='string'&&c.quote.length&&e.result?.abstract?.includes(c.quote)&&e.result?.quotes?.some(q=>q.quote_index===c.quote_index&&q.text===c.quote));
   const before=read&&entries.slice(0,entries.indexOf(read)).some(e=>['search_papers','recommend_papers'].includes(e.tool)&&!e.result?.error&&e.result?.papers?.some(p=>p.doc_id===c.doc_id&&p.version===c.version&&p.source_url===c.source_url));
   const final=read&&entries.slice(entries.indexOf(read)+1).find(e=>e.tool==='finalize'&&!e.result?.error&&e.result?.citations?.some(p=>p.doc_id===c.doc_id&&p.version_key===c.version_key&&p.quote===c.quote));
   return {doc_id:c.doc_id,version_key:c.version_key,passed:Boolean(read&&before&&final),read_attempt:read?.attempt??null,finalize_attempt:final?.attempt??null};
  });
 }
 function payload({row,actual,context=null,handoff=null,events=[],runIndex=null},createdAt=new Date().toISOString()){
  if(!row||!actual||row.task_id!==actual.task_id||row._in_progress||actual.provisional)throw Error('本次终局结果与实际候选证据尚未对齐，不能作为完整任务报告导出。');
  if(actual.source?.kind==='job'&&actual.source.run_index!==runIndex)throw Error('当前运行序号与候选证据不一致，等待同一条结果。');
  const checks=quoteChecks(row),trusted=checks.every(c=>c.passed),record=publicRecord(row),usage=row.metadata?.llm_usage||{};
  record.answer=row.answer&&trusted?clone(row.answer):null;
  const warnings=['协议完成与来源一致不代表语义正确或需求满足；无人相关性标注，不计算NDCG/MRR。','报告包含原问题与实际工具参数；分享前请预览。','独立算法诊断没有写入Agent实际候选或引用。'];
  if(!trusted)warnings.push('至少一条引用未通过本次来源核对，未作为已核验答案导出；实际调用及失败仍保留。');
  const source=clone(actual.source||{});
  const kinds=new Set(['run_started','tool_requested','tool_returned','tool_rejected','constraint_state','model_step','run_completed']);
  const ownEvents=source.kind==='job'?events.filter(e=>e.run_index===source.run_index&&kinds.has(e.kind)).map(e=>pick(e,['id','timestamp','kind','run_index','task_id','policy','payload'])):[];
  // Native observed event payloads contain tool/usage/state data. Model-step public fields only.
  for(const e of ownEvents){if(e.kind==='model_step')e.payload=pick(e.payload,['step_number','duration','tool_calls','error','usage']);if(e.kind==='run_started')e.payload=pick(e.payload,['task_id','policy']);if(e.kind==='run_completed')e.payload=pick(e.payload,['completed_protocol','seconds','error','usage'])}
  const body={format:'papertrail_task_report',version:76,created_at:createdAt,source,task_id:row.task_id,
   scope:{as_of:actual.as_of,context:context?clone(context):null,handoff:handoff?clone(handoff):null},
   protocol_completed:row.completed_protocol===true,accepted_answer_source_checks:checks,source_check_status:checks.length?(trusted?'all_passed':'rejected_for_export'):'no_citations',source_checks_are_not_semantic_quality:true,
   cost:{model_calls:row.policy==='fixed'?0:finite(usage.calls),input_tokens:row.policy==='fixed'?0:finite(usage.input_tokens),output_tokens:row.policy==='fixed'?0:finite(usage.output_tokens),execution_seconds:finite(row.seconds),worker_wall_seconds:null,charged_application_attempts:finite(row.metadata?.charged_application_attempts)},
   actual_candidates:clone(actual),execution:record,events:clone(ownEvents),event_scope:source.kind==='job'?'Only this job/run public events currently received; executed trace is authoritative.':'Historical public executed trace; no live events invented.',
   warnings,private_model_messages_exported:false,independent_diagnostic_injected:false,quality_scores:null};
  if(JSON.stringify(body).length>1500000)throw Error('报告超过本地导出上限，请保留原始日志后缩小单条任务范围。');return body;
 }
 const text=s=>String(s??'未提供').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replace(/([\\`*_{}\[\]])/g,'\\$1');
 function fence(value){const s=typeof value==='string'?value:JSON.stringify(value,null,2),longest=Math.max(2,...[...s.matchAll(/`+/g)].map(m=>m[0].length)),ticks='`'.repeat(longest+1);return ticks+'json\n'+s+'\n'+ticks}
 function markdown(p,hash){
  const n=x=>x==null?'未记录':String(x),lines=['# Papertrail 单次任务报告','',`任务：${text(p.task_id)}`,`来源：${text(p.source.kind)} · ${text(p.created_at)}`,`截止：${text(p.scope.as_of)}`,'',`协议完成：${p.protocol_completed?'是':'否（保留失败）'}`,'','## 原始需求与确认范围','',text(p.scope.context?.original_need||p.scope.context?.description||'本记录未提供可展示的原始需求；以任务ID和实际参数核对。'),''];
  if(p.scope.context?.executed_query!=null)lines.push('实际检索词：'+text(p.scope.context.executed_query),'');
  if(p.scope.handoff)lines.push('### 工作台交接原字段','',fence(p.scope.handoff),'');
  lines.push('## 实际成本','',`模型调用 ${n(p.cost.model_calls)}；输入Token ${n(p.cost.input_tokens)}；输出Token ${n(p.cost.output_tokens)}；执行秒数 ${n(p.cost.execution_seconds)}。`,'','## 实际候选','');
  for(const r of p.actual_candidates.papers||[])lines.push(`- ${text(r.doc_id)} · ${text(r.version_key)} · ${text(r.title)}；来源 ${r.occurrences.map(o=>text(o.tool)+' #'+o.attempt+' / 原排名'+o.rank).join('；')}；读取 ${r.read_success?'成功':'未成功'}；引用 ${r.cited?'是':'否'}。`);
  if(!p.actual_candidates.papers?.length)lines.push('本次实际候选为空，未补入其他论文。');
  lines.push('','## 已接收答案与原文引用','');
  if(p.execution.answer){lines.push(text(p.execution.answer.answer||'本响应无正文。'),'');for(const c of p.execution.answer.citations||[]){lines.push(`### ${text(c.doc_id)} · ${text(c.version_key)}`,'',...c.quote.split('\n').map(s=>'> '+text(s)),'');try{const u=new URL(c.source_url);if(u.protocol==='https:'&&u.hostname==='arxiv.org')lines.push(`[版本来源](${u.href})`,'')}catch{}}}else lines.push('没有可导出的已核验最终答案。已有调用、失败和拒绝保留在下方。','');
  lines.push('## 失败与引用核对','',`执行错误：${text(p.execution.error||p.execution.metadata?.error||'原记录未提供顶层错误；请同时核对工具失败/拒绝。')}`,'',fence(p.accepted_answer_source_checks),'','## 实际执行、提案及拒绝记录','',fence(p.execution),'','## 本次公开逐步事件','',fence(p.events),'','## 范围与限制','',...p.warnings.map(w=>'- '+text(w)),'',`内容 SHA-256：${hash}`,'校验方式：UTF-8(JSON.stringify(JSON文件的payload))；Markdown转义仅用于展示，JSON保留逐字工具返回。','');return lines.join('\n');
 }
 async function pack(snapshot,createdAt){const body=payload(snapshot,createdAt),bytes=new TextEncoder().encode(JSON.stringify(body)),hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');return {envelope:{format:'papertrail_task_report_envelope',version:76,hash_algorithm:'SHA256_UTF8_JSON.stringify_payload',content_sha256:hash,payload:body},markdown:markdown(body,hash),filename:'papertrail-task-'+body.task_id.replace(/[^A-Za-z0-9_-]/g,'_').slice(0,80)}}
 window.PapertrailTaskReport={payload,pack,quoteChecks,publicRecord};
})();

/* Display coordination only. Never invokes an Agent tool, edits parameters or submits. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n};
 let readRows=[],selectedDoc=null,taskKey=null,latestRow=null,latestActual=null;
 function setView(view){$('result-area').dataset.view=view;for(const id of ['abstract','answer'])$('show-'+id).setAttribute('aria-pressed',String(id===view))}
 function source(text,url){try{const u=new URL(url);if(u.protocol==='https:'&&u.hostname==='arxiv.org'){const a=el('a',text);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a}}catch{}return el('span','来源链接未通过校验')}
 function paintReader(){
  const root=$('task-reader');root.replaceChildren();$('read-count').textContent=String(readRows.length);
  if(!readRows.length){root.append(el('p','本次尚无成功返回的原摘要。可先查看实际候选和调用过程；页面不会替模型补读。','empty'));return}
  if(!readRows.some(e=>e.result.doc_id===selectedDoc))selectedDoc=readRows[0].result.doc_id;
  const label=el('label','选择本次已读取论文'),select=el('select');select.id='reader-paper';select.setAttribute('aria-label','本次成功读取的论文');for(const e of readRows){const option=el('option',e.result.title||e.result.doc_id);option.value=e.result.doc_id;select.append(option)}select.value=selectedDoc;select.onchange=()=>{selectedDoc=select.value;paintReader()};label.append(select);root.append(label);
  const e=readRows.find(e=>e.result.doc_id===selectedDoc),p=e.result;root.dataset.docId=p.doc_id;root.append(el('h3',p.title),el('code',`${p.doc_id} · ${p.version_key}`,'reader-version'));
  const actions=el('div',null,'reader-source-actions'),call=el('button',`实际读取 #${e.attempt} ↗`);call.type='button';call.onclick=()=>jumpTimeline(e.attempt);actions.append(source('打开版本对应原文 ↗',p.source_url),call);root.append(actions,el('p',p.abstract,'task-abstract'),el('p','原摘要来自本次 read_paper 返回；未核实全文结论或是否满足全部需求。','muted'));
 }
 function reader(row){latestRow=row;const key=row.task_id;if(taskKey!==key){taskKey=key;selectedDoc=null}const seen=new Set();readRows=(row.trace?.trace||[]).filter(e=>e.tool==='read_paper'&&!e.result?.error&&typeof e.result?.abstract==='string'&&!seen.has(e.result.doc_id)&&seen.add(e.result.doc_id));paintReader();const count=row.trace?.trace?.length||0;$('compact-process').textContent=`${count} 次实际执行${row._in_progress?' · 更新中':''}`;window.PapertrailExports?.refresh()}
 function read(doc){if(!readRows.some(e=>e.result.doc_id===doc))return;selectedDoc=doc;paintReader();setView('abstract');$('task-reader').scrollIntoView({block:'center',behavior:'instant'});$('reader-paper')?.focus({preventScroll:true})}
 function actual(value){latestActual=value;const parts=[['search','搜索/推荐 '+value.retrievals.length],['paper','候选 '+value.papers.length],['read','已读 '+value.papers.filter(p=>p.read_success).length],['cited',(value.provisional?'暂验引用 ':'引用 ')+value.papers.filter(p=>p.cited).length]];$('flow-mini').replaceChildren(...parts.map(([c,t])=>el('span',t,c)));window.PapertrailExports?.refresh()}
 function result(row){latestRow=row;document.body.classList.add('has-task');if(!row._in_progress)$('task-settings').open=false;if(!readRows.length&&row.answer)setView('answer');if(!$('answer').childNodes.length)$('answer').append(el('p','本条任务未完成合法提交。候选、已读摘要、失败和成本仍保留，可展开实际过程核对。','notice'));const context=typeof resultContext!=='undefined'?resultContext:null;$('compact-task').textContent=context?`${context.original_need} · ${context.profile.label} · ${context.scope.label}`:row.task_id+' · '+(row.completed_protocol?'已提交':'未提交');if(!row.completed_protocol&&!row._in_progress)$('timeline-details').open=true;window.PapertrailExports?.refresh()}
 function reset(message){window.PapertrailProfiles?.clear();$('answer').replaceChildren(el('p','当前输入尚无已提交答案。历史失败与结果仍在原记录中。','empty'));$('timeline-details').open=false;$('citation-details').open=false;readRows=[];selectedDoc=null;taskKey=null;latestRow=null;latestActual=null;paintReader();$('flow-mini').textContent=message||'等待本次实际工具返回';$('compact-process').textContent='尚无本次记录';$('compact-task').textContent='核对当前需求、检索词与画像后执行';document.body.classList.remove('has-task');setView('abstract');window.PapertrailExports?.refresh()}
 function init(){
  $('show-abstract').onclick=()=>setView('abstract');$('show-answer').onclick=()=>setView('answer');$('show-process').onclick=()=>{$('timeline-details').open=true;$('timeline-details').scrollIntoView({block:'start',behavior:'instant'});$('timeline-details').querySelector('summary').focus()};
  // Entering a new composer mode does not run a task. The original controls retain validation.
  for(const id of ['mode-custom','mode-preset'])$(id).addEventListener('click',()=>{$('task-settings').open=true});
 }
 window.PapertrailWorkspace={reader,read,actual,result,reset,setView,get snapshot(){return {row:latestRow,actual:latestActual,runIndex:typeof selectedRun==='number'?selectedRun:0}}};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();

/* Reuses the existing report dialog's local Blob + object URL download pattern. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id);let jsonUrl=null,markdownUrl=null,generation=0;
 function revoke(){for(const url of [jsonUrl,markdownUrl])if(url)URL.revokeObjectURL(url);jsonUrl=markdownUrl=null;$('export-preview').hidden=true;for(const id of ['download-task-json','download-task-markdown'])$(id).removeAttribute('href')}
 function ready(s){return Boolean(s?.row&&s.actual&&s.row.task_id===s.actual.task_id&&!s.row._in_progress&&!s.actual.provisional&&(s.actual.source?.kind!=='job'||s.actual.source.run_index===s.runIndex))}
 function refresh(){if(!$('prepare-task-report'))return;generation++;revoke();const s=PapertrailWorkspace.snapshot,ok=ready(s);$('prepare-task-report').disabled=!ok;$('export-readiness').textContent=ok?'终局记录已就绪':'等待本次终局结果及实际候选证据'}
 async function generate(){const s=PapertrailWorkspace.snapshot;if(!ready(s))return;const ticket=++generation;$('prepare-task-report').disabled=true;$('export-error').textContent='';
  try{const context=typeof resultContext!=='undefined'&&resultContext?resultContext:{description:$('task-description').textContent},handoff=window.PapertrailHandoff?.snapshot,ownHandoff=handoff&&context.original_need===handoff.draft_need?handoff:null;
   const events=s.actual.source.kind==='job'&&typeof feed!=='undefined'&&feed.job===s.actual.source.job_id?[...feed.rows.values()]:[];
   const report=await PapertrailTaskReport.pack({...s,context,handoff:ownHandoff,events});if(ticket!==generation||PapertrailWorkspace.snapshot.row!==s.row)return;
   revoke();const json=JSON.stringify(report.envelope,null,2);jsonUrl=URL.createObjectURL(new Blob([json],{type:'application/json;charset=utf-8'}));markdownUrl=URL.createObjectURL(new Blob([report.markdown],{type:'text/markdown;charset=utf-8'}));
   for(const [id,url,ext]of [['download-task-json',jsonUrl,'json'],['download-task-markdown',markdownUrl,'md']]){$(id).href=url;$(id).download=report.filename+'.'+ext}
   $('task-report-preview').value=report.markdown;$('task-report-hash').textContent='内容 SHA-256：'+report.envelope.content_sha256;$('export-preview').hidden=false;
  }catch(e){$('export-error').textContent='报告未生成：'+e.message}finally{if(ticket===generation)$('prepare-task-report').disabled=!ready(PapertrailWorkspace.snapshot)}
 }
 function init(){$('prepare-task-report').onclick=generate;refresh()}
 window.PapertrailExports={refresh};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();

