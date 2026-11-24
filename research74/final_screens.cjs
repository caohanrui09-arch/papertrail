const {page}=require('./browser_helpers.cjs');
(async()=>{
 const lab=await page('final-lab','http://127.0.0.1:8802/');
 await lab.wait("document.getElementById('recorded')&&!document.getElementById('recorded').disabled");
 await lab.choose('example','fixed');await lab.click('#recorded');await lab.wait("document.querySelector('#candidate-flow svg')&&document.querySelector('#citation-chain blockquote')");
 await lab.ev("document.querySelector('.workspace').scrollIntoView({block:'start',behavior:'instant'})");await lab.shot('lab-overview');
 const evaluation=await page('final-evaluation','http://127.0.0.1:8802/evaluation.html');await evaluation.wait("document.querySelectorAll('.outcome').length===12");
 await evaluation.ev("document.getElementById('evaluation-visuals').scrollIntoView({block:'start',behavior:'instant'})");await evaluation.shot('evaluation-overview');
 console.log(JSON.stringify({status:'screenshots_saved',runtime_errors:[...lab.errors,...evaluation.errors],closing_dedicated_browser:true}));
 try{await evaluation.call('Browser.close')}catch{}lab.ws.close();evaluation.ws.close();
})().catch(error=>{console.error(error);process.exitCode=1});
