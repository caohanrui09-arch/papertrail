import {h} from 'preact';
import {useEffect,useState} from 'preact/hooks';
import htm from 'htm';
import {requestJSON} from './research-client.mjs?v=66.1';
const html=htm.bind(h);
export function useNoteSearch(notebook,query,active){
 const [result,setResult]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 useEffect(()=>{
  setResult(null);setError('');if(!active||!query.trim()||!notebook.data){setLoading(false);return;}
  const c=new AbortController();setLoading(true);
  requestJSON('/api/profile/notes/search?'+new URLSearchParams({q:query,revision:notebook.data.revision}),null,c.signal).then(next=>{if(!c.signal.aborted)setResult(next);}).catch(e=>{if(e.name!=='AbortError')setError(e.message);}).finally(()=>{if(!c.signal.aborted)setLoading(false);});return()=>c.abort();
 },[active,query,notebook.data?.revision,attempt]);
 return {result,loading,error,retry:async()=>{await notebook.reload();setAttempt(n=>n+1);}};
}
export function NoteSearchBar({query,onSearch,search}){
 const [draft,setDraft]=useState(query);
 useEffect(()=>setDraft(query),[query]);
 return html`<div class="note-search"><form onSubmit=${e=>{e.preventDefault();onSearch(draft.trim());}}><label for="note-search-query">搜索我的笔记</label><input id="note-search-query" aria-label="笔记关键词" maxLength="200" value=${draft} onInput=${e=>setDraft(e.target.value)} placeholder="问题或疑问中的关键词，多个词同时匹配"/><button disabled=${search.loading}>搜索</button>${query&&html`<button type="button" onClick=${()=>onSearch('')}>清除筛选</button>`}</form>${search.error&&html`<p role="alert">${search.error}<button onClick=${search.retry}>刷新笔记并重试</button></p>`}</div>`;
}
