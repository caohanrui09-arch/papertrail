import {h} from 'preact';
import {useEffect,useRef,useState} from 'preact/hooks';
import htm from 'htm';
import {requestJSON} from './research-client.mjs?v=66.1';
const html=htm.bind(h);
export function useQueryBridge(need,onProposed){
 const [plan,setPlan]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[expanded,setExpanded]=useState(false),[confirmed,setConfirmed]=useState('');
 const live=useRef(need),sequence=useRef(0),controller=useRef(null);live.current=need;
 useEffect(()=>()=>controller.current?.abort(),[]);
 async function generate(){if(!need.trim())return;const value=need,n=++sequence.current;controller.current?.abort();controller.current=new AbortController();setBusy(true);setError('');setConfirmed('');try{const next=await requestJSON('/api/query-plan?'+new URLSearchParams({need:value}),null,controller.current.signal);if(n===sequence.current&&live.current===value){setPlan(next);onProposed(next.proposed_query);}}catch(e){if(e.name!=='AbortError')setError(e.message);}finally{if(n===sequence.current)setBusy(false);}}
 function accept(next){setPlan(next);if(next.reviewed)setConfirmed(next.original_need);}
 const ready=plan?.original_need===need,reviewed=ready&&confirmed===need;
 return {plan:ready?plan:null,ready,busy,error,expanded,setExpanded,generate,accept,reviewed,
  confirm:checked=>setConfirmed(checked?need:''),resetReview:()=>setConfirmed(''),canSearch:!need.trim()||(ready&&(!plan.review_required||reviewed))};
}
export function QueryBridgePanel({need,onNeed,bridge,onClear}){
 if(!bridge.expanded)return null;
 return html`<section class="query-bridge" aria-label="中文需求辅助"><div class="bridge-input"><label for="original-need">先说你的问题</label><textarea id="original-need" aria-label="原始中文需求" value=${need} maxLength="1000" rows="2" placeholder="例如：多模态快慢思考，模型怎样按问题难度决定推理深度？" onInput=${e=>onNeed(e.target.value)}/><div><button type="button" disabled=${bridge.busy||!need.trim()} onClick=${bridge.generate}>${bridge.busy?'正在整理…':'生成英文检索词'}</button><button type="button" onClick=${onClear}>清除原问题</button><small>术语表辅助，不是全文翻译。英文词可在下方修改，再点击搜索。</small></div></div>${bridge.error&&html`<p role="alert">${bridge.error}</p>`}${need&&!bridge.ready&&!bridge.busy&&html`<p class="bridge-pending" role="status">原问题尚未整理，或已经修改。先生成并检查英文词，再执行搜索。</p>`}${bridge.plan&&html`<details class="bridge-explanation"><summary>查看转换过程 · ${bridge.plan.mappings.length} 项映射${bridge.plan.review_required?' · 需要检查':''}</summary><p>建议：<code>${bridge.plan.proposed_query||'暂无可用建议，请手动填写'}</code></p><ul>${bridge.plan.mappings.map(m=>html`<li><span>${m.phrase}</span><span aria-hidden="true">→</span><b>${m.english}</b></li>`)}</ul>${bridge.plan.retained_english.length>0&&html`<p>保留英文：${bridge.plan.retained_english.join(' · ')}</p>`}${bridge.plan.warnings.map(w=>html`<p class="bridge-warning">${w}</p>`)}<small>${bridge.plan.glossary_version}</small></details>`}${bridge.plan?.review_required&&html`<label class="bridge-confirm"><input type="checkbox" checked=${bridge.reviewed} onChange=${e=>bridge.confirm(e.target.checked)}/>我已检查并补充检索词，理解未识别或排除条件需要人工判断。</label>`}</section>`;
}
export function QueryProvenance({plan}){
 if(!plan)return null;
 return html`<details class="query-provenance"><summary>原问题与实际检索词${plan.edited?' · 已修改建议':''}</summary><p class="provenance-need">${plan.original_need}</p><dl><dt>术语建议</dt><dd>${plan.proposed_query||'暂无建议'}</dd><dt>实际执行</dt><dd>${plan.executed_query}</dd></dl><p>${plan.scope}</p>${plan.warnings.map(w=>html`<p>${w}</p>`)}</details>`;
}
