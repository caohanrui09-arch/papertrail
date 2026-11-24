/* Existing JSONEditor form engine + native Web Storage / Blob export.
   No analytics, model calls or relevance judgments are sent to a server. */
(() => {
 'use strict';
 const verification=new URLSearchParams(location.search).get('verification')==='1',origin=verification?'automation_test':'human_self_report',key='papertrail.usability.v76.'+origin;
 const tasks=[
  {id:'find-paper',title:'找到一篇论文并读摘要',goal:'搜索生成式检索相关论文，选择一篇并打开摘要。记录标题或ID，以及你如何做出选择。',href:'/',done:'在右侧阅读到所选论文原摘要。'},
  {id:'check-source',title:'核对版本与来源',goal:'为刚读的论文找到论文ID、版本和原始来源链接。把ID、版本和核对方法写入反馈。',href:'/',done:'能说明本地摘要对应哪个版本及来源。'},
  {id:'handoff',title:'把需求交给 Agent',goal:'在工作台填写需求和检索词，使用“交给Agent”。检查带入内容、目标画像及目录截止时间；到确认页面即可，不必执行模型。',href:'/',done:'能确认原问题是否保留，以及本次将使用的画像和时点。'},
  {id:'trace-citation',title:'沿引用找到实际读取',goal:'在实验台载入“固定组合流程·已提交”历史记录，找到一条引用对应的读取调用。说明这是实时模型执行还是历史回放，以及你如何判断。',href:'http://127.0.0.1:8802/',done:'定位对应read_paper、版本和逐字摘录；明确记录类型。'},
  {id:'export-task',title:'带走一次任务记录',goal:'在同一历史任务中生成并下载Markdown和JSON报告，打开文件并确认包含论文来源与成本。记录是否找到导出入口。',href:'http://127.0.0.1:8802/',done:'两种文件能打开，并能找到来源和成本。'}
 ];
 const protocol={id:'papertrail-usability-v76-5tasks',version:76,tasks,scope:'local-desktop-self-reported-usability-only',timing:'wall clock per attempt, including thinking and page switching; client clock unverified',not_relevance_labels:true};
 const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n};
 const labels={complete:'完成',partial:'部分完成',blocked:'卡住未完成',skipped:'跳过'};
 const blank=()=>({outcome:'',assistance:'',proof:'',obstacle:''});let editor=null,editorReady=false,suppress=false,saveTimer=null,storageError=false,protocolHash='',state={version:76,origin,sessions:[],active_id:null};
 const active=()=>state.sessions.find(s=>s.id===state.active_id),currentTask=()=>active()?.active_task;
 function status(s){$('trial-status').textContent=s}
 function persist(){try{localStorage.setItem(key,JSON.stringify(state));return true}catch{status('本浏览器存储不可用；记录仍在当前页面，请先导出，刷新可能丢失。');return false}}
 function seconds(start){const d=(Date.now()-Date.parse(start))/1000;return Number.isFinite(d)&&d>=0&&d<=10800?d:null}
 function button(text,fn,disabled=false){const b=el('button',text);b.type='button';b.disabled=disabled;b.onclick=fn;return b}
 function setForm(value){if(!editorReady)return;suppress=true;editor.setValue(value||blank());suppress=false}
 function syncSetup(){$('start-trial').disabled=storageError||!editorReady||!$('participant-code').value.trim()||!$('trial-consent').checked}
 function saveDraft(){if(suppress||!currentTask())return;currentTask().draft=editor.getValue();clearTimeout(saveTimer);saveTimer=setTimeout(persist,250)}
 function setupEditor(){const properties={outcome:{type:'string',title:'这次尝试的结果',enum:['','complete','partial','blocked','skipped'],options:{enum_titles:['请选择','完成','部分完成','卡住未完成','跳过']}},assistance:{type:'string',title:'是否需要帮助',enum:['','none','hint','guided'],options:{enum_titles:['请选择','独立完成/尝试','得到提示','有人带着操作']}},proof:{type:'string',format:'textarea',title:'操作证据或实际到达的位置（完成时必填）',maxLength:1200},obstacle:{type:'string',format:'textarea',title:'哪里不清楚、卡在哪一步；未遇到可留空',maxLength:2000}};
  editor=new window.JSONEditor($('trial-editor'),{schema:{type:'object',title:'本次尝试反馈',properties,required:Object.keys(properties),additionalProperties:false},startval:blank(),theme:'html',disable_theme_rules:true,disable_collapse:true,disable_edit_json:true,disable_properties:true,no_additional_properties:true,show_errors:'never',use_default_values:true});editor.on('change',saveDraft);
 }
 function startSession(){if(storageError)return;const code=$('participant-code').value.trim();if(!code||code.length>32||/[\u0000-\u001f]/.test(code)||!$('trial-consent').checked){status('填写参与者代号并确认本地保存后再开始。');return}if(state.sessions.length>=20){status('本浏览器已保存20次试用，请先导出；不会静默覆盖旧记录。');return}
  const previous=active();if(previous&&previous.status==='in_progress')previous.status='incomplete_archived';const session={id:crypto.randomUUID(),participant_code:code,origin,created_at:new Date().toISOString(),consented:true,protocol_sha256:protocolHash,status:'in_progress',attempts:[],active_task:null};state.sessions.push(session);state.active_id=session.id;persist();render();status('试用已开始。选择任务，再点击开始计时；历史记录会保留。');
 }
 function beginTask(task){if(!active()||currentTask())return;if(active().attempts.length>=50){status('本次已有50次尝试，请先导出，再新建试用；旧尝试不会覆盖。');return}active().status='in_progress';delete active().finished_at;active().active_task={id:crypto.randomUUID(),task_id:task.id,started_at:new Date().toISOString(),draft:blank()};persist();setForm(blank());render();status('已为“'+task.title+'”开始墙钟计时。可点击任务卡中的链接在另一个标签操作。')}
 function saveAttempt(){const s=active(),running=currentTask();if(!s||!running)return;const v=editor.getValue();if(!['complete','partial','blocked','skipped'].includes(v.outcome)||!['none','hint','guided'].includes(v.assistance)){status('请选择结果与帮助情况。');return}if(typeof v.proof!=='string'||typeof v.obstacle!=='string'||v.proof.length>1200||v.obstacle.length>2000||(v.outcome==='complete'&&!v.proof.trim())){status('完成时请填写实际操作证据；不要填联系方式，文本也需符合长度限制。');return}
  const elapsed=seconds(running.started_at);s.attempts.push({id:running.id,task_id:running.task_id,started_at:running.started_at,finished_at:new Date().toISOString(),elapsed_seconds:elapsed,duration_valid:elapsed!==null,clock_source:'client_wall_clock_not_verified',...Object.fromEntries(['outcome','assistance','proof','obstacle'].map(k=>[k,v[k]]))});s.active_task=null;
  if(tasks.every(t=>s.attempts.some(a=>a.task_id===t.id))){s.status='recorded';s.finished_at=new Date().toISOString()}persist();setForm(blank());render();status('本次尝试已保存。失败、跳过和重复尝试均保留；这不是相关性标签。');
 }
 function render(){const s=active(),running=currentTask();$('trial-tasks').replaceChildren();for(const [i,t] of tasks.entries()){const card=el('article',null,'trial-task');card.dataset.taskId=t.id;const count=s?.attempts.filter(a=>a.task_id===t.id).length||0;card.append(el('span',String(i+1).padStart(2,'0'),'task-number'),el('h3',t.title),el('p',t.goal),el('p','到达标志：'+t.done,'task-done-hint'));const actions=el('div',null,'task-actions'),link=el('a','打开相关页面 ↗');link.href=t.href;link.target='_blank';link.rel='noopener noreferrer';actions.append(button(count?'追加一次尝试':'开始计时',()=>beginTask(t),!s||Boolean(running)),link,el('span',count+' 次已存记录'));card.append(actions);$('trial-tasks').append(card)}
  $('active-task-title').textContent=running?tasks.find(t=>t.id===running.task_id).title:'选择一个任务并开始计时。';$('save-trial-task').disabled=!running;if(editorReady)editor[running?'enable':'disable']();
  const complete=s?.attempts.filter(a=>a.outcome==='complete').length||0,covered=s?new Set(s.attempts.map(a=>a.task_id)).size:0;$('trial-summary').textContent=s?`${s.participant_code} · ${covered}/5 项已有尝试记录 · 参与者填写“完成”${complete}次 · 总尝试${s.attempts.length}次。`:'还没有当前试用记录。';
  $('trial-history').replaceChildren();for(const a of s?.attempts||[]){const d=el('details'),title=tasks.find(t=>t.id===a.task_id).title;d.append(el('summary',title+' · '+labels[a.outcome]+' · '+(a.elapsed_seconds==null?'时长无效':a.elapsed_seconds.toFixed(1)+'秒墙钟')),el('pre',JSON.stringify(a,null,2)));$('trial-history').append(d)}
  for(const id of ['export-trial-json','export-trial-markdown'])$(id).disabled=!s;$('export-all-trials').disabled=!state.sessions.length;tick();
 }
 function tick(){const r=currentTask();if(!r){$('trial-timer').textContent='尚未计时';return}const value=seconds(r.started_at);$('trial-timer').textContent=value==null?'时钟异常或超过3小时；仍可保存尝试，时长会标记为无效。':value.toFixed(0)+' 秒 · 操作墙钟时间（离开页面也累计）'}
 function envelope(session){return {format:'papertrail_usability_trial',version:76,origin,exported_at:new Date().toISOString(),protocol,protocol_sha256:protocolHash,session,agent_usage_not_measured:true,completion_self_reported_not_verified:true,relevance_labels:[],quality_scores:null}}
 function download(filename,value,type){const url=URL.createObjectURL(new Blob([value],{type})),a=el('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 function markdown(){const s=active(),safe=x=>String(x??'').replaceAll('<','&lt;').replaceAll('>','&gt;'),lines=['# Papertrail 真实试用记录','',`来源：${origin}（参与者声明，不是身份认证）`,`代号：${safe(s.participant_code)}`,'','此记录仅用于可用性反馈，不是论文相关性标签或模型质量评价。',''];for(const a of s.attempts){lines.push('## '+tasks.find(t=>t.id===a.task_id).title,'',`结果：${a.outcome}；帮助：${a.assistance}；墙钟秒数：${a.elapsed_seconds??'无效/未记录'}`,'','操作证据：'+safe(a.proof),'','阻碍：'+safe(a.obstacle),'')}if(s.active_task)lines.push('有尚未结束的尝试，保持未完成状态。');return lines.join('\n')}
 async function init(){
  $('trial-source').textContent=verification?'自动验收空间 · 所有记录固定标记 automation_test，不计入真人试用。':'真实试用准备 · 尚无真人结论。记录来源由参与者声明，完成情况不作独立核验。';$('trial-source').classList.toggle('verification',verification);
  protocolHash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(protocol))))].map(b=>b.toString(16).padStart(2,'0')).join('');
  try{const raw=localStorage.getItem(key);if(raw){const saved=JSON.parse(raw);if(saved.version!==76||saved.origin!==origin||!Array.isArray(saved.sessions)||saved.sessions.length>20||saved.sessions.some(s=>s.protocol_sha256!==protocolHash))throw Error('版本或协议不一致');state=saved}}catch(e){storageError=true;status('旧本地记录无法读取，未覆盖。请先保留浏览器中的原记录：'+e.message)}
  setupEditor();editor.on('ready',()=>{editorReady=true;setForm(currentTask()?.draft||blank());render();syncSetup()});
  $('participant-code').oninput=syncSetup;$('trial-consent').onchange=syncSetup;$('start-trial').onclick=startSession;$('save-trial-task').onclick=saveAttempt;
  $('export-trial-json').onclick=()=>download('papertrail-usability76-'+active().id+'.json',JSON.stringify(envelope(active()),null,2),'application/json;charset=utf-8');$('export-trial-markdown').onclick=()=>download('papertrail-usability76-'+active().id+'.md',markdown(),'text/markdown;charset=utf-8');$('export-all-trials').onclick=()=>download('papertrail-usability76-'+origin+'-all.json',JSON.stringify({version:76,origin,protocol,protocol_sha256:protocolHash,sessions:state.sessions,quality_scores:null},null,2),'application/json;charset=utf-8');
  render();setInterval(tick,1000);
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>init().catch(e=>status('试用页初始化失败：'+e.message)),{once:true});else init().catch(e=>status('试用页初始化失败：'+e.message));
})();
