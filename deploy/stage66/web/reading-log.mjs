import {h} from 'preact';
import {useEffect,useRef,useState} from 'preact/hooks';
import htm from 'htm';
const html=htm.bind(h);
export const READING_LABELS={none:'未加入',to_read:'待读',reading:'在读',read:'已读'};
async function request(path,body){
 const response=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
 const value=await response.json();if(!response.ok){const error=Error(typeof value.detail==='string'?value.detail:`请求失败（${response.status}）`);error.status=response.status;throw error;}return value;
}
export function useReadingLog(profile){
 const [data,setData]=useState(null),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[undo,setUndo]=useState(null);
 const current=useRef(null),locked=useRef(false),sequence=useRef(0);
 function accept(next){current.current=next;setData(next);}
 async function reload(){const n=++sequence.current;setLoading(true);setError('');setMessage('');setUndo(null);try{const next=await request('/api/profile/reading');if(n===sequence.current)accept(next);}catch(e){if(n===sequence.current)setError(e.message);}finally{if(n===sequence.current)setLoading(false);}}
 useEffect(()=>{if(profile?.catalog_key)reload();},[profile?.catalog_key]);
 useEffect(()=>{setMessage('');setUndo(null);},[profile?.revision]);
 async function change(paper,value,undoing=false){
  if(!current.current||locked.current)return;locked.current=true;setBusy(true);setError('');sequence.current++;
  try{const next=await request('/api/profile/reading/feedback',{doc_id:paper.doc_id,version_key:paper.version_key,catalog_key:current.current.catalog_key,value,revision:current.current.revision});accept(next);
   setUndo(undoing||next.change.previous_value===value?null:{paper,value:next.change.previous_value,revision:next.revision});
   setMessage(undoing?'已撤销阅读状态操作。':value==='none'?'已移出阅读清单，收藏保持不变。':`已标记${READING_LABELS[value]}。收藏和推荐画像保持不变。`);
  }catch(e){if(e.status===409){await reload();setError(e.message+'；清单已刷新，请重试。');}else setError(e.message);}
  finally{locked.current=false;setBusy(false);}
 }
 async function undoLast(){if(!undo||locked.current)return;if(undo.revision!==current.current?.revision){setUndo(null);setError('阅读清单已有后续变化，请在清单中修改。');return;}await change(undo.paper,undo.value,true);}
 function result(filter){
  if(!data)return null;
  const papers=data.items.filter(p=>filter==='all'||p.reading_state===filter).map((p,i)=>({...p,rank:i+1,review:null}));
  return {papers,query:'阅读清单',history:[],review_applies:false,message:'手动整理阅读进度；打开摘要不会自动标记已读。按最近状态更新时间排序。',trace:[{tool:'阅读清单读取',reading_revision:data.revision,filter,count:papers.length,catalog_key:data.catalog_key}]};
 }
 return {data,loading,busy,error,message,undo,reload,change,undoLast,result,
  value(doc){return data?.items.find(p=>p.doc_id===doc)?.reading_state||'none';}};
}
export function ReadingStatus({paper,log}){
 const value=log.value(paper.doc_id),disabled=log.busy||log.loading||!log.data;
 if(value==='none')return html`<button class="reading-status add-to-read" disabled=${disabled} aria-label=${'加入待读：'+paper.title} onClick=${()=>log.change(paper,'to_read')}>＋ 待读</button>`;
 return html`<select class=${'reading-status state-'+value} aria-label=${'阅读状态：'+paper.title} value=${value} disabled=${disabled} onChange=${e=>log.change(paper,e.target.value)}><option value="to_read">○ 待读</option><option value="reading">◐ 在读</option><option value="read">✓ 已读</option><option value="none">移出清单</option></select>`;
}
export function ReadingToolbar({log,notebook,filter,onFilter,onBackup}){
 const total=log.data?.items.length??0;
 return html`<div>${notebook.error&&html`<p class="note-error" role="alert">${notebook.error}<button onClick=${notebook.reload}>重新读取笔记</button></p>`}<div class="reading-list-toolbar" aria-label="阅读清单工具栏"><div class="reading-filters" role="group" aria-label="按阅读状态筛选">${['all','to_read','reading','read','noted'].map(key=>html`<button key=${key} class=${filter===key?'active':''} aria-pressed=${filter===key} onClick=${()=>onFilter(key)}>${key==='all'?'全部':key==='noted'?'有笔记':READING_LABELS[key]}<b>${key==='all'?total:key==='noted'?notebook.data?.items.length??0:log.data?.counts[key]??0}</b></button>`)}</div><div class="reading-list-actions"><button onClick=${log.reload} disabled=${log.busy||log.loading}>刷新清单</button><button onClick=${onBackup} disabled=${log.busy||log.loading}>备份清单 ↗</button></div></div></div>`;
}
