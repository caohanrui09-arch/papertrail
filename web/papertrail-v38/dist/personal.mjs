import {h} from 'preact';
import {useState,useEffect,useRef,useMemo} from 'preact/hooks';
import htm from 'htm';
const html=htm.bind(h);
async function request(path,body,signal){
 const response=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal});
 const value=await response.json();
 if(!response.ok){const error=Error(typeof value.detail==='string'?value.detail:`请求失败（${response.status}）`);error.status=response.status;throw error;}
 return value;
}
function listResult(profile,kind){
 if(!profile)return null;
 const preference=kind==='saved'?'like':'hide';
 const papers=profile.items.filter(p=>p.preference===preference).map((p,i)=>({...p,rank:i+1,review:null}));
 return {papers,query:kind==='saved'?'我的收藏':'不感兴趣管理',history:[],review_applies:false,profile_revision:profile.revision,
  message:kind==='saved'?'你的真实收藏。取消收藏后可从最近操作撤销。':'这些论文不进入个人推荐，仍可通过搜索找到原文。',
  trace:[{tool:'个人偏好读取',profile_revision:profile.revision,preference,count:papers.length,catalog_key:profile.catalog_key}]};
}
export function usePersonalSpace(){
 const [profile,setProfile]=useState(null),[recommendation,setRecommendation]=useState(null),[loading,setLoading]=useState(true),[recLoading,setRecLoading]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[undo,setUndo]=useState(null);
 const currentRevision=useRef(-1),recSequence=useRef(0),recAbort=useRef(null);
 function accept(next){currentRevision.current=next.revision;setProfile(next);}
 async function loadRecommendations(revision){
  const sequence=++recSequence.current;recAbort.current?.abort();const controller=new AbortController();recAbort.current=controller;
  setRecLoading(true);setRecommendation(null);
  try{const next=await request('/api/recommendations',null,controller.signal);if(sequence!==recSequence.current)return;if(next.profile_revision!==currentRevision.current||next.profile_revision!==revision)throw Error('偏好已在其他页面变化，请刷新偏好。');setRecommendation(next);}
  catch(e){if(sequence===recSequence.current&&e.name!=='AbortError')setError(e.message);}
  finally{if(sequence===recSequence.current)setRecLoading(false);}
 }
 async function reload(){setLoading(true);setError('');setMessage('');try{const next=await request('/api/profile');accept(next);setUndo(null);await loadRecommendations(next.revision);}catch(e){setError(e.message);}finally{setLoading(false);}}
 useEffect(()=>{reload();return()=>{recSequence.current++;recAbort.current?.abort();};},[]);
 async function change(paper,value,undoing=false){
  if(!profile||busy)return;setBusy(true);setError('');
  try{const next=await request('/api/profile/feedback',{doc_id:paper.doc_id,version_key:paper.version_key,catalog_key:profile.catalog_key,value,revision:currentRevision.current});accept(next);
   setUndo(undoing?null:{paper,value:next.change.previous_value,revision:next.revision});
   setMessage(undoing?'已撤销上一项偏好操作。':value==='like'?'已收藏。':value==='hide'?'已标记不感兴趣，个人推荐会排除此论文。':'已移除这项偏好。');
   await loadRecommendations(next.revision);
  }catch(e){if(e.status===409){await reload();setError(e.message+'；已刷新偏好，请重试。');}else setError(e.message);}
  finally{setBusy(false);}
 }
 async function undoLast(){if(!undo)return;if(undo.revision!==currentRevision.current){setUndo(null);setError('偏好已有后续变化，请在管理页修改。');return;}await change(undo.paper,undo.value,true);}
 async function reset(){if(!profile||busy)return;setBusy(true);setError('');try{const next=await request('/api/profile/reset',{catalog_key:profile.catalog_key,revision:currentRevision.current});accept(next);setUndo(null);setMessage('当前目录的偏好已重置。');await loadRecommendations(next.revision);}catch(e){if(e.status===409)await reload();setError(e.message);}finally{setBusy(false);}}
 const saved=useMemo(()=>listResult(profile,'saved'),[profile]),hidden=useMemo(()=>listResult(profile,'hidden'),[profile]);
 return {profile,recommendation,loading,recLoading,busy,error,message,undo,saved,hidden,reload,change,undoLast,reset,
  value(doc){return profile?.items.find(p=>p.doc_id===doc)?.preference||'none';}};
}
export function PreferenceButtons({paper,space}){
 const value=space.value(paper.doc_id),disabled=space.busy||!space.profile;
 return html`<div class="paper-preferences" role="group" aria-label=${'偏好：'+paper.title}><button class=${value==='like'?'pref-like on':'pref-like'} aria-pressed=${value==='like'} disabled=${disabled} onClick=${()=>space.change(paper,value==='like'?'none':'like')}><span aria-hidden="true">${value==='like'?'♥':'♡'}</span>${value==='like'?'已收藏':'收藏'}</button><button class=${value==='hide'?'pref-hide on':'pref-hide'} aria-pressed=${value==='hide'} disabled=${disabled} onClick=${()=>space.change(paper,value==='hide'?'none':'hide')}><span aria-hidden="true">⊘</span>${value==='hide'?'取消屏蔽':'不感兴趣'}</button></div>`;
}
export function PersonalNotice({space}){
 if(!space.error&&!space.message&&!space.loading)return null;
 return html`<div class=${'personal-notice'+(space.error?' failure':'')} role=${space.error?'alert':'status'}><span>${space.error|| (space.loading?'正在读取当前浏览器偏好…':space.message)}${space.recLoading?' 正在更新推荐…':''}</span>${space.undo&&!space.error&&html`<button disabled=${space.busy} onClick=${space.undoLast}>撤销上次操作</button>`}${space.error&&html`<button disabled=${space.busy} onClick=${space.reload}>刷新偏好</button>`}</div>`;
}
export function PersonalToolbar({mode,space,onChoose,onReset,onBackup}){return html`<div class="personal-toolbar"><div class="profile-tabs"><button class=${mode==='saved'?'active':''} aria-pressed=${mode==='saved'} onClick=${()=>onChoose('saved')}>我的收藏 <b>${space.profile?.like_count??'—'}</b></button><button class=${mode==='hidden'?'active':''} aria-pressed=${mode==='hidden'} onClick=${()=>onChoose('hidden')}>不感兴趣 <b>${space.profile?.hidden_count??'—'}</b></button></div><div class="profile-actions"><button disabled=${space.busy||space.loading} onClick=${onBackup}>收藏备份</button><button disabled=${space.busy||space.loading} onClick=${space.reload}>刷新偏好</button><button class="reset-preferences" disabled=${space.busy||!space.profile?.items.length} onClick=${onReset}>重置偏好</button></div><p>${mode==='recommend'?'内容推荐只用你的有效收藏，排除已反馈论文。':'偏好保存在当前浏览器空间；搜索仍可找到被屏蔽的论文。'}</p></div>`;}
export function RecommendationExplanation({explanation,onRead}){
 if(!explanation)return null;
 return html`<div class="recommendation-explanation"><span class="explanation-label">推荐依据</span>${explanation.anchors.length?html`<p>与你收藏的这些论文有词项重合：</p>${explanation.anchors.map(p=>html`<button class="anchor-paper" onClick=${()=>onRead(p.doc_id)}>${p.title}<span>↗</span></button>`)}`:html`<p>当前没有正分收藏贡献项。</p>`}<div class="matching-terms">${explanation.terms.map(t=>html`<span>${t.term}</span>`)}</div><details><summary>查看计算依据</summary><dl><dt>内容余弦得分</dt><dd>${explanation.cosine.toFixed(6)}</dd><dt>全部词项贡献合计</dt><dd>${explanation.all_term_contribution_sum.toFixed(6)}</dd><dt>全部收藏贡献合计</dt><dd>${explanation.all_anchor_contribution_sum.toFixed(6)}</dd><dt>偏好修订号</dt><dd>${explanation.profile_revision}</dd></dl><p>上方只展示部分高贡献项；词项相近不代表语义相关性已获验证。</p>${explanation.anchors.map(p=>html`<div class="contribution-row"><span>${p.version_key}</span><span>贡献 ${p.score_contribution.toFixed(6)}</span></div>`)}</details></div>`;
}
export function ResetPreferencesDialog({open,onClose,onConfirm,space}){
 const ref=useRef(null);
 useEffect(()=>{if(open)ref.current?.showModal();else if(ref.current?.open)ref.current.close();},[open]);
 return html`<dialog ref=${ref} class="about-dialog reset-dialog" onCancel=${onClose} aria-labelledby="reset-title"><h2 id="reset-title">重置当前目录的偏好？</h2><p>将清空 ${space.profile?.like_count||0} 篇收藏和 ${space.profile?.hidden_count||0} 篇不感兴趣标记。此操作不改动论文、旧目录画像或实验数据。</p><div class="reset-actions"><button onClick=${onClose}>取消</button><button class="confirm-reset" disabled=${space.busy} onClick=${onConfirm}>确认重置</button></div></dialog>`;
}
