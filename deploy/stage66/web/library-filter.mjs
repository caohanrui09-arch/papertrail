import {h} from 'preact';
import htm from 'htm';
const html=htm.bind(h);
export function filterSaved(result,previews,reading,filters){
 if(!result)return result;
 const papers=result.papers.filter(p=>{const m=previews.get(p);return (filters.scope==='all'||(filters.scope==='core'?!m?.collections.includes('multimodal'):m?.collections.includes(filters.scope)))&&(!filters.year||String(m?.submitted_year)===filters.year)&&(filters.reading==='all'||reading.value(p.doc_id)===filters.reading);}).map((p,i)=>({...p,rank:i+1}));
 return {...result,papers,message:papers.length?'按你选择的条件整理收藏；不改变收藏或推荐画像。':'当前筛选下没有收藏论文；可以清除条件，收藏没有被删除。',trace:[...result.trace,{tool:'收藏筛选',...filters,before:result.papers.length,returned:papers.length,read_revision:reading.data?.revision}]};
}
export function LibraryFilters({value,onChange,collections,total,shown}){
 return html`<div class="library-filters" aria-label="收藏筛选"><label>收录主题<select aria-label="收藏主题" value=${value.scope} onChange=${e=>onChange({...value,scope:e.target.value})}>${collections.scopes.filter(s=>s.value!=='core').map(s=>html`<option value=${s.value}>${s.label}</option>`)}</select></label><label>年份<select aria-label="收藏年份" value=${value.year} onChange=${e=>onChange({...value,year:e.target.value})}><option value="">全部年份</option>${collections.years.map(y=>html`<option value=${String(y)}>${y}</option>`)}</select></label><label>阅读状态<select aria-label="收藏阅读状态" value=${value.reading} onChange=${e=>onChange({...value,reading:e.target.value})}><option value="all">全部状态</option><option value="none">未加入阅读清单</option><option value="to_read">待读</option><option value="reading">在读</option><option value="read">已读</option></select></label><button onClick=${()=>onChange({scope:'all',year:'',reading:'all'})}>清除筛选</button><span>${shown??0} / ${total} 篇收藏</span><small>主题沿用收录分组，可能重叠；不是人工相关性标签。</small></div>`;
}
