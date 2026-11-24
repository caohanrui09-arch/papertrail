/* Disclosure follows existing display state only; no tools or requests are created. */
(() => {
 'use strict';
 function init(){
  const shell=document.getElementById('workspace-shell'),plan=document.getElementById('custom-plan'),scope=document.getElementById('scope-info');
  if(!shell||!plan||!scope)return;
  const showResults=()=>{const state=document.body.dataset.executionState;if(document.body.classList.contains('has-task')||['submitting','running','complete','failed','disconnected'].includes(state))shell.open=true};
  new MutationObserver(showResults).observe(document.body,{attributes:true,attributeFilter:['class','data-execution-state']});
  new MutationObserver(()=>{if(!plan.hidden)scope.open=true}).observe(plan,{attributes:true,attributeFilter:['hidden']});
  const diagnostic=document.getElementById('algorithm-diagnostics');if(diagnostic)new MutationObserver(()=>{if(diagnostic.open)shell.open=true}).observe(diagnostic,{attributes:true,attributeFilter:['open']});
  showResults();if(!plan.hidden)scope.open=true;
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
