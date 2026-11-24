/* A fragment is untrusted user data. Only the strict server response fills fields. */
(() => {
 'use strict';
 let incoming=null,retainedQuery='',generation=0;
 const $=id=>document.getElementById(id),el=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n};
 function applyPlan(plan){
  if(!incoming||plan.original_need!==incoming.draft_need||plan.intent!==incoming.intent)return;
  $('custom-query').value=incoming.intent==='recommend'?'':retainedQuery;$('query-reviewed').checked=false;$('conditions-reviewed').checked=false;
  $('custom-status').textContent='已保留工作台传入的检索词；请在此重新确认画像、时点与全部限定，再手动执行。';syncControls();
 }
 async function init(){
  if(!location.hash.startsWith('#handoff='))return;
  const ticket=++generation;incoming=null;retainedQuery='';const holder=$('handoff-context')||el('section');holder.replaceChildren();holder.id='handoff-context';holder.className='handoff-context';holder.setAttribute('role','status');if(!holder.isConnected)$('task-settings').before(holder);
  try{
   const encoded=location.hash.slice(9);if(encoded.length>16000)throw Error('交接内容过长');
   const json=new TextDecoder('utf-8',{fatal:true}).decode(Uint8Array.from(atob(encoded.replaceAll('-','+').replaceAll('_','/')),c=>c.charCodeAt(0))),payload=JSON.parse(json);
   const r=await fetch('/lab/v76/handoff',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const value=await r.json();if(ticket!==generation)return;if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'交接字段未通过严格校验');
   if(typeof phase!=='undefined'&&['running','submitting','disconnected'].includes(phase)){holder.append(el('strong','交接已保留，当前作业仍在运行或待确认。'),el('p','先恢复当前作业；本页不会改写进行中的任务。'));return}
   incoming={...value.handoff,draft_need:value.draft_need};retainedQuery=incoming.executed_query;$('custom-query').addEventListener('input',()=>{retainedQuery=$('custom-query').value});
   // The profile selector and target clock stay server controlled, never copied from the source.
   $('mode-custom').click();$('task-settings').open=true;$('custom-need').value=incoming.draft_need;$('custom-need').dispatchEvent(new Event('input',{bubbles:true}));$('custom-intent').value=incoming.intent;$('custom-intent').dispatchEvent(new Event('change',{bubbles:true}));
   const sourceDetails=el('details');sourceDetails.append(el('summary','查看原问题、检索词与来源范围'));holder.append(el('strong','需求已带入 · 尚未执行'),el('p','确认画像与范围后继续。'),sourceDetails);sourceDetails.append(el('p','原问题：'+incoming.original_need),el('p','传入检索词：'+(incoming.executed_query||'推荐任务无检索词')),el('p',`来源筛选：${incoming.source_scope} / ${incoming.source_year||'全部年份'}；来源确认标记：${incoming.query_reviewed?'已确认（仅来源声明）':'未确认'}`),el('p',`目标：${value.target_scope.label} · ${value.target_scope.catalog} 篇 · 截止 ${value.target_scope.at}`),el('p',value.warning),el('p','下一步：选择服务端画像 → 整理需求 → 重新核对检索词与限定 → 点击执行。'));
   if(incoming.draft_need!==incoming.original_need)sourceDetails.append(el('p','已把来源筛选明确附加到执行草稿；原问题完整保留在上方。请核对后再生成方案，检索词保持原值。'));
   const details=el('details'),summary=el('summary','查看交接原始字段');details.append(summary,el('pre',JSON.stringify(value,null,2)));sourceDetails.append(details);
   history.replaceState(null,'',location.pathname+location.search);
  }catch(error){if(ticket!==generation)return;holder.append(el('strong','需求交接失败，未创建任务。'),el('p',error.message));history.replaceState(null,'',location.pathname+location.search)}
 }
 window.PapertrailHandoff={applyPlan,get snapshot(){return incoming}};window.addEventListener('hashchange',init);if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
