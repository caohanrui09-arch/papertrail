// Isolated local Edge target, no external packages or user browser profile.
const fs=require('node:fs/promises');
async function connect(url){
 const ws=new WebSocket(url);await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no});
 let id=0;const pending=new Map();
 ws.onmessage=e=>{const v=JSON.parse(e.data);if(v.id){const p=pending.get(v.id);pending.delete(v.id);v.error?p.reject(Error(v.error.message)):p.resolve(v.result)}};
 return {ws,call(method,params={}){return new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}))})}};
}
async function main(){
 const target=await (await fetch('http://127.0.0.1:9327/json/new?about:blank',{method:'PUT'})).json();
 await fs.writeFile('.cache/stage67/target.json',JSON.stringify(target));
 const {ws,call}=await connect(target.webSocketDebuggerUrl);
 try{
  await call('Page.enable');await call('Runtime.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:1600,height:1100,deviceScaleFactor:1,mobile:false});
  await call('Page.navigate',{url:'http://127.0.0.1:8791/'});
  let state;
  for(let i=0;i<50;i++){
   const r=await call('Runtime.evaluate',{expression:`JSON.stringify({ready:document.readyState,found:!!document.querySelector('.collection-grid'),text:document.body.innerText.slice(0,700)})`,returnByValue:true});
   state=JSON.parse(r.result.value);if(state.found)break;
   await new Promise(r=>setTimeout(r,300));
  }
  if(!state.found)throw Error(JSON.stringify(state));
  await new Promise(r=>setTimeout(r,900));
  const r=await call('Runtime.evaluate',{expression:`JSON.stringify({buttons:[...document.querySelectorAll('.collection-button')].map(b=>({label:b.getAttribute('aria-label'),type:b.type})),grid:(()=>{const r=document.querySelector('.collection-grid').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height}})(),headings:[...document.querySelectorAll('h1,h2')].map(h=>h.textContent)})`,returnByValue:true});
  state=JSON.parse(r.result.value);
  const shot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{...state.grid,scale:1}});
  await fs.writeFile('reports/stage67/topics-rest.png',Buffer.from(shot.data,'base64'));
  await fs.writeFile('reports/stage67/browser-inspection.json',JSON.stringify(state,null,2));
  console.log(JSON.stringify(state));
 }finally{ws.close()}
}
module.exports={connect};
if(require.main===module)main().catch(e=>{console.error(e);process.exitCode=1});
