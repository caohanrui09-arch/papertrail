import {h} from 'preact';
import {useEffect,useState} from 'preact/hooks';
import htm from 'htm';
import {highlightParts} from './highlight.mjs';
const html=htm.bind(h);

export function Highlighted({text='',query=''}){
 return html`${highlightParts(text,query).map(c=>c.highlight?html`<mark class="query-hit">${text.slice(c.start,c.end)}</mark>`:text.slice(c.start,c.end))}`;
}
export function usePaperPreviews(){
 const [data,setData]=useState(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 useEffect(()=>{const c=new AbortController();setError('');fetch('/api/paper-previews',{signal:c.signal}).then(async r=>{if(!r.ok)throw Error('原摘要预览暂时不可用，可继续打开原摘要核验。');return r.json();}).then(setData).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();},[attempt]);
 return {error,loading:!data&&!error,retry(){setAttempt(n=>n+1);},get(paper){const value=data?.papers[paper.doc_id];return value&&value.version_key===paper.version_key&&value.title===paper.title&&value.source_url===paper.source_url?value:null;}};
}
export function PaperMetadata({paper,previews}){
 const p=previews.get(paper);
 return html`<div class="paper-metadata"><span class="paper-year" title=${p?'arXiv首次提交：'+p.published_at.slice(0,10)+'；非期刊发表时间':'提交年份暂不可用'}>${p?p.submitted_year:'年份待核验'}</span><span class="metadata-dot" aria-hidden="true">·</span><span>arXiv</span><span class="metadata-dot" aria-hidden="true">·</span><code>${paper.version_key}</code>${p&&html`<span class="metadata-date-kind">首次提交</span>`}</div>`;
}
export function AbstractPreview({paper,previews,query}){
 const p=previews.get(paper);
 if(!p)return html`<div class="abstract-preview-unavailable" role="status">${previews.loading?'正在读取原摘要预览…':'预览暂不可用，请打开原摘要核验。'}</div>`;
 return html`<div class="abstract-preview-block"><span class="preview-label">原摘要预览</span><p class="abstract-preview"><${Highlighted} text=${p.abstract_excerpt} query=${query}/>${p.excerpt_truncated?'…':''}</p></div>`;
}
export function ModelReview({review}){
 if(!review)return null;
 const labels={2:'明确匹配',1:'部分匹配',0:'主题不符'};
 return html`<details class="model-reference"><summary>模型参考 · ${labels[review.grade]}</summary><p>${review.reason}</p>${review.evidence&&html`<blockquote>${review.evidence}</blockquote>`}<small>非独立真人评价，未用于检索排名。</small></details>`;
}
