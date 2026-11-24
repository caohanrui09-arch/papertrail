const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
const {connect}=require('./inspect_topics67.cjs');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function main(){
 const target=JSON.parse(await fs.readFile('.cache/stage67/target.json','utf8'));
 const {ws,call}=await connect(target.webSocketDebuggerUrl);
 const checks=[];
 async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value}
 async function move(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'nearest',behavior:'instant'})`);const box=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);await call('Input.dispatchMouseEvent',{type:'mouseMoved',...box});await pause(700);return box}
 async function click(selector){const box=await move(selector);await call('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...box});await call('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...box});await pause(500)}
 try{
  await call('Runtime.enable');await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:1600,height:1100,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.querySelector('.collection-grid').scrollIntoView({block:'center',behavior:'instant'})`);
  await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:1,y:1});await pause(300);
  const baseline=await evaluate(`(()=>{const grid=document.querySelector('.collection-grid');return {background:getComputedStyle(document.querySelector('.studio')).backgroundColor,columns:getComputedStyle(grid).gridTemplateColumns,cards:[...grid.querySelectorAll('.collection-card')].map(c=>({background:getComputedStyle(c).backgroundColor,action:getComputedStyle(c.querySelector('.collection-action')).backgroundColor})),grid:{width:grid.getBoundingClientRect().width,height:grid.getBoundingClientRect().height}}})()`);
  for(const rgb of [baseline.background,...baseline.cards.map(c=>c.background)]){const n=rgb.match(/\d+/g);assert.equal(n[0],n[1]);assert.equal(n[1],n[2])}
  checks.push('neutral_page_and_all_three_card_surfaces');
  for(const [i,key] of ['generative','cold','bias'].entries()){
   await move(`.collection-${key} .collection-button`);
   const hover=await evaluate(`(()=>{const c=document.querySelector('.collection-${key}');return {background:getComputedStyle(c).backgroundColor,action:getComputedStyle(c.querySelector('.collection-action')).backgroundColor,graphic:getComputedStyle(c.querySelector('svg')).transform}})()`);
   assert.equal(hover.background,baseline.cards[i].background);assert.notEqual(hover.action,baseline.cards[i].action);assert.notEqual(hover.graphic,'none');checks.push(key+'_hover_feedback_without_surface_recolor');
  }
  await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:1,y:1});
  await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  await evaluate(`document.querySelector('.collection-generative .collection-button').focus()`);await pause(300);
  const focus=await evaluate(`(()=>{const b=document.activeElement;return {visible:b.matches(':focus-visible'),width:getComputedStyle(b).outlineWidth,color:getComputedStyle(b).outlineColor}})()`);
  assert.equal(focus.visible,true);assert.equal(focus.width,'3px');checks.push('keyboard_visible_focus');
  const clip=await evaluate(`(()=>{const r=document.querySelector('.collection-grid').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
  await move('.collection-cold .collection-button');
  const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip});await fs.writeFile('reports/stage67/topics-hover.png',Buffer.from(shot.data,'base64'));
  await evaluate(`document.activeElement.blur()`);
  await click('.motion-toggle');assert.equal(await evaluate(`document.querySelector('.studio').classList.contains('motion-off')`),true);
  await move('.collection-generative .collection-button');
  const off=await evaluate(`['.collection-generative','.collection-generative svg','.sculpture-chip','.collection-generative .collection-action>span'].map(s=>({transform:getComputedStyle(document.querySelector(s)).transform,duration:getComputedStyle(document.querySelector(s)).transitionDuration}))`);
  for(const item of off){assert.equal(item.transform,'none');assert.equal(item.duration,'0s')}checks.push('site_motion_switch_removes_all_topic_movement');
  await click('.motion-toggle');
  await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await move('.collection-cold .collection-button');
  const reduce=await evaluate(`['.collection-cold','.interest-sculpture','.interest-heart'].map(s=>getComputedStyle(document.querySelector(s)).transform)`);
  for(const item of reduce)assert.equal(item,'none');checks.push('os_reduced_motion_removes_topic_movement');
  await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'no-preference'}]});
  await click('.collection-cold .collection-button');
  for(let i=0;i<30;i++){if(await evaluate(`!!document.querySelector('.studio.is-work')`))break;await pause(300)}
  assert.equal(await evaluate(`!!document.querySelector('.studio.is-work')`),true);
  const work=await evaluate(`({heading:document.querySelector('h1')?.textContent,papers:document.querySelectorAll('.paper-card').length,reader:!!document.querySelector('.abstract')})`);
  assert.ok(work.papers>0);checks.push('real_button_enters_reading_workbench_with_papers');
  const report={status:'passed',browser:'isolated headless Microsoft Edge',viewport:{width:1600,height:1100},checks,baseline,focus,work};
  await fs.writeFile('reports/stage67/browser-validation.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{ws.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
