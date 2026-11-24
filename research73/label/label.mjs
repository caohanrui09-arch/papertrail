import {h,render} from 'preact';
import {useState,useEffect,useRef} from 'preact/hooks';
import htm from 'htm';
const html=htm.bind(h);
const verification=new URLSearchParams(location.search).get('verification')==='1';
const headers=()=>verification?{'X-Papertrail-Verification':'1'}:{};
const labels={topic:'主题搜索',recommend:'个性化推荐',mixed:'组合需求'};
const statuses={pending:'待确认',draft:'已存草稿',approve:'已确认',reject:'已拒绝',clarify:'待澄清',submitted:'已提交',skipped:'无法判断'};
const emptyReview={decision:'',reviewer:'',note:''},emptyJudgment={grade:'',reviewer:'',rationale:''};
async function api(path,method='GET',data){const r=await fetch('/api/annotation'+path,{method,headers:{...headers(),...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{})});const body=await r.json();if(!r.ok){const e=Error(typeof body.detail==='string'?body.detail:'请求参数未通过校验');e.code=r.status;throw e;}return body;}
function Source({paper}){let url;try{const parsed=new URL(paper.source_url);if(parsed.protocol==='https:'&&parsed.hostname==='arxiv.org')url=parsed.href;}catch{}return html`<div class="source-meta"><span>arXiv ${paper.doc_id} · v${paper.version}</span>${url&&html`<a href=${url} target="_blank" rel="noopener noreferrer">打开原始来源 ↗</a>`}<span>原始版本已核验</span></div>`;}
function Editor({kind,value,onChange,editorRef}){
  const node=useRef(null);
  useEffect(()=>{
    const properties=kind==='review'?{
      decision:{type:'string',title:'这条需求能否用于评价？',enum:['','approve','reject','clarify'],options:{enum_titles:['请选择','确认：需求清楚、可评价','拒绝：不适合作为本轮需求','待澄清：需要修改或补充']}},
      reviewer:{type:'string',title:'判断者标识（可用化名）',maxLength:64},
      note:{type:'string',format:'textarea',title:'确认理由或需要澄清的内容',maxLength:4000}
    }:{
      grade:{type:'string',title:'相关性等级',enum:['','0','1','2'],options:{enum_titles:['请选择；无法判断可留空','0 · 不相关','1 · 部分相关','2 · 高度相关']}},
      reviewer:{type:'string',title:'判断者标识（可用化名）',maxLength:64},
      rationale:{type:'string',format:'textarea',title:'判断依据／无法判断的原因',maxLength:4000}
    };
    let ready=false;
    const initial=JSON.stringify(value);
    const editor=new window.JSONEditor(node.current,{schema:{type:'object',title:kind==='review'?'需求确认表':'论文相关性判断',properties,additionalProperties:false,required:Object.keys(properties)},
      startval:value,theme:'html',disable_collapse:true,disable_edit_json:true,disable_properties:true,no_additional_properties:true,show_errors:'never',use_default_values:true});
    const syncAll=()=>{
      const values={...editor.getValue()};
      for(const key of Object.keys(properties)){
        const field=node.current.querySelector(`[name="root[${key}]"]`);
        if(field)values[key]=field.value;
      }
      editor.setValue(values);
      return editor.getValue();
    };
    const adapter={getValue:syncAll,validate:()=>editor.validate(),isDirty:()=>JSON.stringify(syncAll())!==initial};
    editorRef.current=adapter;
    editor.on('ready',()=>{ready=true;});
    editor.on('change',()=>{if(ready)onChange(JSON.stringify(editor.getValue())!==initial);});
    const syncInput=event=>{
      const path=event.target.closest('[data-schemapath]')?.getAttribute('data-schemapath');
      if(!path||!Object.keys(properties).some(k=>path==='root.'+k))return;
      editor.getEditor(path)?.setValue(event.target.value);
      if(ready)onChange(JSON.stringify(editor.getValue())!==initial);
    };
    node.current.addEventListener('input',syncInput,true);
    return()=>{node.current?.removeEventListener('input',syncInput,true);if(editorRef.current===adapter)editorRef.current=null;editor.destroy();};
  },[]);
  return html`<div class="native-editor" ref=${node}></div>`;
}
function App(){
  const [workspace,setWorkspace]=useState(null),[detail,setDetail]=useState(null),[qid,setQid]=useState(null),[candidate,setCandidate]=useState(null),[tab,setTab]=useState('review');
  const [dirty,setDirty]=useState(false),[saving,setSaving]=useState(false),[attest,setAttest]=useState(false),[notice,setNotice]=useState(''),[error,setError]=useState(''),[conflict,setConflict]=useState(false),[history,setHistory]=useState(null),[reloadKey,setReloadKey]=useState(0);
  const [alias,setAlias]=useState('');const editor=useRef(null),requestVersion=useRef(0);
  const selected=detail?.candidates.find(c=>c.annotation_id===candidate),kind=tab==='review'?'review':'judgment',record=kind==='review'?detail?.review:selected?.record;
  const currentValue=record?.value;
  const initial=kind==='review'?{decision:currentValue?.decision||'',reviewer:currentValue?.reviewer||alias,note:currentValue?.note||''}:{grade:currentValue?.grade==null?'':String(currentValue.grade),reviewer:currentValue?.reviewer||alias,rationale:currentValue?.rationale||''};
  async function refreshWorkspace(){const value=await api('/workspace');setWorkspace(value);return value;}
  function canNavigate(){if(editor.current?.isDirty()||dirty){setDirty(true);setNotice('有未保存修改。请先保存草稿，或使用“放弃未保存修改”恢复已存版本。');return false;}return !saving;}
  async function openQuery(id,preferredTab){if(!canNavigate())return;const n=++requestVersion.current;setSaving(true);setError('');try{const data=await api('/queries/'+id);if(n!==requestVersion.current)return;setDetail(data);setQid(id);setCandidate(data.candidates[0]?.annotation_id||null);setTab(preferredTab||(data.labeling_unlocked?'judgment':'review'));setDirty(false);setAttest(false);setHistory(null);setConflict(false);}catch(e){setError(e.message);}finally{setSaving(false);}}
  useEffect(()=>{refreshWorkspace().then(w=>{if(w.queries.length)openQuery(w.queries[0].query_id,'review');}).catch(e=>setError(e.message));},[]);
  useEffect(()=>{const handler=e=>{if(dirty){e.preventDefault();e.returnValue='';}};addEventListener('beforeunload',handler);return()=>removeEventListener('beforeunload',handler);},[dirty]);
  function chooseTab(next){if(!canNavigate())return;if(next==='judgment'&&!detail.labeling_unlocked){setNotice('先提交“确认需求”，才能保存相关性判断。');return;}setTab(next);setAttest(false);setHistory(null);setConflict(false);}
  function chooseCandidate(id){if(!canNavigate())return;setCandidate(id);setAttest(false);setHistory(null);setConflict(false);}
  async function reloadCurrent(){if(saving)return;try{const data=await api('/queries/'+qid);setDetail(data);setDirty(false);setConflict(false);setAttest(false);setReloadKey(k=>k+1);setNotice('已加载服务端保存的版本。');}catch(e){setError(e.message);}}
  function restoreSaved(){if(saving)return;setDirty(false);setAttest(false);setReloadKey(k=>k+1);setNotice('已恢复最后保存的内容。');}
  async function save(operation){if(saving)return;if(!editor.current){setError('表单尚未就绪，请重新载入当前记录。');return;}const value=editor.current.getValue();const validation=editor.current.validate();if(validation.length){setError('请检查输入字段的类型和长度。');return;}setSaving(true);setError('');setNotice('');
    try{const body={...value,revision:record.revision,operation,attest};if(kind==='judgment')body.grade=value.grade===''?null:Number(value.grade);
      const path=kind==='review'?'/reviews/'+qid:'/judgments/'+qid+'/'+candidate;
      await api(path,'PUT',body);setAlias(value.reviewer||alias);
      const fresh=await api('/queries/'+qid);setDetail(fresh);setDirty(false);setAttest(false);setConflict(false);setHistory(null);
      await refreshWorkspace();setNotice(operation==='draft'?'草稿已保存，可以稍后继续。':operation==='skip'?'已记录无法判断，等级保持空白，不计入已提交覆盖。':kind==='review'?'需求结论已提交。确认后的需求可以开始逐篇判断。':'判断已提交。修改后再次提交会保留原修订记录。');
    }catch(e){setError(e.message);if(e.code===409)setConflict(true);}finally{setSaving(false);}}
  async function showHistory(){if(!canNavigate())return;try{setHistory(await api('/history/'+qid+'/'+kind+'/'+(kind==='review'?'review':candidate)));}catch(e){setError(e.message);}}
  async function download(format){try{const r=await fetch('/api/annotation/export?format='+format,{headers:headers()});if(!r.ok)throw Error('导出失败');const blob=await r.blob();const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='papertrail-stage73-'+format+'.json';a.click();URL.revokeObjectURL(url);setNotice('已导出当前空间的保存记录。');}catch(e){setError(e.message);}}
  const index=detail?.candidates.findIndex(c=>c.annotation_id===candidate)??-1;
  return html`<div class="label-shell"><header class="label-header"><a class="label-brand" href="/"><img src="/mark.svg" alt=""/><strong>Papertrail</strong><span>需求确认与盲标</span></a><div class="header-scope"><span class="dot"></span>本地保存 · 阶段73</div><a href="/evaluation.html" onClick=${e=>{if(!canNavigate())e.preventDefault();}}>返回评测证据 ↗</a></header>
    ${verification&&html`<div class="verification-banner">自动化验收空间：此处的确认与判断均标为测试，不计入真人统计。</div>`}
    <div class="label-layout"><aside class="task-sidebar"><div class="sidebar-intro"><span class="overline">REVIEW THE REQUEST.</span><h1>先明确需求，<br/>再判断论文。</h1><p>先确认需求是否清楚，再依据原摘要逐篇判断。你的草稿和修订会保存在本机。</p></div>
      <div class="workspace-progress"><div><strong>${workspace?.approved||0}<small> / ${workspace?.total_queries||26}</small></strong><span>已确认需求</span></div><div><strong>${workspace?.submitted||0}<small> / ${workspace?.total_pairs||'—'}</small></strong><span>已提交判断</span></div></div>
      <nav class="query-list" aria-label="本轮需求列表">${workspace?.queries.map((q,i)=>html`<button class=${q.query_id===qid?'selected':''} disabled=${saving} onClick=${()=>openQuery(q.query_id)}><span class="task-num">${String(i+1).padStart(2,'0')}</span><span><strong>${q.topic}</strong><small>${labels[q.intent]} · ${statuses[q.review_status]} · ${q.submitted}/${q.candidates}</small></span></button>`)}</nav>
      <div class="sidebar-export"><button onClick=${()=>download('native')}>导出保存记录 ↓</button><button onClick=${()=>download('label-studio')}>导出 Label Studio 格式 ↓</button><small>仅导出当前空间。草稿与无法判断不等于已完成标注。</small></div></aside>
    <main class="label-main">${error&&html`<div class="error-message" role="alert">${error}${conflict&&html`<button onClick=${reloadCurrent}>放弃本次修改并加载最新版本</button>`}</div>`}${notice&&html`<div class="notice" role="status">${notice}<button aria-label="关闭提示" onClick=${()=>setNotice('')}>×</button></div>`}
      ${detail?html`<section class="request-card"><div class="card-kicker">${labels[detail.query.intent]}<span>${detail.query.query_id} · ${detail.query.query_origin}</span></div><h2>${detail.query.request_zh}</h2><p class="request-en">${detail.query.request}</p><p class="evaluation-context">实际评价查询：${detail.query.confirmed_query}<br/>画像范围：${detail.query.profile_scope}<br/>来源：${detail.query.query_origin}；曾使用：${detail.query.previously_used?'是':'否'}。需确认限定条件；本轮不做独立测试声明。</p><div class="focus-grid"><div><span>核心要求</span><p>${detail.query.required_focus_zh}</p></div><div><span>次要偏好</span><p>${detail.query.preferred_focus_zh}</p></div></div>
      <details class="rubric"><summary>查看相关性判据与判断边界</summary><p><b>2 · 高度相关</b>${detail.query.grade_2_rule}</p><p><b>1 · 部分相关</b>${detail.query.grade_1_rule}</p><p><b>0 · 不相关</b>${detail.query.grade_0_rule}</p><p>只有能可靠确定部分相关时才判1；无法理解或证据不足时保留空白并说明。次要偏好不单独升降等级。</p></details>
      <details class="reading-context"><summary>阅读上下文 · ${detail.context.length?detail.context.length+' 篇固定材料':'本条主题需求不使用阅读上下文'}</summary>${detail.context.length?html`<p class="context-note">这是任务提供的相同阅读场景，不是你的个人收藏；显式主题优先。</p>${detail.context.map(p=>html`<article><h3>${p.title}</h3><${Source} paper=${p}/><p>${p.abstract}</p></article>`)}`:html`<p>按明确主题判断，不假定额外兴趣。</p>`}</details></section>
      <div class="review-tabs"><button class=${tab==='review'?'active':''} onClick=${()=>chooseTab('review')}>1 · 确认需求 <span>${statuses[detail.review.value?.status||'pending']}</span></button><button class=${tab==='judgment'?'active':''} onClick=${()=>chooseTab('judgment')}>2 · 判断候选 <span>${detail.candidates.filter(c=>c.valid_submission).length}/${detail.candidates.length}</span></button></div>
      ${tab==='review'?html`<section class="review-grid"><div class="review-guide"><span class="overline">MAKE IT JUDGEABLE.</span><h2>这条需求是否清楚，<br/>能否据摘要判断？</h2><p>确认：核心对象与条件清晰，可按给定判据判断。<br/>拒绝：不适合本轮使用。<br/>待澄清：需要补充或修改问题。</p><p>需要改正文或判据时，选择“待澄清”并写明修改建议。新文本需要新的候选池。</p><div class="subtle-warning">重新提交需求结论后，旧判断仍保留；确认版本变化会使旧判断需要重新提交。</div></div><section class="editor-card"><div class="editor-heading"><h3>确认需求</h3><span>${dirty?'未保存修改':record?.revision?'已保存 · 版本 '+record.revision:'尚未保存'}</span></div><${Editor} key=${qid+':review:'+record.revision+':'+reloadKey} kind="review" value=${initial} editorRef=${editor} onChange=${setDirty}/><${Declaration} checked=${attest} onChange=${setAttest}/><div class="form-buttons"><button disabled=${saving} onClick=${()=>save('draft')}>保存草稿</button><button class="primary" disabled=${saving} onClick=${()=>save('submit')}>提交需求结论</button></div><${RecordTools} record=${record} dirty=${dirty} saving=${saving} restore=${restoreSaved} history=${showHistory}/></section></section>`:
        html`<div class="candidate-section"><div class="candidate-toolbar"><span>候选顺序与算法无关 · 已隐藏方法、排名和分数</span><div><button disabled=${saving||index<=0} onClick=${()=>chooseCandidate(detail.candidates[index-1].annotation_id)}>上一篇</button><span>${index+1} / ${detail.candidates.length}</span><button disabled=${saving||index>=detail.candidates.length-1} onClick=${()=>chooseCandidate(detail.candidates[index+1].annotation_id)}>下一篇</button></div></div><div class="candidate-picker" aria-label="候选论文列表">${detail.candidates.map((c,i)=>html`<button class=${(c.annotation_id===candidate?'selected ':'')+(c.valid_submission?'done':'')} aria-label=${'候选 '+(i+1)+' · '+(c.valid_submission?'已提交':statuses[c.record.value?.status]||'待判断')} onClick=${()=>chooseCandidate(c.annotation_id)}>${String(i+1).padStart(2,'0')}<span>${c.valid_submission?'✓':c.record.value?.status==='draft'?'·':c.record.value?.status==='skipped'?'?':''}</span></button>`)}</div>
        <div class="judgment-grid"><article class="original-paper"><span class="overline">ORIGINAL ABSTRACT · v1</span><h2>${selected.paper.title}</h2><${Source} paper=${selected.paper}/><div class="abstract-title">原始摘要</div><p class="abstract">${selected.paper.abstract}</p><div class="source-footnote">标题和摘要已经与缓存的官方原始 v1 响应核对。请判断它是否满足上方需求；来源核验本身不代表相关。</div></article><section class="editor-card"><div class="editor-heading"><h3>相关性判断</h3><span>${dirty?'未保存修改':selected.valid_submission?'已提交 · 版本 '+record.revision:record.revision?'已保存 · 版本 '+record.revision:'尚未保存'}</span></div>${record.value?.status==='submitted'&&!selected.valid_submission&&html`<div class="subtle-warning">需求确认版本已变化，请重新核对后提交。</div>`}<${Editor} key=${qid+':'+candidate+':'+record.revision+':'+reloadKey} kind="judgment" value=${initial} editorRef=${editor} onChange=${setDirty}/><${Declaration} checked=${attest} onChange=${setAttest}/><div class="form-buttons"><button disabled=${saving} onClick=${()=>save('draft')}>保存草稿</button><button disabled=${saving} onClick=${()=>save('skip')}>无法判断，留空</button><button class="primary" disabled=${saving} onClick=${()=>save('submit')}>提交判断</button></div><${RecordTools} record=${record} dirty=${dirty} saving=${saving} restore=${restoreSaved} history=${showHistory}/></section></div></div>`}
      ${history&&html`<section class="history-panel"><header><h3>修订记录</h3><button onClick=${()=>setHistory(null)}>收起</button></header>${history.length?history.map(e=>html`<article><strong>版本 ${e.revision} · ${statuses[e.value.status]}</strong><time>${new Date(e.updated).toLocaleString('zh-CN',{timeZone:'Asia/Hong_Kong'})}</time><p>${e.value.note||e.value.rationale||'空白草稿'}</p><small>${e.value.reviewer||'未填写判断者'} · ${e.value.origin==='automation_test'?'自动化验收记录':e.value.origin==='human'?'已声明真人来源':'未提交草稿'}${e.value.grade!=null?' · 等级 '+e.value.grade:''}</small></article>`):html`<p>还没有保存记录。</p>`}</section>`}
      <footer class="label-foot">仅本机保存 · 26 条本轮材料 · 未标注不等于不相关 · 仅完整真人池内查询可计质量</footer>`:html`<div class="loading">正在读取需求与盲标材料…</div>`}</main></div></div>`;
}
function Declaration({checked,onChange}){return html`<label class="source-declaration"><input type="checkbox" checked=${checked} onChange=${e=>onChange(e.currentTarget.checked)}/><span>${verification?'我正在验证界面；这些记录只作为自动化测试保存。':'我本人已阅读需求或原摘要，确认以真人来源提交本次结论。'}<small>保存草稿不需要声明；提交结论或等级时必须勾选。</small></span></label>`;}
function RecordTools({record,dirty,saving,restore,history}){return html`<div class="record-tools"><button disabled=${saving} onClick=${history}>查看修订记录</button>${dirty&&html`<button disabled=${saving} onClick=${restore}>放弃未保存修改</button>`}<span>${record?.updated?'保存于 '+new Date(record.updated).toLocaleString('zh-CN',{timeZone:'Asia/Hong_Kong'}):'未保存的输入仅在当前页面'}</span></div>`;}
render(html`<${App}/>`,document.getElementById('app'));
