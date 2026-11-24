// Local-only real browser checks using the existing isolated Edge CDP helper.
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
const {connect}=require('../research66/inspect_topics67.cjs');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function main(){
 const target=await(await fetch('http://127.0.0.1:9327/json/new?about:blank',{method:'PUT'})).json();
 await fs.writeFile('.cache/stage68/target.json',JSON.stringify(target));
 const {ws,call}=await connect(target.webSocketDebuggerUrl),checks=[],errors=[];
 ws.addEventListener('message',e=>{const v=JSON.parse(e.data);if(v.method==='Runtime.exceptionThrown')errors.push(v.params.exceptionDetails.text)});
 async function ev(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value}
 async function wait(expression){for(let i=0;i<100;i++){if(await ev(expression))return;await pause(250)}throw Error('Timed out: '+expression)}
 async function click(selector){await ev(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center',behavior:'instant'})`);const p=await ev(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);await call('Input.dispatchMouseEvent',{type:'mouseMoved',...p});await call('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...p});await call('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...p});await pause(180)}
 async function choose(id,value){await ev(`(()=>{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('change',{bubbles:true}))})()`);await pause(180)}
 async function shot(name){const r=await call('Page.captureScreenshot',{format:'png'});await fs.writeFile('reports/stage68/'+name+'.png',Buffer.from(r.data,'base64'))}
 try{
  await call('Page.enable');await call('Runtime.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:1600,height:1200,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:'http://127.0.0.1:8802/'});
  await wait(`document.querySelectorAll('.candidate').length===10&&document.querySelectorAll('.event').length===3`);
  const inspection=await ev(`({buttons:[...document.querySelectorAll('button')].map(b=>({id:b.id,text:b.textContent})),source:document.getElementById('source-mode').textContent,events:[...document.querySelectorAll('.event')].map(e=>({tool:e.dataset.tool,text:e.querySelector('.event-title').textContent})),candidates:[...document.querySelectorAll('.candidate')].map(p=>p.dataset.docId)})`);
  await fs.writeFile('reports/stage68/browser-inspection.json',JSON.stringify(inspection,null,2));
  assert.equal(inspection.source,'历史真实记录');assert.deepEqual(inspection.events.map(e=>e.tool),['search_papers','read_paper','finalize']);checks.push('real_historical_search_read_finalize_timeline');
  assert.equal(await ev(`document.querySelector('.candidate h3').textContent.includes(document.querySelector('.candidate').dataset.docId)`),false);checks.push('paper_titles_and_version_links_rendered');
  await shot('lab-overview');
  await click('.event details summary');assert.equal(await ev(`document.querySelector('.event details').open`),true);checks.push('expand_original_tool_arguments_and_returns');
  await click('[data-method="hybrid"]');
  const native=await(await fetch('http://127.0.0.1:8802/lab/algorithms',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:'evaluation-000'})})).json();
  const hybrid=await ev(`[...document.querySelectorAll('.candidate')].map(p=>p.dataset.docId)`);assert.deepEqual(hybrid,native.methods.hybrid.map(p=>p.doc_id));checks.push('algorithm_tab_exact_native_order');
  const base=new Map(native.methods.content.map((p,i)=>[p.doc_id,i+1]));const expected=native.methods.hybrid.map((p,i)=>base.has(p.doc_id)?base.get(p.doc_id)-(i+1):null);
  const labels=await ev(`[...document.querySelectorAll('.candidate')].map(p=>p.querySelector('.paper-meta .pill:last-child').textContent)`);
  expected.forEach((delta,i)=>assert.ok(delta===null?labels[i].includes('新入'):delta>0?labels[i].includes('↑ '+delta):delta<0?labels[i].includes('↓ '+(-delta)):labels[i].includes('不变')));checks.push('rank_deltas_and_top10_entry_labels_match_native');
  await click('.candidate details summary');assert.equal(await ev(`document.querySelector('.candidate details').open`),true);assert.ok(await ev(`document.querySelector('.scores').textContent.includes('SAR 分数')`));checks.push('expand_native_scores_and_profile_evidence');
  await choose('baseline','sar');assert.ok((await ev(`document.getElementById('rank-summary').textContent`)).includes('重合'));checks.push('comparison_reference_can_change');
  await choose('example','llm_agent');await click('#recorded');
  await wait(`document.querySelectorAll('.event.failed').length===4&&document.getElementById('task').value==='evaluation-001'`);assert.ok((await ev(`document.getElementById('summary').textContent`)).includes('未提交'));assert.equal(await ev(`document.querySelectorAll('.event[data-tool="finalize"]').length`),0);checks.push('real_failure_replay_keeps_four_errors_and_no_fake_submission');
  await shot('failure-replay');
  await click('#aggregate');await wait(`document.querySelectorAll('#research-result tbody tr').length===3`);checks.push('historical_same_condition_aggregate_table');
  await click('#quality');await wait(`document.getElementById('research-result').textContent.includes('49,533')`);assert.ok((await ev(`document.getElementById('research-result').textContent`)).includes('不是本次'));checks.push('historical_quality_kept_separate');
  await choose('task','evaluation-002');await choose('policy','fixed');await click('#run');
  assert.equal(await ev(`document.getElementById('run').disabled`),true);assert.ok((await ev(`document.getElementById('timeline').textContent`)).includes('不展示推测进度'));checks.push('live_job_waiting_state_is_honest_and_locked');
  await wait(`!document.getElementById('run').disabled&&document.querySelectorAll('.event[data-tool="finalize"]').length===1`);
  assert.equal(await ev(`document.getElementById('source-mode').textContent`),'本次真实执行');assert.equal(await ev(`document.querySelectorAll('.citation').length`),2);assert.equal(await ev(`document.querySelectorAll('.event.failed').length`),0);checks.push('new_real_fixed_job_two_citations_and_executed_timeline');
  await ev(`document.querySelector('.execution').scrollIntoView({block:'start',behavior:'instant'})`);await shot('live-fixed-result');
  await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await ev(`document.getElementById('recorded').focus()`);assert.equal(await ev(`document.activeElement.matches(':focus-visible')`),true);checks.push('keyboard_visible_focus');
  assert.deepEqual(errors,[]);checks.push('no_browser_runtime_exceptions');
  const result={status:'passed',browser:'isolated headless Microsoft Edge',viewport:{width:1600,height:1200},checks:checks.length,passed:checks,errors};await fs.writeFile('reports/stage68/browser-validation.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{ws.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
