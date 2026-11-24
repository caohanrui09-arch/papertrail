import {h} from 'preact';
import {useLayoutEffect,useRef} from 'preact/hooks';
import htm from 'htm';
const html=htm.bind(h);

// Scroll only the list, so revealing a paper never moves the reading pane or page.
function reveal(list,card,force=false){
 if(!list||!card)return;
 const area=list.getBoundingClientRect(),item=card.getBoundingClientRect();
 if(force||item.top<area.top+12||item.bottom>area.bottom-12){
  list.scrollTo({top:Math.max(0,list.scrollTop+item.top-area.top-12),behavior:'auto'});
 }
}

export function useReadingSession({result,target,paper,view}){
 const listRef=useRef(null),readRef=useRef(null),cards=useRef(new Map());
 useLayoutEffect(()=>{listRef.current?.scrollTo(0,0);},[result]);
 useLayoutEffect(()=>{if(view==='work')reveal(listRef.current,cards.current.get(target));},[target,view]);
 useLayoutEffect(()=>{readRef.current?.scrollTo(0,0);},[target,paper?.paper.doc_id]);
 return {listRef,readRef,
  registerCard(doc,node){if(node)cards.current.set(doc,node);else cards.current.delete(doc);},
  locate(){const card=cards.current.get(target);reveal(listRef.current,card,true);card?.querySelector('.paper-title')?.focus({preventScroll:true});}
 };
}

export function ReadingControls({papers=[],target,readState,onRead}){
 const index=papers.findIndex(p=>p.doc_id===target);
 const label=index>=0?`第 ${index+1} / ${papers.length} 篇`:target?'上下文论文':'尚未选择论文';
 function move(delta){const next=index+delta;if(index>=0&&next>=0&&next<papers.length)onRead(papers[next].doc_id);}
 return html`<nav class="reading-nav" aria-label="连续阅读"><button class="reading-prev" aria-label="上一篇论文" disabled=${index<=0} title=${index>0?papers[index-1].title:'没有上一篇候选'} onClick=${()=>move(-1)}><span aria-hidden="true">←</span>上一篇</button><div class="reading-position" role="status" aria-live="polite"><strong>${label}</strong>${readState==='loading'?html`<small>正在载入</small>`:readState==='error'?html`<small>读取失败</small>`:null}</div><button class="reading-next" aria-label="下一篇论文" disabled=${index<0||index>=papers.length-1} title=${index>=0&&index<papers.length-1?papers[index+1].title:'没有下一篇候选'} onClick=${()=>move(1)}>下一篇<span aria-hidden="true">→</span></button></nav>`;
}
