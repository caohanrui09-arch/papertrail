import {h} from 'preact';
import htm from 'htm';
import SpotlightCard from './spotlight.mjs';
const html=htm.bind(h);

function IndexSculpture(){return html`<svg class="index-sculpture" viewBox="0 0 560 450" fill="none" aria-hidden="true"><defs>
 <linearGradient id="gallery-paper" x1="260" y1="95" x2="470" y2="365" gradientUnits="userSpaceOnUse"><stop stop-color="#f6f9ff"/><stop offset="1" stop-color="#b2c9ef"/></linearGradient>
 <linearGradient id="gallery-blue" x1="240" y1="100" x2="480" y2="365" gradientUnits="userSpaceOnUse"><stop stop-color="#75a8ff"/><stop offset=".46" stop-color="#3274e4"/><stop offset="1" stop-color="#153a7d"/></linearGradient>
 <linearGradient id="gallery-glass" x1="140" y1="140" x2="440" y2="380" gradientUnits="userSpaceOnUse"><stop stop-color="#80b7ff" stop-opacity=".5"/><stop offset="1" stop-color="#4582d3" stop-opacity=".04"/></linearGradient>
 <radialGradient id="gallery-halo"><stop stop-color="#3777de" stop-opacity=".6"/><stop offset="1" stop-color="#1a2b4b" stop-opacity="0"/></radialGradient>
 <filter id="gallery-soft"><feGaussianBlur stdDeviation="15"/></filter></defs>
 <ellipse cx="378" cy="265" rx="195" ry="180" fill="url(#gallery-halo)"/>
 <g stroke="#55718f" stroke-opacity=".27"><path d="m180 352 174-102 185 106-174 102zM208 335l184 107m-151-126 184 107m-150-126 184 107m-150-126 184 107M213 371l174-102m-140 122 174-102m-140 122 174-102m-141 121 174-102"/></g>
 <ellipse cx="373" cy="365" rx="118" ry="23" fill="#070e19" opacity=".65" filter="url(#gallery-soft)"/>
 <g class="sculpture-back"><path d="m284 124 162 40-38 192-163-42z" fill="#15315c" stroke="#557bac"/><path d="m264 136 162 40-38 192-163-42z" fill="url(#gallery-glass)" stroke="#79a8db" stroke-opacity=".55"/><path d="m279 157 123 31m-128-8 123 31m-129-7 98 25" stroke="#86b6ef" stroke-opacity=".35" stroke-width="3"/></g>
 <g class="sculpture-front"><path d="m334 83 159 60-57 215-159-62z" fill="#7098ca"/><path d="m326 77 159 60-57 215-159-62z" fill="url(#gallery-paper)" stroke="#edf5ff"/>
 <path d="m344 110 76 29m-81-8 110 42m-120-5 110 42m-116-20 111 43m-117-20 84 32" stroke="#8ca8cb" stroke-width="4"/>
 <path d="m306 251 112 43-9 34-112-43z" fill="#2b5fa3"/><path d="m316 266 66 25" stroke="#b4cceb" stroke-width="3"/>
 <path d="m430 116 55 21-18 65-54-21z" fill="#d5e5fa"/><path d="m437 132 29 11-10 39-30-11z" fill="#7faae5"/>
 </g>
 <g class="sculpture-chip"><path d="m244 235 88 33-16 65-88-33z" fill="url(#gallery-blue)" stroke="#a2c6ff"/><path d="m249 251 21 8m-25 8 44 17m-48-1 32 13" stroke="#d2e4ff" stroke-width="3"/><path d="m313 283 4 3-6 26-5-1z" fill="#c9f477"/></g>
 <g><rect x="352" y="347" width="115" height="30" rx="15" fill="#c9f477"/><circle cx="369" cy="362" r="3" fill="#294022"/><text x="382" y="366" fill="#294022" font-family="Consolas,monospace" font-size="10" letter-spacing="1">DOC → ID</text></g>
 <circle cx="263" cy="119" r="4" fill="#b1c9ed"/><path d="M492 281v12m-6-6h12M230 196v10m-5-5h10" stroke="#7997bb"/>
 </svg>`;}

function InterestSculpture(){return html`<svg class="interest-sculpture" viewBox="0 0 260 220" fill="none" aria-hidden="true"><defs><linearGradient id="interest-paper" x1="78" y1="33" x2="213" y2="192" gradientUnits="userSpaceOnUse"><stop stop-color="#fff"/><stop offset="1" stop-color="#e5eade"/></linearGradient><filter id="interest-shadow"><feGaussianBlur stdDeviation="8"/></filter></defs>
 <ellipse cx="145" cy="185" rx="78" ry="12" fill="#657555" opacity=".13" filter="url(#interest-shadow)"/>
 <g class="interest-back"><rect x="91" y="53" width="91" height="119" rx="10" transform="rotate(20 91 53)" fill="#d8e4c9" stroke="#abbf96"/><path d="m105 75 47 18m-53-2 45 18" stroke="#97ad82" stroke-width="3"/></g>
 <g class="interest-front"><rect x="95" y="42" width="100" height="130" rx="11" transform="rotate(-12 95 42)" fill="url(#interest-paper)" stroke="#d0d8c4"/><path d="m112 65 48-10m-45 24 62-13m-59 27 62-13" stroke="#bbc9ab" stroke-width="3"/><path d="m122 112 41-9m-38 23 54-11" stroke="#d2dbc8" stroke-width="3"/>
 <path d="m152 30 21-5 8 36-14-5-7 10z" fill="#4b6542"/></g>
 <g class="interest-heart"><circle cx="99" cy="141" r="29" fill="#c9f477" stroke="#a2c773"/><path d="M99 153s-14-8-14-17c0-7 9-10 14-3 5-7 14-4 14 3 0 9-14 17-14 17Z" fill="#32472a"/></g>
 <circle cx="204" cy="105" r="4" fill="#6f8b57"/><circle cx="65" cy="81" r="3" fill="#a7b88d"/><path d="M211 151v10m-5-5h10" stroke="#9bad85"/>
 </svg>`;}

function EvaluationSculpture(){return html`<svg class="evaluation-sculpture" viewBox="0 0 260 220" fill="none" aria-hidden="true"><defs><linearGradient id="eval-bar" x1="90" y1="72" x2="181" y2="179" gradientUnits="userSpaceOnUse"><stop stop-color="#dca786"/><stop offset="1" stop-color="#a76849"/></linearGradient><linearGradient id="eval-glass" x1="160" y1="42" x2="195" y2="180" gradientUnits="userSpaceOnUse"><stop stop-color="#efe3d8" stop-opacity=".8"/><stop offset="1" stop-color="#d6bba4" stop-opacity=".12"/></linearGradient></defs>
 <path d="m59 165 99 35 81-40-98-35z" fill="#e8ded5"/><g stroke="#b9a18d" stroke-opacity=".4"><path d="m67 145 91 33 74-36M71 121l91 33 70-34M76 95l88 32 67-32" stroke-dasharray="2 5"/></g>
 <g class="eval-bars"><path d="m80 128 25 9v40l-25-9z" fill="#ceb7a6"/><path d="m105 137 13-7v40l-13 7z" fill="#ac8d77"/><path d="m80 128 13-7 25 9-13 7z" fill="#e5d6c9"/>
 <path d="m125 84 26 9v100l-26-9z" fill="url(#eval-bar)"/><path d="m151 93 14-7v100l-14 7z" fill="#905b43"/><path d="m125 84 14-7 26 9-14 7z" fill="#efc5a8"/>
 <path d="m174 112 24 9v54l-24-9z" fill="#bb9a82"/><path d="m198 121 13-7v54l-13 7z" fill="#98755d"/><path d="m174 112 13-7 24 9-13 7z" fill="#debfaa"/></g>
 <path class="eval-lens" d="m161 45 41 15v119l-41-15z" fill="url(#eval-glass)" stroke="#bda38c" stroke-opacity=".8"/>
 <path d="m92 79 35-20 56 20 28-18" stroke="#a0785d" stroke-width="1.5"/><circle cx="127" cy="59" r="4" fill="#9d6a4b"/><circle cx="211" cy="61" r="4" fill="#c9a184"/>
 <path d="M68 64v10m-5-5h10" stroke="#bca18d"/></svg>`;}

const copy={
 generative:{number:'01',overline:'GENERATIVE RETRIEVAL',title:'生成式检索',line:html`从一个问题，<br/>找到文档的坐标。`,tags:['DocID','神经索引'],theme:'dark'},
 cold:{number:'02',overline:'COLD START',title:'推荐冷启动',line:html`交互还少时，<br/>内容如何连接兴趣？`,tags:['内容推荐','兴趣画像'],theme:'light'},
 bias:{number:'03',overline:'BEYOND THE METRICS',title:'曝光与评价',line:html`看见指标背后，<br/>那些缺失的观测。`,tags:['曝光偏差','离线评价'],theme:'light'}
};

export function TopicGallery({onChoose,motion}){return html`<section class="topic-collection" aria-labelledby="collection-heading" data-reveal>
 <div class="collection-heading"><div><span class="collection-kicker">THE RESEARCH COLLECTION</span><h2 id="collection-heading">换一条线索，发现新方向<span>。</span></h2></div><p><span>03</span> 个研究专题</p></div>
 <div class="collection-grid">${Object.entries(copy).map(([key,t])=>html`<${SpotlightCard} key=${key} className=${'collection-card collection-'+key} theme=${t.theme} disabled=${!motion} ambient=${false} grain=${0} spotlightColor=${key==='generative'?'#8ab4ff':key==='cold'?'#8eab69':'#c69c7d'} intensity=${.18} borderGlow=${.5} proximity=${0}>
 <button class="collection-button" aria-label=${'探索'+t.title+'论文'} onClick=${()=>onChoose(key,true)}><span class="collection-top"><span class="collection-number">${t.number} <i>/</i> 专题</span><span class="collection-category">${t.overline}</span><span class="collection-arrow" aria-hidden="true">↗</span></span>
 <span class="collection-copy"><h3>${t.title}</h3><span class="collection-description">${t.line}</span></span>
 ${key==='generative'?html`<span class="index-watermark" aria-hidden="true">INDEX</span><${IndexSculpture}/>`:key==='cold'?html`<${InterestSculpture}/>`:html`<${EvaluationSculpture}/>`}
 <span class="collection-bottom"><span class="collection-tags">${t.tags.map(tag=>html`<span>${tag}</span>`)}</span><span class="collection-action">探索论文 <span aria-hidden="true">↗</span></span></span>
 </button></${SpotlightCard}>`)}</div><div class="collection-caption"><span>三种视角，同一个出发点：读到值得读的论文。</span><span>插画为主题示意</span></div>
 </section>`;}
