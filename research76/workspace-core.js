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
