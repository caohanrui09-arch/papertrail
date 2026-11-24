// Targeted visual smoke checks; no new rankings, model runs or visitor feedback.
const fs=require('node:fs/promises'),assert=require('node:assert/strict'),{page}=require('./browser_helpers.cjs');
async function main(){
 const p=await page('validation','http://127.0.0.1:8791/'),checks=[];let modelPosts=0,feedbackPosts=0;
 await p.call('Network.enable');p.ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.method==='Network.requestWillBeSent'&&m.params.request.method==='POST'){const u=m.params.request.url;if(/\/lab\/(custom\/)?run$/.test(u))modelPosts++;if(/\/api\/profile\/(feedback|reset|import)/.test(u))feedbackPosts++}});
 const check=(name,v)=>{assert.ok(v,name);checks.push(name)},style=(selector,prop)=>p.ev(`getComputedStyle(document.querySelector(${JSON.stringify(selector)}))[${JSON.stringify(prop)}]`);
 async function go(url,ready){await p.call('Page.navigate',{url});await p.wait(ready)}
 try{
  // This is the dedicated verification profile only. Start a fresh visual walk-through.
  const reset=await p.call('Page.addScriptToEvaluateOnNewDocument',{source:"if(location.origin==='http://127.0.0.1:8791')for(const k of Object.keys(localStorage))if(k.startsWith('papertrail.workspace.v1.'))localStorage.removeItem(k)"});
  await p.call('Page.reload');await p.wait("document.querySelector('.orbit-scene')");await p.call('Page.removeScriptToEvaluateOnNewDocument',{identifier:reset.identifier});
  check('home_surface_stays_neutral',await style('.studio','backgroundColor')==='rgb(246, 246, 246)');
  check('orbit_gradient_and_satellites_have_color',await p.ev("getComputedStyle(document.querySelector('#orb stop:nth-child(2)')).stopColor==='rgb(75, 130, 233)'&&getComputedStyle(document.querySelector('.orbit-scene>circle[fill=\"#1e1e1e\"]')).fill==='rgb(230, 155, 70)'"));
  check('all_three_topic_illustrations_keep_color',await p.ev("getComputedStyle(document.querySelector('#gallery-blue stop:nth-child(2)')).stopColor==='rgb(76, 148, 255)'&&getComputedStyle(document.querySelector('.interest-heart path')).fill==='rgb(207, 119, 81)'&&getComputedStyle(document.querySelector('#eval-bar stop:last-child')).stopColor==='rgb(107, 97, 198)'"));
  await p.shot('home-art','.hero-art');await p.shot('topic-gallery','.collection-grid');
  await p.click('.learning-search');await p.ev("(()=>{const q=document.getElementById('query');q.value='retrieval';q.dispatchEvent(new Event('input',{bubbles:true}))})()");await p.click('.search-submit');await p.wait("document.querySelectorAll('.paper-card').length>0");
  check('reading_workspace_retains_neutral_surface',await style('.studio','backgroundColor')==='rgb(246, 246, 246)');
  check('real_search_terms_have_local_color',await p.ev("document.querySelector('.query-hit')&&getComputedStyle(document.querySelector('.query-hit')).backgroundColor==='rgb(255, 240, 200)'"));
  check('reader_empty_paper_illustration_has_local_color',await p.ev("getComputedStyle(document.querySelector('.empty-pages>span:first-child')).backgroundColor==='rgb(231, 239, 253)'&&getComputedStyle(document.querySelector('.empty-pages>span:last-child')).color==='rgb(83, 127, 190)'"));await p.shot('reading-workspace');
  await go('http://127.0.0.1:8791/evidence.html',"document.querySelector('.evidence-art')");await p.shot('evidence-graphic','.evidence-art');
  await p.ev("[...document.querySelectorAll('button')].find(n=>n.textContent.includes('训练对照')).click()");await p.wait("document.querySelector('.quality-chart .chart-bar')");
  check('evidence_illustration_and_real_bars_colored',await p.ev("getComputedStyle(document.querySelector('.art-path')).stroke==='rgb(57, 121, 217)'&&getComputedStyle(document.querySelector('.chart-bar.retained')).fill==='rgb(75, 128, 211)'&&getComputedStyle(document.querySelector('.chart-bar:not(.retained)')).fill==='rgb(153, 129, 203)'"));await p.shot('evidence-graphic','.evidence-art');await p.shot('evidence-chart','.quality-chart');
  await go('http://127.0.0.1:8791/minionerec.html',"document.querySelector('.project-chain')");
  check('minionerec_all_four_stages_colored',await p.ev("new Set([...document.querySelectorAll('.project-chain>rect')].map(n=>getComputedStyle(n).fill)).size===3&&new Set([...document.querySelectorAll('.project-chain>g:first-of-type rect')].map(n=>getComputedStyle(n).fill)).size===3"));
  await p.click('.project-step:nth-child(2)');check('minionerec_selected_model_still_marked',await p.ev("document.querySelector('.project-step:nth-child(2)').getAttribute('aria-pressed')==='true'&&getComputedStyle(document.querySelector('.project-chain>rect:nth-of-type(2)')).strokeWidth==='2px'"));await p.shot('minionerec');
  await go('http://127.0.0.1:8791/sid-lab.html',"document.querySelector('.sid-bars i')&&document.querySelector('.sid-tokens code')");
  check('sid_layers_have_three_distinct_chart_colors',await p.ev("new Set([...document.querySelectorAll('.sid-book-grid>article')].map(n=>getComputedStyle(n.querySelector('.sid-bars i')).backgroundColor)).size===3"));
  check('sid_token_palette_matches_layer_roles',await p.ev("getComputedStyle(document.querySelector('.sid-tokens code:nth-child(1)')).color==='rgb(49, 92, 154)'&&getComputedStyle(document.querySelector('.sid-tokens code:nth-child(2)')).color==='rgb(116, 83, 152)'"));await p.shot('sid-codebooks','.sid-codebooks');await p.shot('sid-lab');
  for(const path of ['online.html','legal.html']){await go('http://127.0.0.1:8791/'+path,"[...document.styleSheets].some(s=>s.href?.includes('graphic-colors'))");check(path+'_uses_shared_graphic_palette',await p.ev("[...document.styleSheets].some(s=>s.href?.includes('graphic-colors'))"))}
  await go('http://127.0.0.1:8802/',"document.getElementById('recorded')&&!document.getElementById('recorded').disabled");await p.choose('example','fixed');await p.click('#recorded');await p.wait("document.querySelector('#candidate-flow .flow-node.cited')");
  check('agent_flow_search_recommend_read_citation_have_distinct_colors',await p.ev("new Set(['search','recommend','read','cited'].map(c=>getComputedStyle(document.querySelector('#candidate-flow .flow-node.'+c+' rect')).fill)).size===4&&getComputedStyle(document.querySelector('#candidate-flow .flow-node.cited rect')).fill==='rgb(73, 106, 171)'"));
  check('citation_quote_uses_blue_evidence_line',await p.ev("getComputedStyle(document.querySelector('.chain-steps blockquote')).borderLeftColor==='rgb(117, 149, 208)'"));await p.shot('agent-flow','#candidate-flow');await p.shot('citation-chain','#citation-chain');
  await go('http://127.0.0.1:8802/evaluation.html',"document.querySelectorAll('.outcome').length===12");
  check('evaluation_keeps_protocol_counts_and_local_state_colors',await p.ev("document.querySelectorAll('.outcome.pass').length===7&&document.querySelectorAll('.outcome.fail').length===5&&getComputedStyle(document.querySelector('.outcome.fail')).backgroundColor==='rgb(252, 240, 236)'"));
  check('cost_strategies_have_three_distinct_colors_and_fixed_zero',await p.ev("new Set([...document.querySelectorAll('.cost-chart:first-child .cost-bar')].map(n=>getComputedStyle(n).backgroundColor)).size===3&&document.querySelector('.cost-chart[data-unit=tokens] .cost-row[data-policy=fixed]').dataset.value==='0'"));await p.shot('evaluation-visuals','#evaluation-visuals');
  await go('http://127.0.0.1:8802/label?verification=1',"document.querySelectorAll('.query-list button').length===26");check('blind_label_page_loads_shared_palette_without_new_judgments',await p.ev("[...document.styleSheets].some(s=>s.href?.includes('graphic-colors'))"));
  check('no_browser_runtime_exceptions',p.errors.length===0);check('no_model_or_feedback_writes',modelPosts===0&&feedbackPosts===0);
  const result={status:'passed',checks:checks.length,passed:checks,model_submissions:modelPosts,feedback_writes:feedbackPosts,new_human_labels:0,scope:'Desktop visual smoke checks; existing algorithms, model and data unchanged.'};await fs.writeFile('reports/stage75/browser-validation.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{p.ws.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
