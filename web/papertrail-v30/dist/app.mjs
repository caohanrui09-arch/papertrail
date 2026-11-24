import {h,render} from 'preact';
import {useState,useEffect,useRef} from 'preact/hooks';
import htm from 'htm';
const html=htm.bind(h),labels={generative:'生成式文档检索',cold:'物品冷启动',bias:'曝光与离线评价'};
const gradeNames={2:'明确匹配',1:'部分匹配',0:'主题不符'};
async function api(path){const r=await fetch(path);if(!r.ok)throw Error(`请求失败（${r.status}）`);return r.json();}
function App(){
 const [meta,setMeta]=useState(null),[topic,setTopic]=useState('generative'),[q,setQ]=useState(''),[method,setMethod]=useState('bm25'),[context,setContext]=useState('none');
 const [result,setResult]=useState(null),[paper,setPaper]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const seq=useRef(0),readSeq=useRef(0);
 useEffect(()=>{api('/api/meta').then(m=>{setMeta(m);setQ(m.topics.generative.core);}).catch(e=>setError(e.message));},[]);
 function changeTopic(t){seq.current++;readSeq.current++;setBusy(false);setTopic(t);setQ(meta.topics[t].core);setResult(null);setPaper(null);setError('');}
 function invalidate(){seq.current++;readSeq.current++;setBusy(false);setResult(null);setPaper(null);setError('');}
 async function search(e){e?.preventDefault();const n=++seq.current;readSeq.current++;setBusy(true);setError('');setPaper(null);
  try{const value=await api('/api/search?'+new URLSearchParams({topic,q,method,context}));if(seq.current===n)setResult(value);}
  catch(e){if(seq.current===n){setError(e.message);setResult(null);}}finally{if(seq.current===n)setBusy(false);}}
 async function read(doc){const n=++readSeq.current;try{const v=await api('/api/paper/'+encodeURIComponent(doc));if(n===readSeq.current)setPaper(v);}catch(e){setError(e.message);}}
 if(!meta)return html`<main class="boot">${error||'正在核验目录与原摘要…'}</main>`;
 const counts=meta.summary[topic];
 return html`<div class="shell"><aside class="nav"><a class="brand" href="/">◈ <span>Papertrail</span></a><div class="version">RESEARCH SPACE / 02</div><p class="navtitle">主题目录</p>${Object.keys(labels).map(t=>html`<button class=${topic===t?'topic active':'topic'} onClick=${()=>changeTopic(t)}>${labels[t]}<span>↗</span></button>`)}
 <div class="navbottom"><span class="live">● 本机运行</span><p>42 篇原 v1<br/>独立搜索开发目录</p><a href="http://127.0.0.1:8769/" target="_blank" rel="noopener noreferrer">原论文工作台 ↗</a><small>原服务需另行启动</small></div></aside>
 <main><header><div><div class="eyebrow">PAPER DISCOVERY / V2</div><h1>从主题出发，<em>沿证据阅读。</em></h1><p>核心检索与画像排序分开；每个判断都能回到原摘要。</p></div><span class="stamp">本地预览<br/>开发验证</span></header>
 <form onSubmit=${search}><label for="query">你的论文需求</label><div class="queryrow"><input id="query" value=${q} maxLength="1000" onInput=${e=>{setQ(e.target.value);setResult(null);setPaper(null);seq.current++;readSeq.current++;setBusy(false);}}/><button class="primary" disabled=${busy||!q.trim()} type="submit">${busy?'检索中…':'检索论文 →'}</button></div>
 <div class="controls"><label>检索方法 <select value=${method} onChange=${e=>{setMethod(e.target.value);invalidate();}}><option value="bm25">BM25</option><option value="tfidf">内容 TF-IDF</option></select></label><label>候选内排序 <select value=${context} onChange=${e=>{setContext(e.target.value);invalidate();}}><option value="none">保持核心检索顺序</option><option value="same">合成同主题上下文</option><option value="cross">合成跨主题上下文</option></select></label><button type="button" class="quiet" onClick=${()=>{setQ(meta.topics[topic].core);invalidate();}}>恢复核心主题</button></div></form>
 <div class="audit"><strong>模型摘要审查</strong><span>明确 ${counts['2']}</span><span>部分 ${counts['1']}</span><span>不符 ${counts['0']}</span><small>统计覆盖目录42篇，非独立真人评价</small></div>
 <details class="boundaries"><summary>判据与适用范围</summary><p>${meta.rules[topic]}</p><p>模型已参与项目设计并见过开发结果。等级仅适用于预设核心主题；自定义查询显示“未审查”。未核验全文结论，未按标签筛选或排序。</p><p>上下文均为合成阅读场景，不是你的真实收藏。42篇仅是小规模开发目录；词项匹配不保证语义满足。</p></details>
 ${error&&html`<div role="alert" class="error">${error}，请重试。</div>`}
 <div class="workspace"><section class="results"><div class="sectionline"><h2>${labels[topic]}</h2><span>${result?result.papers.length+' 篇候选':'等待检索'}</span></div>
 ${!result?html`<div class="empty"><span>↗</span><h3>先检索，再检查证据</h3><p>输入核心术语，也可以修改查询。<br/>选择上下文时，只在同一候选集合里调整顺序。</p></div>`:html`<p class="resultnote">${result.message}</p>${!result.papers.length&&html`<div class="empty">没有匹配结果，请尝试更具体或不同的英文术语。</div>`}${result.papers.map(p=>html`<article class=${paper?.paper.doc_id===p.doc_id?'card selected':'card'}><div class="cardmeta"><span>${String(p.rank).padStart(2,'0')} / ${p.doc_id}</span><span class=${'badge g'+(p.review?.grade??'x')}>${p.review?gradeNames[p.review.grade]:'未审查此查询'}</span></div><h3><button class="titlebutton" onClick=${()=>read(p.doc_id)}>${p.title}</button></h3><p>${p.review?.reason||'当前查询没有对应的相关性判断，请阅读原摘要。'}</p><div class="cardfoot"><button class="quiet" onClick=${()=>read(p.doc_id)}>读取原摘要 ↗</button><small>${p.version_key}</small></div></article>`)}`}</section>
 <aside class="reader"><div class="sectionline"><h2>证据阅读器</h2><span>ORIGINAL / V1</span></div>${paper?html`<div class="readerbody"><span class="live">● 官方缓存已核验</span><h3>${paper.paper.title}</h3><p class="mono">${paper.paper.version_key}</p><p class="abstract">${paper.paper.abstract}</p><a class="source" href=${paper.paper.source_url} target="_blank" rel="noopener noreferrer">打开版本对应来源 ↗</a>${result?.papers.find(p=>p.doc_id===paper.paper.doc_id)?.review&&html`<blockquote>判断所用短证据：${result.papers.find(p=>p.doc_id===paper.paper.doc_id).review.evidence}</blockquote>`}<p class="muted">核验仅表示摘要与原始响应对应，不代表核实了论文的实验结论。</p></div>`:html`<div class="readerempty">点击论文标题或“读取原摘要”，<br/>查看完整原摘要及版本链接。</div>`}
 ${result?.history.length>0&&html`<details><summary>本次合成阅读上下文</summary>${result.history.map(p=>html`<button class="history" onClick=${()=>read(p.doc_id)}>${p.title}</button>`)}</details>`}
 ${result&&html`<details open class="trace"><summary>调用轨迹</summary>${[...result.trace,...(paper?.trace||[])].map((t,i)=>html`<div class="traceitem"><b>${i+1}. ${t.tool}</b><pre>${JSON.stringify(t,null,2)}</pre></div>`)}</details>`}</aside></div>
 <footer>仅在当前电脑运行 · 没有调用 LLM · 没有产生真人标签 · 历史时点 ${meta.at.slice(0,10)}</footer></main></div>`;
}
document.getElementById('app').replaceChildren();
render(html`<${App}/>`,document.getElementById('app'));
