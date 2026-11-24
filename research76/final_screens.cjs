const fs=require('node:fs/promises'),{page}=require('./browser_helpers.cjs');
(async()=>{
 const p=await page('trial-preparation','http://127.0.0.1:8791/trial.html');await p.wait("document.querySelectorAll('.trial-task').length===5&&document.querySelector('[name=\"root[outcome]\"]')");
 const evidence=await p.ev("({default_human_storage:localStorage.getItem('papertrail.usability.v76.human_self_report'),source:document.getElementById('trial-source').textContent,record_summary:document.getElementById('trial-summary').textContent})");
 if(evidence.default_human_storage!==null)throw Error('Unexpected human trial record in verification browser');await p.shot('step5-preparation');await fs.writeFile('reports/stage76/step5-human-preparation.json',JSON.stringify({status:'passed',...evidence,human_trials_carried_out:0,user_choice:'prepare_materials_now_trial_later'},null,2));console.log(evidence);p.ws.close();
})().catch(e=>{console.error(e);process.exitCode=1});
