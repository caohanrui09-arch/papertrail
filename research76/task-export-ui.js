/* Reuses the existing report dialog's local Blob + object URL download pattern. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id);let jsonUrl=null,markdownUrl=null,generation=0;
 function revoke(){for(const url of [jsonUrl,markdownUrl])if(url)URL.revokeObjectURL(url);jsonUrl=markdownUrl=null;$('export-preview').hidden=true;for(const id of ['download-task-json','download-task-markdown'])$(id).removeAttribute('href')}
 function ready(s){return Boolean(s?.row&&s.actual&&s.row.task_id===s.actual.task_id&&!s.row._in_progress&&!s.actual.provisional&&(s.actual.source?.kind!=='job'||s.actual.source.run_index===s.runIndex))}
 function refresh(){if(!$('prepare-task-report'))return;generation++;revoke();const s=PapertrailWorkspace.snapshot,ok=ready(s);$('prepare-task-report').disabled=!ok;$('export-readiness').textContent=ok?'终局记录已就绪':'等待本次终局结果及实际候选证据'}
 async function generate(){const s=PapertrailWorkspace.snapshot;if(!ready(s))return;const ticket=++generation;$('prepare-task-report').disabled=true;$('export-error').textContent='';
  try{const context=typeof resultContext!=='undefined'&&resultContext?resultContext:{description:$('task-description').textContent},handoff=window.PapertrailHandoff?.snapshot,ownHandoff=handoff&&context.original_need===handoff.draft_need?handoff:null;
   const events=s.actual.source.kind==='job'&&typeof feed!=='undefined'&&feed.job===s.actual.source.job_id?[...feed.rows.values()]:[];
   const report=await PapertrailTaskReport.pack({...s,context,handoff:ownHandoff,events});if(ticket!==generation||PapertrailWorkspace.snapshot.row!==s.row)return;
   revoke();const json=JSON.stringify(report.envelope,null,2);jsonUrl=URL.createObjectURL(new Blob([json],{type:'application/json;charset=utf-8'}));markdownUrl=URL.createObjectURL(new Blob([report.markdown],{type:'text/markdown;charset=utf-8'}));
   for(const [id,url,ext]of [['download-task-json',jsonUrl,'json'],['download-task-markdown',markdownUrl,'md']]){$(id).href=url;$(id).download=report.filename+'.'+ext}
   $('task-report-preview').value=report.markdown;$('task-report-hash').textContent='内容 SHA-256：'+report.envelope.content_sha256;$('export-preview').hidden=false;
  }catch(e){$('export-error').textContent='报告未生成：'+e.message}finally{if(ticket===generation)$('prepare-task-report').disabled=!ready(PapertrailWorkspace.snapshot)}
 }
 function init(){$('prepare-task-report').onclick=generate;refresh()}
 window.PapertrailExports={refresh};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
