const {page}=require('./browser_helpers.cjs');
(async()=>{
 const lab=await page('lab','http://127.0.0.1:8802/');
 await lab.wait("document.getElementById('recorded')&&!document.getElementById('recorded').disabled");
 console.log('options',await lab.ev("[...document.getElementById('example').options].map(o=>({value:o.value,text:o.textContent}))"));
 await lab.choose('example','fixed');await lab.click('#recorded');
 await lab.wait("document.querySelector('#candidate-flow svg')&&document.querySelector('#citation-chain .citation-chain-card')");
 console.log('lab',await lab.ev("({flow:document.querySelectorAll('#candidate-flow .flow-node').length,chain:document.querySelectorAll('.citation-chain-card').length,errors:document.getElementById('status').textContent})"),lab.errors);
 await lab.shot('candidate-flow','#candidate-flow');await lab.shot('citation-chain','#citation-chain');
 const evidence=await page('evaluation','http://127.0.0.1:8802/evaluation.html');
 await evidence.wait("document.querySelectorAll('.outcome').length===12");
 console.log('evaluation',await evidence.ev("[...document.querySelectorAll('.cost-row')].map(n=>({policy:n.dataset.policy,value:n.dataset.value}))"),evidence.errors);
 await evidence.shot('evaluation-visuals','#evaluation-visuals');lab.ws.close();evidence.ws.close();
})().catch(e=>{console.error(e);process.exit(1)});
