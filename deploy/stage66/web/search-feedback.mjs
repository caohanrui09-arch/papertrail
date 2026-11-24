import {h} from 'preact';
import htm from 'htm';
import {QueryProvenance} from './query-bridge.mjs?v=66.1';
const html=htm.bind(h);
const fields={title:'标题',abstract:'摘要',boundary:'标题与摘要边界'};
export function MatchEvidence({match}){
 if(!match)return html`<p class="match-unavailable">这篇来自收藏、推荐或导读，没有随附关键词检索依据。</p>`;
 return html`<div class="match-evidence"><p>查询：<q>${match.query}</q><span>${match.kind}</span></p>${match.terms.length?html`<ul>${match.terms.slice(0,12).map(t=>html`<li><b>${t.term}</b><span>${t.fields.map(f=>fields[f]).join('、')}</span></li>`)}</ul>`:html`<p>所展示的词项中没有匹配；此处不推断语义相关性。</p>`}${(match.terms.length>12||match.partial)&&html`<small>仅展示部分词项；不作为完整得分分解。</small>`}</div>`;
}
export function SearchFeedback({feedback,onSuggest,queryPlan,filters,onExpand}){
 if(!feedback)return null;
 return html`<details class="search-feedback"><summary>${feedback.returned?'已返回 '+feedback.returned+' 篇':'当前范围未返回结果'}<span>可搜 ${feedback.eligible} / ${feedback.catalog} 篇 · 查看范围与词项</span></summary><div class="search-feedback-body">${filters&&html`<div class="active-scope-note"><strong>${filters.label} · ${filters.year||'全部年份'}</strong><button type="button" onClick=${onExpand}>扩大到全部目录</button><p>先按范围过滤，再取前十；主题沿用收录分组，可能重叠，不是人工相关性判断。</p></div>`}<${QueryProvenance} plan=${queryPlan}/><p>${feedback.scope}</p><p>主题：${feedback.topics.join('、')}。目录时点（UTC）${feedback.as_of.slice(0,10)}；${feedback.excluded} 篇预设演示过滤项不参加搜索。</p><dl><dt>目录可匹配词项</dt><dd>${feedback.indexed_terms.join(' · ')||'本次未检测到'}</dd><dt>目录未匹配词项</dt><dd>${feedback.unmatched_terms.join(' · ')||'无'}</dd>${feedback.ignored_terms.length>0&&html`<dt>停用词</dt><dd>${feedback.ignored_terms.join(' · ')}</dd>`}</dl><p>${feedback.kind}；${feedback.notice}</p>${feedback.terms_truncated&&html`<p>查询词项较多，只展示前128项诊断。</p>`}${!feedback.returned&&html`<${SearchSuggestions} feedback=${feedback} onSuggest=${onSuggest}/>`}</div></details>`;
}
export function SearchSuggestions({feedback,onSuggest}){
 if(!feedback)return null;
 return html`<div class="search-suggestions"><p>这不是全网检索，也不表示论文不存在。试试目录内已有主题：</p>${feedback.suggestions.map(s=>html`<button type="button" onClick=${()=>onSuggest(s)}><strong>${s.label}</strong><span>${s.query} ↗</span></button>`)}</div>`;
}
