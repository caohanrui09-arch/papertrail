import {useEffect,useRef} from 'preact/hooks';
import Split from './vendor/split.mjs?v=66.1';

// Only a display ratio is stored; queries, reading history and preferences are not.
const KEY='papertrail.workbench.split.v1';
const DEFAULT=42;
function savedSize(){
 try{const value=Number(localStorage.getItem(KEY));return Number.isFinite(value)&&value>=25&&value<=65?value:DEFAULT;}
 catch{return DEFAULT;}
}

export function useWorkbenchLayout(enabled,focused){
 const container=useRef(null),separator=useRef(null),instance=useRef(null),last=useRef(savedSize());
 function sync(persist=false){
  const api=instance.current,gutter=separator.current,host=container.current;
  if(!api||!gutter||!host)return;
  const value=api.getSizes()[0],width=host.clientWidth;
  last.current=value;
  gutter.setAttribute('aria-valuenow',String(Math.round(value)));
  gutter.setAttribute('aria-valuemin',String(Math.ceil(286/Math.max(width,1)*100)));
  gutter.setAttribute('aria-valuemax',String(Math.floor(100-366/Math.max(width,1)*100)));
  gutter.setAttribute('aria-valuetext',`候选列表 ${Math.round(value)}%，阅读器 ${Math.round(100-value)}%`);
  if(persist)try{localStorage.setItem(KEY,String(value));}catch{}
 }
 function change(value){const api=instance.current;if(!api)return;api.setSizes([value,100-value]);sync(true);}
 useEffect(()=>{
  if(!enabled||focused||!container.current||!separator.current)return;
  const host=container.current,gutter=separator.current;
  const left=host.querySelector('.result-panel'),right=host.querySelector('.evidence-panel');
  const api=Split([left,right],{sizes:[last.current,100-last.current],minSize:[280,360],gutterSize:12,
   snapOffset:0,gutter:()=>gutter,onDrag:()=>sync(),onDragEnd:()=>sync(true)});
  instance.current=api;sync();
  const resize=new ResizeObserver(()=>{api.setSizes(api.getSizes());sync();});
  resize.observe(host);
  return()=>{resize.disconnect();api.destroy(false,true);instance.current=null;};
 },[enabled,focused]);
 function onKeyDown(event){
  if(!instance.current)return;
  const current=instance.current.getSizes()[0],step=event.shiftKey?5:2;
  const min=Number(separator.current.getAttribute('aria-valuemin'));
  const max=Number(separator.current.getAttribute('aria-valuemax'));
  const value=event.key==='ArrowLeft'?Math.max(min,current-step):event.key==='ArrowRight'?Math.min(max,current+step):event.key==='Home'?min:event.key==='End'?max:event.key==='Enter'?DEFAULT:null;
  if(value!==null){event.preventDefault();change(value);}
 }
 return {container,separator,onKeyDown,reset:()=>change(DEFAULT)};
}
