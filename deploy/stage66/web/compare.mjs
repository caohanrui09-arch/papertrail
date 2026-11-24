import {h} from 'preact';
import {useEffect,useRef,useState} from 'preact/hooks';
import htm from 'htm';
import {Highlighted,PaperMetadata} from './papers.mjs?v=66.1';
import {MatchEvidence} from './search-feedback.mjs?v=66.1';
import {ReadingMode,ReadingText,ComparisonFacts} from './reading-view.mjs?v=66.1';
const html=htm.bind(h);
export function useComparison(){
 const [items,setItems]=useState([]),[open,setOpen]=useState(false);
 function has(doc){return items.some(p=>p.doc_id===doc);}
 function toggle(p){setItems(current=>current.some(x=>x.doc_id===p.doc_id)?current.filter(x=>x.doc_id!==p.doc_id):current.length<3?[...current,{doc_id:p.doc_id,title:p.title,version_key:p.version_key,source_url:p.source_url,search_match:p.search_match||null}]:current);}
 return {items,open,setOpen,has,toggle,clear:()=>setItems([]),remove:doc=>setItems(current=>current.filter(p=>p.doc_id!==doc))};
}
export function CompareToggle({paper,compare}){
 const checked=compare.has(paper.doc_id);
 return html`<label class="compare-choice" title="临时勾选2–3篇，保留各自加入时的查询依据"><input type="checkbox" aria-label=${'对比论文：'+paper.title} checked=${checked} disabled=${!checked&&compare.items.length>=3} onChange=${()=>compare.toggle(paper)}/><span>对比</span></label>`;
}
export function CompareAction({compare}){return html`<div class="compare-actions"><button disabled=${compare.items.length<2} title="勾选2–3篇后并排阅读原摘要" onClick=${()=>compare.setOpen(true)}>对比 ${compare.items.length}/3</button>${compare.items.length>0&&html`<button aria-label="清空对比选择" onClick=${compare.clear}>×</button>`}</div>`;}
export function ComparisonDialog({compare,previews,onRead,abstractMode,onAbstractMode}){
 const dialog=useRef(null),[papers,setPapers]=useState({}),[error,setError]=useState(''),[loading,setLoading]=useState(false),[attempt,setAttempt]=useState(0);
 const key=compare.items.map(p=>p.version_key).join(',');
 useEffect(()=>{if(compare.open)dialog.current?.showModal();else if(dialog.current?.open)dialog.current.close();},[compare.open]);
 useEffect(()=>{
  if(!compare.open||compare.items.length<2)return;
  const controller=new AbortController();setLoading(true);setError('');setPapers({});
  Promise.all(compare.items.map(async p=>{const r=await fetch('/api/paper-reading/'+encodeURIComponent(p.doc_id),{signal:controller.signal});if(!r.ok)throw Error('原摘要读取失败（'+r.status+'），请重试。');const data=await r.json();if(data.paper.version_key!==p.version_key||data.paper.title!==p.title||data.paper.source_url!==p.source_url||!data.trace?.some(t=>t.source_verified))throw Error('论文版本或来源不一致，请重新选文。');return [p.doc_id,data];})).then(rows=>{if(!controller.signal.aborted)setPapers(Object.fromEntries(rows));}).catch(e=>{if(e.name!=='AbortError')setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[compare.open,key,attempt]);
 return html`<dialog ref=${dialog} class="comparison-dialog" aria-labelledby="compare-title" onCancel=${()=>compare.setOpen(false)}><header><div><span class="eyebrow">READ SIDE BY SIDE</span><h2 id="compare-title">把线索，放在一起看。</h2><p>原摘要与版本对应；每篇保留加入对比时的查询依据。临时选择在刷新后清空。</p></div><button aria-label="关闭论文对比" onClick=${()=>compare.setOpen(false)}>×</button></header>${compare.items.length<2?html`<p class="comparison-empty">至少需要2篇论文。返回工作台继续勾选。</p>`:error?html`<div class="comparison-error" role="alert"><p>${error}</p><button onClick=${()=>setAttempt(n=>n+1)}>重新读取对比摘要</button></div>`:html`<div class=${'comparison-grid columns-'+compare.items.length} style=${{'--columns':compare.items.length}} aria-busy=${loading}>${compare.items.map(p=>html`<article key=${p.doc_id} class="comparison-paper"><div class="comparison-id"><code>${p.version_key}</code><button aria-label=${'移出对比：'+p.title} onClick=${()=>compare.remove(p.doc_id)}>移出</button></div><h3>${p.title}</h3><${PaperMetadata} paper=${p} previews=${previews}/><details class="comparison-match"><summary>匹配依据 · ${p.search_match?p.search_match.terms.length+' 个词项':'来源说明'}<span aria-hidden="true"> ↗</span></summary><${MatchEvidence} match=${p.search_match}/></details><${ComparisonFacts} facts=${papers[p.doc_id]?.comparison} scope=${papers[p.doc_id]?.comparison_scope}/><div class="comparison-abstract-heading"><h4>v1 摘要</h4><${ReadingMode} value=${abstractMode} onChange=${onAbstractMode}/></div><div class="compare-abstract" role="region" tabIndex="0" aria-label=${'对比原摘要：'+p.title}>${loading?'正在核验原摘要…':papers[p.doc_id]?html`<${ReadingText} paper=${papers[p.doc_id].paper} view=${papers[p.doc_id].reading_view} mode=${abstractMode} query=${p.search_match?.query||''} className="compare-reading-text" label=${'对比摘要内容：'+p.title}/>`:'摘要尚未返回'}</div><div class="comparison-paper-actions"><a href=${p.source_url} target="_blank" rel="noopener noreferrer">版本来源 ↗</a><button class="comparison-read" onClick=${()=>{compare.setOpen(false);onRead(p.doc_id);}}>在阅读器中继续 ↗</button></div></article>`)}</div>`}<footer><span>词项匹配不代表论文质量；不自动生成论文结论。</span><button onClick=${()=>compare.setOpen(false)}>返回工作台</button></footer></dialog>`;
}
