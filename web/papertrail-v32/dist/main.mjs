import {h,render} from 'preact';
import {useState,useEffect,useRef} from 'preact/hooks';
import htm from 'htm';
const html=htm.bind(h),labels={generative:'生成式文档检索',cold:'物品冷启动',bias:'曝光与离线评价'};
const gradeNames={2:'明确匹配',1:'部分匹配',0:'主题不符'};
async function api(path,signal){const r=await fetch(path,{signal});if(!r.ok)throw Error(`请求失败（${r.status}）`);return r.json();}
function traceDescription(t){
 if(t.tool==='核心检索')return `${t.method==='bm25'?'BM25':'内容 TF-IDF'} · ${t.eligible} 篇可检索 · 返回 ${t.returned} 篇候选`;
 if(t.tool==='候选内画像排序')return `${t.context==='same'?'同主题':'跨主题'}合成上下文 · 候选集合保持不变`;
 if(t.tool==='审查说明')return t.applies?'预设主题模型判断，仅用于说明':'自定义需求，未套用预设主题等级';
 if(t.tool==='读取官方原v1摘要')return `${t.doc_id} · 原始响应对应核验已通过`;
 return '';
}
function Trace({result,loading,paper,readState,readError,target}){
 return html`<section class="trace-panel" aria-label="本次调用轨迹"><div class="sectionline"><h2>本次调用</h2><span>TRACE</span></div>
 ${loading?html`<div class="trace-pending" role="status"><span class="activity"/>检索请求进行中<p>内部步骤以响应中的真实记录为准。</p></div>`:html`<ol class="steps">${(result?.trace||[]).map((t,i)=>html`<li class="step" key=${t.tool}><span class="step-mark">${i+1}</span><div><h3>${t.tool}<span class="step-state">已返回</span></h3><p>${traceDescription(t)}</p><details><summary>查看参数</summary><pre>${JSON.stringify(t,null,2)}</pre></details></div></li>`)}
 ${readState==='loading'&&html`<li class="step pending"><span class="step-mark activity"/><div><h3>读取原摘要<span class="step-state">进行中</span></h3><p>${target} · 等待原文核验响应</p></div></li>`}
 ${readState==='error'&&html`<li class="step failed"><span class="step-mark">!</span><div><h3>原摘要读取失败</h3><p>${readError}</p></div></li>`}
 ${readState==='ready'&&(paper?.trace||[]).map(t=>html`<li class="step" key=${'read:'+t.doc_id}><span class="step-mark">✓</span><div><h3>原摘要核验<span class="step-state">已返回</span></h3><p>${traceDescription(t)}</p><details><summary>查看参数</summary><pre>${JSON.stringify(t,null,2)}</pre></details></div></li>`)}</ol>`}</section>`;
}
function App(){
 const [meta,setMeta]=useState(null),[topic,setTopic]=useState('generative'),[q,setQ]=useState(''),[method,setMethod]=useState('bm25'),[context,setContext]=useState('none');
 const [result,setResult]=useState(null),[paper,setPaper]=useState(null),[status,setStatus]=useState('idle'),[error,setError]=useState('');
 const [readState,setReadState]=useState('idle'),[readError,setReadError]=useState(''),[target,setTarget]=useState(null),[batch,setBatch]=useState(0);
 const seq=useRef(0),readSeq=useRef(0),searchAbort=useRef(null),readAbort=useRef(null);
 useEffect(()=>{const controller=new AbortController();api('/api/meta',controller.signal).then(m=>{setMeta(m);setQ(m.topics.generative.core);}).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>{controller.abort();searchAbort.current?.abort();readAbort.current?.abort();};},[]);
 function clearReader(){readSeq.current++;readAbort.current?.abort();setPaper(null);setReadState('idle');setReadError('');setTarget(null);}
 function invalidate(){seq.current++;searchAbort.current?.abort();setStatus('idle');setResult(null);setError('');clearReader();}
 function changeTopic(t){invalidate();setTopic(t);setQ(meta.topics[t].core);}
 async function search(e){e?.preventDefault();if(!q.trim())return;
  const n=++seq.current;searchAbort.current?.abort();const controller=new AbortController();searchAbort.current=controller;
  clearReader();setResult(null);setStatus('loading');setError('');
  try{const value=await api('/api/search?'+new URLSearchParams({topic,q,method,context}),controller.signal);if(seq.current===n){setResult(value);setStatus(value.papers.length?'returned':'empty');setBatch(b=>b+1);}}
  catch(e){if(seq.current===n&&e.name!=='AbortError'){setError(e.message);setStatus('error');}}
 }
 async function read(doc){const n=++readSeq.current;readAbort.current?.abort();const controller=new AbortController();readAbort.current=controller;
  setPaper(null);setTarget(doc);setReadState('loading');setReadError('');
  try{const value=await api('/api/paper/'+encodeURIComponent(doc),controller.signal);if(n===readSeq.current){setPaper(value);setReadState('ready');}}
  catch(e){if(n===readSeq.current&&e.name!=='AbortError'){setReadError(e.message);setReadState('error');}}
 }
 if(!meta)return html`<main class="boot"><h2>${error?'连接未完成':'正在连接论文目录'}</h2><p role="status">${error||'核对本地服务与主题信息…'}</p>${error&&html`<button class="primary" onClick=${()=>location.reload()}>重新连接</button>`}</main>`;
 const busy=status==='loading',counts=meta.summary[topic];
 const buttonText={idle:'检索论文 →',loading:'正在检索…',returned:`返回 ${result?.papers.length||0} 篇 · 再次检索`,empty:'无匹配 · 修改重试',error:'重试检索 →'}[status];
 const statusText={idle:'输入英文核心术语，或直接检索当前主题。',loading:'正在等待检索响应，返回后显示实际步骤。',returned:'已返回候选；这不代表每篇都满足需求，请核对摘要证据。',empty:'没有词项匹配的候选，请修改查询；没有用历史信号补充结果。',error:'本次请求未完成。可以重试，或检查本机服务是否运行。'}[status];
 return html`<div class="shell"><aside class="nav"><a class="brand" href="/">◈ <span>Papertrail</span></a><div class="version">RESEARCH SPACE / 02</div><p class="navtitle">主题目录</p>${Object.keys(labels).map(t=>html`<button class=${topic===t?'topic active':'topic'} aria-pressed=${topic===t} onClick=${()=>changeTopic(t)}>${labels[t]}<span>↗</span></button>`)}<div class="navbottom"><span class="live">● 本机运行</span><p>42 篇原 v1<br/>独立搜索开发目录</p><a href="http://127.0.0.1:8770/" target="_blank" rel="noopener noreferrer">上一版入口 ↗</a><small>原服务需另行启动</small></div></aside>
 <main><header><div><div class="eyebrow">PAPER DISCOVERY / V2</div><h1>从主题出发，<em>沿证据阅读。</em></h1><p>核心检索与画像排序分开；每个判断都能回到原摘要。</p></div><span class="stamp">交互预览<br/>轻量动态</span></header>
 <form onSubmit=${search}><label for="query">你的论文需求</label><div class="queryrow"><input id="query" value=${q} maxLength="1000" onInput=${e=>{setQ(e.target.value);invalidate();}}/><button class=${'primary action-'+status} aria-busy=${busy} disabled=${busy||!q.trim()} type="submit">${busy&&html`<span class="activity"/>`}${buttonText}</button></div>
 <div class="controls"><label>检索方法 <select value=${method} onChange=${e=>{setMethod(e.target.value);invalidate();}}><option value="bm25">BM25</option><option value="tfidf">内容 TF-IDF</option></select></label><label>候选内排序 <select value=${context} onChange=${e=>{setContext(e.target.value);invalidate();}}><option value="none">保持核心检索顺序</option><option value="same">合成同主题上下文</option><option value="cross">合成跨主题上下文</option></select></label><button type="button" class="quiet" onClick=${()=>{setQ(meta.topics[topic].core);invalidate();}}>恢复核心主题</button></div><p class=${'search-status '+status} role="status" aria-live="polite">${statusText}</p></form>
 <div class="audit"><strong>模型摘要审查</strong><span>明确 ${counts['2']}</span><span>部分 ${counts['1']}</span><span>不符 ${counts['0']}</span><small>统计覆盖目录42篇，非独立真人评价</small></div>
 <details class="boundaries"><summary>判据与适用范围</summary><p>${meta.rules[topic]}</p><p>模型已参与项目设计并见过开发结果。等级只适用于预设核心主题；自定义查询显示“未审查”。摘要核验不代表核实全文结论，标签不参与过滤或排序。</p><p>阅读上下文是合成场景，不是你的真实收藏。</p></details>
 ${error&&html`<div role="alert" class="error">${error}</div>`}
 <div class="workspace"><section class="results" aria-label="检索结果" aria-busy=${busy}><div class="sectionline"><h2>${labels[topic]}</h2><span>${busy?'检索中':result?result.papers.length+' 篇候选':'等待检索'}</span></div>
 ${busy?html`<div class="loading-results"><p>正在查询当前目录…</p>${[0,1,2].map(i=>html`<div class="skeleton-card" aria-hidden="true"><div/><div/><div/></div>`)}</div>`:!result?html`<div class="empty"><span>↗</span><h3>先检索，再检查证据</h3><p>输入核心术语，也可以修改查询。<br/>选择上下文时，只在相同候选集合内调整顺序。</p></div>`:html`<p class="resultnote">${result.message}</p>${!result.papers.length&&html`<div class="empty"><h3>当前查询没有匹配结果</h3><p>修改上方术语，或恢复核心主题后重试。</p></div>`}<div class="result-batch" key=${batch}>${result.papers.map(p=>html`<article key=${p.doc_id} class=${'card'+(target===p.doc_id?' selected':'')+(target===p.doc_id&&readState==='loading'?' reading':'')}><div class="cardmeta"><span>${String(p.rank).padStart(2,'0')} / ${p.doc_id}</span><span class=${'badge g'+(p.review?.grade??'x')}>${p.review?gradeNames[p.review.grade]:'未审查此查询'}</span></div><h3><button class="titlebutton" aria-pressed=${target===p.doc_id} onClick=${()=>read(p.doc_id)}>${p.title}</button></h3><p>${p.review?.reason||'此查询没有对应判断，请阅读原摘要。'}</p><div class="cardfoot"><button class="quiet read-action" onClick=${()=>read(p.doc_id)}>${target===p.doc_id?(readState==='loading'?'正在读取…':readState==='ready'?'正在阅读 ✓':readState==='error'?'重试读取 ↗':'读取原摘要 ↗'):'读取原摘要 ↗'}</button><small>${p.version_key}</small></div></article>`)}</div>`}</section>
 <aside class="reader"><div class="sectionline"><h2>证据阅读器</h2><span>ORIGINAL / V1</span></div><section class="reader-slot" aria-label="原摘要阅读器" aria-busy=${readState==='loading'}>
 ${readState==='loading'?html`<div class="reader-loading" role="status"><span class="activity"/><h3>正在核验原摘要</h3><p>${target}</p><small>等待版本与原始响应对应核验。</small></div>`:readState==='error'?html`<div class="reader-failed" role="alert"><h3>这次读取未完成</h3><p>${readError}</p><button class="primary" onClick=${()=>read(target)}>重试读取</button></div>`:paper?html`<div class="readerbody reader-enter" key=${paper.paper.doc_id}><span class="live">● 官方缓存已核验</span><h3>${paper.paper.title}</h3><p class="mono">${paper.paper.version_key}</p><p class="abstract" tabIndex="0" aria-label="完整原摘要">${paper.paper.abstract}</p><a class="source" href=${paper.paper.source_url} target="_blank" rel="noopener noreferrer">打开版本对应来源 ↗</a>${result?.papers.find(p=>p.doc_id===paper.paper.doc_id)?.review&&html`<blockquote>判断所用短证据：${result.papers.find(p=>p.doc_id===paper.paper.doc_id).review.evidence}</blockquote>`}<p class="muted">核验表示摘要与原始响应对应，未核实论文实验结论。</p></div>`:html`<div class="readerempty"><span class="reader-symbol">↗</span><h3>把依据放在手边</h3><p>点击论文标题或“读取原摘要”，<br/>查看完整摘要与版本来源。</p></div>`}</section>
 ${result?.history.length>0&&html`<details><summary>本次合成阅读上下文</summary>${result.history.map(p=>html`<button class="history" onClick=${()=>read(p.doc_id)}>${p.title}</button>`)}</details>`}
 ${(result||busy)&&html`<${Trace} result=${result} loading=${busy} paper=${paper} readState=${readState} readError=${readError} target=${target}/>`}</aside></div>
 <footer>本机运行 · 检索请求没有调用 LLM · 没有产生真人标签 · 历史时点 ${meta.at.slice(0,10)}</footer></main></div>`;
}
document.getElementById('app').replaceChildren();
render(html`<${App}/>`,document.getElementById('app'));
