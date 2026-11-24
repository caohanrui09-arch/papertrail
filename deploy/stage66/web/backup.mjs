import {h} from 'preact';
import {useEffect,useRef,useState} from 'preact/hooks';
import htm from 'htm';
const html=htm.bind(h);
const labels={like:'收藏',hide:'不感兴趣',none:'未设置',to_read:'待读',reading:'在读',read:'已读'};
const statuses={added:'新增',changed:'覆盖冲突',unchanged:'相同，保留',skipped:'冲突，保留当前'};
async function send(path,body){
 const r=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const result=await r.json();if(!r.ok){const e=Error(typeof result.detail==='string'?result.detail:`请求失败（${r.status}）`);e.status=r.status;throw e;}return result;
}
export function BackupDialog({open,onClose,space,readingLog,notebook}){
 const dialog=useRef(null),sequence=useRef(0);
 const [text,setText]=useState(''),[filename,setFilename]=useState(''),[policy,setPolicy]=useState('keep_current'),[preview,setPreview]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[done,setDone]=useState('');
 useEffect(()=>{if(open){sequence.current++;setText('');setFilename('');setPreview(null);setPolicy('keep_current');setError('');setDone('');dialog.current?.showModal();}else if(dialog.current?.open)dialog.current.close();},[open]);
 function invalidate(){sequence.current++;setPreview(null);setError('');setDone('');}
 async function chooseFile(e){const file=e.target.files?.[0];invalidate();setText('');setFilename(file?.name||'');e.target.value='';if(!file)return;if(file.size>256*1024){setError('文件不能超过 256 KiB，请选择本站导出的 JSON 备份。');return;}const n=sequence.current;try{const value=await file.text();if(n===sequence.current)setText(value);}catch{if(n===sequence.current)setError('无法读取文件，请重新选择。');}}
 async function makePreview(){if(busy||!space.profile||!readingLog.data||!notebook.data)return;setBusy(true);setError('');setPreview(null);setDone('');const n=++sequence.current;
  try{const p=await send('/api/profile/notebook/import/preview',{text,policy,revision:space.profile.revision,reading_revision:readingLog.data.revision,notes_revision:notebook.data.revision});if(n===sequence.current)setPreview(p);}
  catch(e){if(n===sequence.current){setError(e.message);if(e.status===409)await Promise.all([space.reload(),readingLog.reload(),notebook.reload()]);}}
  finally{setBusy(false);}
 }
 async function apply(){if(busy||!preview)return;setBusy(true);setError('');
  try{const result=await send('/api/profile/notebook/import/apply',{text,policy,revision:preview.revision,reading_revision:preview.reading_revision,notes_revision:preview.notes_revision,preview_token:preview.preview_token});setPreview(null);setDone(`已导入 ${result.applied} 项偏好、${result.reading_applied} 项阅读状态、${result.notes_applied} 篇笔记。备份之外的记录已保留。`);await Promise.all([space.reload(),readingLog.reload(),notebook.reload()]);}
  catch(e){setPreview(null);setError(e.message);if(e.status===409)await Promise.all([space.reload(),readingLog.reload(),notebook.reload()]);}
  finally{setBusy(false);}
 }
 function close(e){if(busy){e?.preventDefault();return;}sequence.current++;onClose();}
 const stale=preview&&(preview.revision!==space.profile?.revision||preview.reading_revision!==readingLog.data?.revision||preview.notes_revision!==notebook.data?.revision);
 return html`<dialog ref=${dialog} class="backup-dialog" aria-labelledby="backup-title" onCancel=${close}>
 <div class="backup-heading"><div><span class="eyebrow">YOUR PAPER TRAIL, TO KEEP</span><h2 id="backup-title">备份你的阅读清单</h2></div><button class="backup-close" aria-label="关闭备份" disabled=${busy} onClick=${close}>×</button></div>
 <p class="backup-intro">收藏、阅读状态和你的笔记一起保存。兼容v1偏好、v2清单备份。</p>
 <section class="backup-export"><div><span class="backup-step">01 / 保存一份</span><h3>导出收藏、清单与笔记</h3><p>${space.profile?.like_count??0} 篇收藏 · ${space.profile?.hidden_count??0} 篇不感兴趣 · ${readingLog.data?.items.length??0} 篇阅读记录 · ${notebook.data?.items.length??0} 篇笔记</p></div><a href="/api/profile/notebook/export" download="papertrail-library-v3.json" aria-disabled=${busy||!space.profile||!readingLog.data||!notebook.data} onClick=${e=>{if(busy||!space.profile||!readingLog.data||!notebook.data)e.preventDefault();}}>导出备份 <span aria-hidden="true">↓</span></a></section>
 <section class="backup-import"><span class="backup-step">02 / 恢复或合并</span><h3>导入备份</h3><p>先核对每项变化，再确认保存。备份之外的当前收藏、阅读状态和笔记始终保留。</p>
 <label class="backup-file">选择 JSON 备份文件<input type="file" accept=".json,application/json" aria-label="选择备份文件" disabled=${busy} onChange=${chooseFile}/></label>${filename&&html`<p class="backup-filename">${filename}</p>`}
 <details class="backup-paste"><summary>或粘贴备份 JSON</summary><textarea aria-label="备份 JSON 内容" value=${text} disabled=${busy} spellcheck="false" placeholder="粘贴从本站导出的备份内容" onInput=${e=>{invalidate();setFilename('粘贴的备份');setText(e.target.value);}}/></details>
 <label class="backup-policy">同一论文的偏好、状态或笔记冲突时<select value=${policy} disabled=${busy} onChange=${e=>{invalidate();setPolicy(e.target.value);}}><option value="keep_current">保留当前记录（默认）</option><option value="use_backup">使用备份中的记录</option></select></label>
 <button class="backup-preview-button" disabled=${busy||!text.trim()||!space.profile||!readingLog.data||!notebook.data||space.busy||readingLog.busy||notebook.busy} onClick=${makePreview}>${busy?'正在处理…':'校验并预览'}</button>
 ${error&&html`<p class="backup-error" role="alert">${error}</p>`}${done&&html`<p class="backup-success" role="status">${done}</p>`}
 ${preview&&html`<section class="backup-plan" aria-label="导入预览"><div class="backup-plan-heading"><h3>确认这些变化</h3><span>尚未保存</span></div>${preview.migrated_from&&html`<p class="backup-migration">这是旧 42 篇目录的备份；论文 ID、v1 版本、标题和来源已逐项核验。确认后迁入当前目录，其他偏好继续保留。</p>`}<h4>收藏与不感兴趣</h4><p>新增 ${preview.counts.added} · 覆盖 ${preview.counts.changed} · 冲突 ${preview.counts.conflicts} · 相同 ${preview.counts.unchanged} · 跳过 ${preview.counts.skipped}</p><p>另保留 ${preview.retained_outside_backup} 项现有偏好，合并后共 ${preview.total_after} 项。</p>
 <ul>${preview.rows.map(p=>html`<li key=${p.doc_id} class=${p.conflict?'has-conflict':''}><strong>${p.title}</strong><code>${p.version_key}</code><div><span>当前：${labels[p.current]}</span><span>备份：${labels[p.preference]}</span><b>${statuses[p.status]} → ${labels[p.result]}</b></div></li>`)}</ul>
 ${!preview.rows.length&&html`<p>备份没有偏好项，当前偏好不会清空。</p>`}<h4>阅读状态</h4>${preview.file_version===1&&html`<p>这是v1偏好备份，不包含阅读状态；当前阅读清单保持不变。</p>`}<p>新增 ${preview.reading.counts.added} · 覆盖 ${preview.reading.counts.changed} · 冲突 ${preview.reading.counts.conflicts} · 相同 ${preview.reading.counts.unchanged} · 跳过 ${preview.reading.counts.skipped}</p><p>另保留 ${preview.reading.retained_outside_backup} 篇阅读记录，合并后共 ${preview.reading.total_after} 篇。</p><ul>${preview.reading.rows.map(p=>html`<li key=${p.doc_id} class=${p.conflict?'has-conflict':''}><strong>${p.title}</strong><code>${p.version_key}</code><div><span>当前：${labels[p.current]}</span><span>备份：${labels[p.state]}</span><b>${statuses[p.status]} → ${labels[p.result]}</b></div></li>`)}</ul><h4>阅读笔记</h4>${preview.file_version<3&&html`<p>v${preview.file_version}备份不含笔记；当前笔记保持不变。</p>`}<p>新增 ${preview.notes.counts.added} · 覆盖 ${preview.notes.counts.changed} · 冲突 ${preview.notes.counts.conflicts} · 相同 ${preview.notes.counts.unchanged} · 跳过 ${preview.notes.counts.skipped}</p><p>另保留 ${preview.notes.retained_outside_backup} 篇笔记，合并后共 ${preview.notes.total_after} 篇。</p><ul>${preview.notes.rows.map(p=>html`<li key=${p.doc_id} class=${p.conflict?'has-conflict':''}><strong>${p.title}</strong><code>${p.version_key}</code><b>${statuses[p.status]}</b><details><summary>查看笔记内容与变化</summary><p class="backup-note-text">当前问题：${p.current==='none'?'无笔记':p.current.problem}</p><p class="backup-note-text">当前疑问：${p.current==='none'?'无笔记':p.current.questions}</p><p class="backup-note-text">备份问题：${p.problem}</p><p class="backup-note-text">备份疑问：${p.questions}</p><p>结果：${p.status==='skipped'?'保留当前笔记':'采用备份笔记'}</p></details></li>`)}</ul>${stale&&html`<p role="alert">收藏、阅读清单或笔记已变化，请重新预览。</p>`}
 <button class="backup-confirm" disabled=${busy||stale||!preview.changes_total} onClick=${apply}>确认导入 ${preview.changes_total} 项变化</button>
 </section>`}</section><p class="backup-footnote">备份含你的笔记内容、偏好、阅读状态和论文标识，请自行保管；不含浏览器凭据或查询。v3/v2支持当前目录，v1兼容经核验的旧42篇目录；文件限制 256 KiB。导入由当前服务校验，不读取外部链接。</p>
 </dialog>`;
}
