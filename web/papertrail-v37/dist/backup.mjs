import {h} from 'preact';
import {useEffect,useRef,useState} from 'preact/hooks';
import htm from 'htm';
const html=htm.bind(h);
const labels={like:'收藏',hide:'不感兴趣',none:'无偏好'};
const statuses={added:'新增',changed:'覆盖冲突',unchanged:'相同，保留',skipped:'冲突，保留当前'};
async function send(path,body){
 const r=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const result=await r.json();if(!r.ok){const e=Error(typeof result.detail==='string'?result.detail:`请求失败（${r.status}）`);e.status=r.status;throw e;}return result;
}
export function BackupDialog({open,onClose,space}){
 const dialog=useRef(null),sequence=useRef(0);
 const [text,setText]=useState(''),[filename,setFilename]=useState(''),[policy,setPolicy]=useState('keep_current'),[preview,setPreview]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[done,setDone]=useState('');
 useEffect(()=>{if(open){sequence.current++;setText('');setFilename('');setPreview(null);setPolicy('keep_current');setError('');setDone('');dialog.current?.showModal();}else if(dialog.current?.open)dialog.current.close();},[open]);
 function invalidate(){sequence.current++;setPreview(null);setError('');setDone('');}
 async function chooseFile(e){const file=e.target.files?.[0];invalidate();setText('');setFilename(file?.name||'');e.target.value='';if(!file)return;if(file.size>256*1024){setError('文件不能超过 256 KiB，请选择本站导出的 JSON 备份。');return;}const n=sequence.current;try{const value=await file.text();if(n===sequence.current)setText(value);}catch{if(n===sequence.current)setError('无法读取文件，请重新选择。');}}
 async function makePreview(){if(busy||!space.profile)return;setBusy(true);setError('');setPreview(null);setDone('');const n=++sequence.current;
  try{const p=await send('/api/profile/import/preview',{text,policy,revision:space.profile.revision});if(n===sequence.current)setPreview(p);}
  catch(e){if(n===sequence.current){setError(e.message);if(e.status===409)await space.reload();}}
  finally{setBusy(false);}
 }
 async function apply(){if(busy||!preview)return;setBusy(true);setError('');
  try{const result=await send('/api/profile/import/apply',{text,policy,revision:preview.revision,preview_token:preview.preview_token});setPreview(null);setDone(`已导入 ${result.applied} 项偏好。其余当前偏好已保留，个人推荐已刷新。`);await space.reload();}
  catch(e){setPreview(null);setError(e.message);if(e.status===409)await space.reload();}
  finally{setBusy(false);}
 }
 function close(e){if(busy){e?.preventDefault();return;}sequence.current++;onClose();}
 const stale=preview&&preview.revision!==space.profile?.revision;
 return html`<dialog ref=${dialog} class="backup-dialog" aria-labelledby="backup-title" onCancel=${close}>
 <div class="backup-heading"><div><span class="eyebrow">YOUR PAPER TRAIL, TO KEEP</span><h2 id="backup-title">备份你的兴趣</h2></div><button class="backup-close" aria-label="关闭备份" disabled=${busy} onClick=${close}>×</button></div>
 <p class="backup-intro">收藏与不感兴趣一起保存。换浏览器后，可在相同目录中恢复。</p>
 <section class="backup-export"><div><span class="backup-step">01 / 保存一份</span><h3>导出当前偏好</h3><p>${space.profile?.like_count??0} 篇收藏 · ${space.profile?.hidden_count??0} 篇不感兴趣</p></div><a href="/api/profile/export" download="papertrail-preferences-v1.json" aria-disabled=${busy||!space.profile} onClick=${e=>{if(busy||!space.profile)e.preventDefault();}}>导出备份 <span aria-hidden="true">↓</span></a></section>
 <section class="backup-import"><span class="backup-step">02 / 恢复或合并</span><h3>导入备份</h3><p>先核对每项变化，再确认保存。备份之外的当前偏好始终保留。</p>
 <label class="backup-file">选择 JSON 备份文件<input type="file" accept=".json,application/json" aria-label="选择备份文件" disabled=${busy} onChange=${chooseFile}/></label>${filename&&html`<p class="backup-filename">${filename}</p>`}
 <details class="backup-paste"><summary>或粘贴备份 JSON</summary><textarea aria-label="备份 JSON 内容" value=${text} disabled=${busy} spellcheck="false" placeholder="粘贴从本站导出的备份内容" onInput=${e=>{invalidate();setFilename('粘贴的备份');setText(e.target.value);}}/></details>
 <label class="backup-policy">同一论文的偏好冲突时<select value=${policy} disabled=${busy} onChange=${e=>{invalidate();setPolicy(e.target.value);}}><option value="keep_current">保留当前偏好（默认）</option><option value="use_backup">使用备份中的偏好</option></select></label>
 <button class="backup-preview-button" disabled=${busy||!text.trim()||!space.profile||space.busy} onClick=${makePreview}>${busy?'正在处理…':'校验并预览'}</button>
 ${error&&html`<p class="backup-error" role="alert">${error}</p>`}${done&&html`<p class="backup-success" role="status">${done}</p>`}
 ${preview&&html`<section class="backup-plan" aria-label="导入预览"><div class="backup-plan-heading"><h3>确认这些变化</h3><span>尚未保存</span></div><p>新增 ${preview.counts.added} · 覆盖 ${preview.counts.changed} · 冲突 ${preview.counts.conflicts} · 相同 ${preview.counts.unchanged} · 跳过 ${preview.counts.skipped}</p><p>另保留 ${preview.retained_outside_backup} 项现有偏好，合并后共 ${preview.total_after} 项。</p>
 <ul>${preview.rows.map(p=>html`<li key=${p.doc_id} class=${p.conflict?'has-conflict':''}><strong>${p.title}</strong><code>${p.version_key}</code><div><span>当前：${labels[p.current]}</span><span>备份：${labels[p.preference]}</span><b>${statuses[p.status]} → ${labels[p.result]}</b></div></li>`)}</ul>
 ${!preview.rows.length&&html`<p>这是空备份，当前偏好不会清空。</p>`}${stale&&html`<p role="alert">偏好已变化，请重新预览。</p>`}
 <button class="backup-confirm" disabled=${busy||stale||!(preview.counts.added+preview.counts.changed)} onClick=${apply}>确认导入 ${preview.counts.added+preview.counts.changed} 项变化</button>
 </section>`}</section><p class="backup-footnote">备份仅含偏好及论文标识，不含浏览器凭据。仅支持相同目录和论文版本；文件限制 256 KiB。导入会在本机校验，不读取外部链接。</p>
 </dialog>`;
}
