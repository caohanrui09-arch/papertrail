import {h} from 'preact';
import htm from 'htm';
const html=htm.bind(h);

export function LearningPathIntro({guide}){
 if(!guide)return null;
 return html`<section class="learning-path-intro" aria-label="这条路径要解决的问题"><span class="learning-kicker">ONE QUESTION, THREE PAPERS</span><h3>${guide.goal}</h3><details><summary>读之前，需要哪些基础？</summary><ul>${guide.prerequisites.map(text=>html`<li>${text}</li>`)}</ul></details></section>`;
}

export function LearningCardPrompt({learning}){
 if(!learning)return null;
 return html`<div class="learning-card-prompt"><span class="learning-stage">${String(learning.position).padStart(2,'0')} / ${learning.stage}</span><p>${learning.why}</p></div>`;
}

export function LearningReaderPrompt({learning}){
 if(!learning)return null;
 return html`<aside class="learning-reader-prompt" aria-label="本篇阅读提示"><span class="learning-kicker">带着一个问题读</span><p>${learning.question}</p><details><summary>继续深入时，看什么？</summary><p>${learning.follow_up}</p><div class="learning-evidence"><span>导读对应的原摘要片段</span><blockquote>${learning.evidence}</blockquote></div><small>中文提示为编辑整理；原摘要仍完整保留。作者的摘要表述不等于本站验证了论文结论。</small></details></aside>`;
}
