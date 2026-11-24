import {h} from 'preact';
import htm from 'htm';
import {Highlighted} from './papers.mjs?v=66.1';
const html=htm.bind(h);
export function ReadingMode({value,onChange}){return html`<div class="reading-view-toggle" role="group" aria-label="摘要显示方式"><button type="button" aria-pressed=${value==='clean'} onClick=${()=>onChange('clean')}>清洁阅读</button><button type="button" aria-pressed=${value==='original'} onClick=${()=>onChange('original')}>原始文本</button></div>`;}
export function ReadingText({paper,view,mode,query='',className='abstract',label='摘要内容'}){
 const clean=mode==='clean'&&view;
 return html`<div class="reading-text"><p class=${className} tabIndex="0" aria-label=${label}><${Highlighted} text=${clean?view.text:paper.abstract} query=${query}/></p>${clean&&html`<small class="reading-view-notice">仅整理显示格式，原文与检索索引保持不变。公式保留TeX文本。${view.warnings.map(w=>html`<span>${w}</span>`)}</small>`}</div>`;
}
export function ComparisonFacts({facts,scope}){
 if(!facts)return html`<p class="comparison-unreviewed">— 尚未核实这些比较项</p>`;
 const labels={control:'控制什么',selection:'如何选择快慢',training:'是否需要训练'};
 return html`<details class="comparison-facts"><summary>研究方法对比 · 摘要依据</summary><p>${scope||'基于明确v1摘要整理；没有说明的项目留空。'}</p><dl>${Object.entries(labels).map(([key,label])=>html`<div><dt>${label}</dt><dd>${facts[key]?html`<p>${facts[key].value}</p><details><summary>查看原文依据</summary><blockquote>${facts[key].evidence}</blockquote><a href=${facts[key].source_url} target="_blank" rel="noopener noreferrer">${facts[key].version_key} · Abstract ↗</a></details>`:html`<span class="unverified">— 未核实（摘要未明确）</span>`}</dd></div>`)}</dl><small>助手依据原摘要整理，不是独立真人标注；未核验全文和实验结论。</small></details>`;
}
