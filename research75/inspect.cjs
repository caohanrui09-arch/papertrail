const {page}=require('./browser_helpers.cjs');
(async()=>{
 const p=await page('inspect','http://127.0.0.1:8791/');await p.wait("document.querySelector('.orbit-scene')");
 console.log('home',await p.ev("({background:getComputedStyle(document.querySelector('.studio')).backgroundColor,gradient:[...document.querySelectorAll('#orb stop')].map(n=>getComputedStyle(n).stopColor),buttons:[...document.querySelectorAll('button')].slice(0,22).map(n=>({text:n.textContent,cls:n.className})),inputs:[...document.querySelectorAll('input')].map(n=>({placeholder:n.placeholder,id:n.id,type:n.type})),links:[...document.querySelectorAll('a')].slice(0,12).map(n=>({text:n.textContent,href:n.getAttribute('href')}))})"));
 await p.shot('home-art','.hero-art');await p.shot('topic-gallery','.collection-grid');
 for(const path of ['evidence.html','minionerec.html','sid-lab.html','online.html']){
  await p.call('Page.navigate',{url:'http://127.0.0.1:8791/'+path});await p.wait("document.querySelector('h1')");
  console.log(path,await p.ev("({h1:document.querySelector('h1').textContent,svgs:[...document.querySelectorAll('svg')].map(s=>s.getAttribute('class')),colorsheet:[...document.styleSheets].some(s=>s.href?.includes('graphic-colors')),bg:getComputedStyle(document.body).backgroundColor})"));await p.shot(path.replace('.html',''));
 }
 console.log('errors',p.errors);p.ws.close();
})().catch(e=>{console.error(e);process.exitCode=1});
