import {h} from 'preact';
import htm from 'htm';
const html=htm.bind(h);
export function AgentHandoff({originalNeed,query,reviewed,scope,year,intent}){
 const original=(originalNeed||query||'').trim(),disabled=!original||(!query?.trim()&&intent!=='recommend');
 const payload={version:76,source:'papertrail-reading-workbench',original_need:original,executed_query:intent==='recommend'?'':query,query_reviewed:Boolean(reviewed),intent,source_scope:scope||'all',source_year:year||''};
 const bytes=new TextEncoder().encode(JSON.stringify(payload)),encoded=btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
 return html`<div class="agent-handoff-entry"><a class="handoff-link" aria-disabled=${disabled} href=${disabled?undefined:'http://127.0.0.1:8802/#handoff='+encoded} onClick=${e=>{if(disabled)e.preventDefault();}}>交给 Agent ↗</a><span>带上原问题与检索词；进入后确认画像和范围，再执行。</span></div>`;
}
