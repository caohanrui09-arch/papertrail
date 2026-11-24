/* Presentation only. Native tool traces, pool rankings and frozen evaluation are the source.
 * Links reuse local ISC-licensed d3-shape 3.2.0; no scoring or Agent decisions here. */
(() => {
  'use strict';
  const ns = 'http://www.w3.org/2000/svg';
  const names = {search_papers:'搜索', recommend_papers:'推荐', read_paper:'读取摘要', finalize:'提交'};
  const policies = {fixed:'固定流程', llm_agent:'原 LLM', constrained:'状态约束 LLM'};
  const node = (tag, text, cls) => {const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n};
  const svgNode = (tag, attrs={}, text) => {const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!=null)n.textContent=text;return n};
  const num = v => typeof v==='number'&&Number.isFinite(v);
  const short = (v, length=22) => {const a=Array.from(String(v||''));return a.length>length?a.slice(0,length-1).join('')+'…':a.join('')};
  function section(root, eyebrow, title, note) {
    root.replaceChildren();delete root.dataset.taskId;root.classList.add('evidence-visual');
    const head=node('div',null,'visual-heading');head.append(node('p',eyebrow,'eyebrow'),node('h3',title));root.append(head);
    if(note)root.append(node('p',note,'visual-note'));return root;
  }
  function clear(root, message='等待本次真实数据。') {if(!root)return;root.replaceChildren(node('p',message,'visual-empty'));delete root.dataset.taskId}
  function frame(root,w,h,label) {
    const wrap=node('div',null,'visual-scroll'),s=svgNode('svg',{viewBox:`0 0 ${w} ${h}`,class:'evidence-svg',role:'group','aria-label':label});
    s.append(svgNode('title',{},label));wrap.append(s);root.append(wrap);return s;
  }
  function table(headers, rows) {
    const t=node('table',null,'visual-data'),thead=node('thead'),h=node('tr');headers.forEach(x=>{const th=node('th',x);th.scope='col';h.append(th)});thead.append(h);t.append(thead);
    const body=node('tbody');rows.forEach(values=>{const tr=node('tr');values.forEach(x=>tr.append(node('td',x)));body.append(tr)});t.append(body);return t;
  }
  function fallback(root, title, headers, rows) {const d=node('details',null,'visual-details');d.append(node('summary',title),table(headers,rows));root.append(d)}
  function button(text, action, cls) {const b=node('button',text,cls);b.type='button';b.onclick=action;return b}
  function safeLink(text, href) {try{const u=new URL(href);if(u.protocol==='https:'&&u.hostname==='arxiv.org'){const a=node('a',text);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a}}catch{}return node('span','来源链接未通过校验')}
  function activate(n, fn) {n.setAttribute('role','button');n.setAttribute('tabindex','0');n.addEventListener('click',fn);n.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();fn()}})}
  function curve(s, from, to, cls, data={}) {
    const d=window.d3?.linkHorizontal()({source:from,target:to});
    if(!d)return null;
    const p=svgNode('path',{d,class:'flow-link '+cls,...data});s.append(p);return p;
  }
  function flowNode(s,{x,y,w=144,label,sub,kind,doc,attempt,action,full}) {
    const g=svgNode('g',{transform:`translate(${x},${y})`,class:'flow-node '+kind,'aria-label':full||[label,sub].filter(Boolean).join(' · ')});
    if(doc)g.dataset.docId=doc;if(attempt!=null)g.dataset.attempt=String(attempt);
    g.append(svgNode('title',{},full||[label,sub].join(' · ')),svgNode('rect',{x:0,y:-24,width:w,height:48,rx:8}),svgNode('text',{x:11,y:-3,class:'node-label'},short(label,20)),svgNode('text',{x:11,y:14,class:'node-sub'},short(sub,18)));
    if(action)activate(g,action);s.append(g);return g;
  }
  function candidateFlow(root, value, hooks={}) {
    if(!root)return;if(!value){clear(root);return}
    section(root,'ACTUAL CANDIDATE FLOW','从返回，到引用。','只画实际取得的论文与关联；同一论文合并为一个候选。点击节点定位论文或原始调用。');
    root.dataset.taskId=value.task_id;
    const papers=value.papers||[],calls=value.retrievals||[],reads=papers.filter(p=>p.read_success),cites=papers.filter(p=>p.cited);
    const counts=node('div',null,'flow-totals');counts.append(node('span',`${calls.length} 次返回`),node('span',`${papers.length} 篇去重`),node('span',`${reads.length} 篇已读`),node('span',`${cites.length} 篇${value.provisional?'暂验引用':'最终引用'}`));root.append(counts);
    const h=Math.max(245,papers.length*64+96,calls.length*66+96),s=frame(root,760,h,'实际调用到候选、成功读取与引用的关联图；方向从左到右'),xs=[8,205,407,607],ys=new Map(papers.map((p,i)=>[p.doc_id,76+i*64]));
    ['工具返回','去重候选','成功读取','引用'].forEach((label,i)=>s.append(svgNode('text',{x:xs[i]+5,y:23,class:'column-label'},label)));
    const links=svgNode('g');s.append(links);
    const callY=new Map(calls.map((c,i)=>[c.attempt,68+(h-110)*(i+.5)/Math.max(1,calls.length)]));
    for(const p of papers){const y=ys.get(p.doc_id);for(const o of p.occurrences||[])if(callY.has(o.attempt))curve(links,[xs[0]+144,callY.get(o.attempt)],[xs[1],y],o.tool==='search_papers'?'search':'recommend',{'data-doc-id':p.doc_id,'data-stage':'return'});
      if(p.read_success)curve(links,[xs[1]+144,y],[xs[2],y],'read',{'data-doc-id':p.doc_id,'data-stage':'read'});
      if(p.cited&&p.read_success)curve(links,[xs[2]+144,y],[xs[3],y],'cited',{'data-doc-id':p.doc_id,'data-stage':'citation'});
    }
    for(const c of calls)flowNode(s,{x:xs[0],y:callY.get(c.attempt),label:`#${c.attempt} ${names[c.tool]||c.tool}`,sub:c.error?'执行失败':`${c.count??0} 篇返回`,kind:c.error?'failed':c.tool==='search_papers'?'search':'recommend',attempt:c.attempt,action:()=>hooks.call?.(c.attempt),full:`调用 #${c.attempt} ${names[c.tool]||c.tool} · ${c.error||c.count+' 篇返回'}`});
    for(const p of papers){const y=ys.get(p.doc_id);flowNode(s,{x:xs[1],y,label:p.doc_id,sub:short(p.title),kind:'paper',doc:p.doc_id,action:()=>hooks.paper?.(p.doc_id),full:`${p.doc_id} · ${p.title} · ${p.version_key}`});
      if(p.read_success)flowNode(s,{x:xs[2],y,label:p.doc_id,sub:`已读 · 调用 #${p.read_attempt}`,kind:'read',doc:p.doc_id,attempt:p.read_attempt,action:()=>hooks.call?.(p.read_attempt)});
      if(p.cited)flowNode(s,{x:xs[3],y,label:p.doc_id,sub:value.provisional?'暂验提交 · 待最终响应':'最终引用 · 核对摘录',kind:'cited',doc:p.doc_id,action:()=>hooks.citation?.(p.doc_id)});
    }
    if(!papers.length)s.append(svgNode('text',{x:215,y:100,class:'empty-label'},calls.length?'实际返回为空，没有后续论文节点。':'尚无工具返回；等待真实事件。'));
    const highlight=doc=>{for(const n of s.querySelectorAll('[data-doc-id]'))n.classList.toggle('dimmed',Boolean(doc)&&n.dataset.docId!==doc)};
    s.addEventListener('focusin',e=>highlight(e.target.closest('[data-doc-id]')?.dataset.docId));s.addEventListener('focusout',()=>highlight(null));s.addEventListener('pointerover',e=>highlight(e.target.closest('[data-doc-id]')?.dataset.docId));s.addEventListener('pointerleave',()=>highlight(null));
    const sourceName={historical_v64:'阶段64历史回放',historical_v71:'阶段71历史回放',job:'当前作业'}[value.source?.kind]||'来源见原始字段';
    root.append(node('p',`${sourceName} · ${value.task_id} · ${value.provisional?'逐步记录，尚未冻结':'已返回记录'} · 截止 ${value.as_of}`,'visual-caption'),node('p','请求读取不等于读取成功；未读或未引用不表示不相关。连线不表示流量权重，也不推断模型内部思考。','visual-note'));
    fallback(root,'按文字核对每篇流转',['论文 ID','实际来源 / 原排名','成功读取','引用'],papers.map(p=>[p.doc_id,p.occurrences.map(o=>`${names[o.tool]} #${o.attempt} / 第${o.rank}`).join('；'),p.read_success?'是':'否',p.cited?(value.provisional?'暂验':'是'):'否']));
  }
  function rankData(value) {
    const a=value?.methods?.pool_content,b=value?.methods?.profile_rerank;
    if(!Array.isArray(a)||!Array.isArray(b))return {error:'等待共享候选池的查询排序与画像重排结果。'};
    const ah=value.method_info?.pool_content?.pool_ids_sha256,bh=value.method_info?.profile_rerank?.pool_ids_sha256;
    const ids=a.map(p=>p.doc_id),other=b.map(p=>p.doc_id);
    if(!ah||ah!==bh||ah!==value.pool_ids_sha256||new Set(ids).size!==ids.length||new Set(other).size!==other.length||ids.length!==other.length||ids.some(id=>!other.includes(id)))return {error:'候选池集合或哈希不一致，不绘制重排连线。'};
    const positions=new Map(b.map((p,i)=>[p.doc_id,i+1]));
    return {rows:a.map((p,i)=>({...p,before:i+1,after:positions.get(p.doc_id),delta:i+1-positions.get(p.doc_id)})),hash:ah};
  }
  function rankChanges(root,value,hooks={}) {
    if(!root)return;if(!value){clear(root,'运行独立诊断后，展示同池重排前后名次。');return}
    section(root,'SHARED POOL / RANK CHANGE','名次如何移动。','共享池查询排序 → 同池画像重排。显示完整池内名次，不直接比较不同方法的原始分数。');
    const data=rankData(value);if(data.error){root.append(node('p',data.error,'visual-empty'));return}
    root.dataset.taskId=value.task_id;const rows=data.rows,n=rows.length;
    const enters=rows.filter(r=>r.before>10&&r.after<=10),exits=rows.filter(r=>r.before<=10&&r.after>10);
    const tags=node('div',null,'flow-totals');tags.append(node('span',`${n} 篇共享候选`),node('span',`${enters.length} 篇进入 Top10`),node('span',`${exits.length} 篇离开 Top10`));root.append(tags);
    if(!n){root.append(node('p','共享候选池为空，无名次可连线。','visual-empty'));return}
    const s=frame(root,760,Math.max(180,78+n*32),'共享候选池的查询名次与画像重排名次，数字越小越靠前'),y=r=>51+(r-1)*32;
    s.append(svgNode('text',{x:10,y:19,class:'column-label'},'查询排序'),svgNode('text',{x:574,y:19,class:'column-label'},'画像重排'));
    if(n>10){s.append(svgNode('line',{x1:6,x2:754,y1:y(10)+16,y2:y(10)+16,class:'rank-cutoff'}),svgNode('text',{x:319,y:y(10)+12,class:'cutoff-label'},'Top10 边界'));}
    const detail=node('p','点击任一连线或名次，查看论文与名次变化。','rank-selection');detail.setAttribute('aria-live','polite');
    for(const r of rows){const cls=r.before>10&&r.after<=10?'entry':r.before<=10&&r.after>10?'exit':r.delta>0?'up':r.delta<0?'down':'same';
      const label=`${r.doc_id}：${r.before} → ${r.after}，${r.delta>0?'上升 '+r.delta:r.delta<0?'下降 '+(-r.delta):'不变'}${cls==='entry'?'，进入 Top10':cls==='exit'?'，离开 Top10':''}`;
      const g=svgNode('g',{class:'rank-pair '+cls,'data-doc-id':r.doc_id,'data-before':r.before,'data-after':r.after,'aria-label':label});
      g.append(svgNode('title',{},label+' · '+r.title),svgNode('line',{x1:193,y1:y(r.before),x2:545,y2:y(r.after),class:'rank-hit',stroke:'transparent','stroke-width':12}),svgNode('line',{x1:193,y1:y(r.before),x2:545,y2:y(r.after),class:'rank-line'}));
      [193,545].forEach((x,i)=>g.append(svgNode('circle',{cx:x,cy:y(i?r.after:r.before),r:4})));
      g.append(svgNode('text',{x:8,y:y(r.before)+4,class:'rank-label'},`${String(r.before).padStart(2,'0')}  ${r.doc_id}`),svgNode('text',{x:562,y:y(r.after)+4,class:'rank-label'},`${String(r.after).padStart(2,'0')}  ${r.doc_id}`));
      activate(g,()=>{for(const other of s.querySelectorAll('.rank-pair'))other.classList.toggle('dimmed',other!==g);detail.replaceChildren(node('strong',label),node('span',' · '+r.title));if(hooks.paper)detail.append(button('定位诊断论文 ↗',()=>hooks.paper(r.doc_id)))});s.append(g);
    }
    root.append(detail,button('显示全部名次',()=>{for(const g of s.querySelectorAll('.rank-pair'))g.classList.remove('dimmed');detail.textContent='点击任一连线或名次，查看论文与名次变化。'},'rank-reset'),node('p','蓝色 / 上升 · 琥珀 / 下降 · 灰色 / 不变；名次与进入/离开状态同时提供文字。','visual-note'));
    const info=value.method_info.profile_rerank;if(info.fallback_reason)root.append(node('p','回退：'+info.fallback_reason,'visual-note'));
    root.append(node('p','独立诊断，未发送给 Agent。候选池 SHA-256：'+data.hash,'visual-caption'));
    fallback(root,'查看完整名次与 Top10 变化',['论文 ID','重排前','重排后','变化'],rows.map(r=>[r.doc_id,r.before,r.after,r.before>10&&r.after<=10?'进入 Top10':r.before<=10&&r.after>10?'离开 Top10':r.delta>0?'↑ '+r.delta:r.delta<0?'↓ '+(-r.delta):'不变']));
  }
  function chainData(row) {
    const entries=row?.trace?.trace||[],answer=row?.answer;
    return (answer?.citations||[]).map(c=>{
      const retrieved=entries.filter(e=>['search_papers','recommend_papers'].includes(e.tool)&&!e.result?.error&&e.result?.papers?.some(p=>p.doc_id===c.doc_id&&p.version===c.version&&p.source_url===c.source_url));
      const read=entries.find(e=>e.tool==='read_paper'&&!e.result?.error&&e.result?.doc_id===c.doc_id&&e.result.version_key===c.version_key&&e.result.source_url===c.source_url&&e.result.version===c.version&&typeof c.quote==='string'&&c.quote.length>0&&e.result.abstract?.includes(c.quote)&&e.result.quotes?.some(q=>q.quote_index===c.quote_index&&q.text===c.quote));
      const finalize=entries.find(e=>e.tool==='finalize'&&!e.result?.error&&e.result?.citations?.some(q=>q.doc_id===c.doc_id&&q.version_key===c.version_key&&q.quote===c.quote));
      const ordered=read&&finalize&&entries.indexOf(read)<entries.indexOf(finalize)&&retrieved.some(e=>entries.indexOf(e)<entries.indexOf(read));
      return {citation:c,retrieved,read,finalize,verified:Boolean(ordered)};
    });
  }
  function citationChain(root,row,context={},hooks={}) {
    if(!root)return;if(!row){clear(root,'完成实际读取与提交后，在这里核对引用来源。');return}
    section(root,'CITATION PROVENANCE','每一段引用，都能回到原文。','核对本次实际工具返回、成功读取与提交摘录；程序化来源一致不代表语义正确。');root.dataset.taskId=row.task_id;
    if(row._in_progress)root.append(node('p','当前为逐步事件中的已接收提交，等待作业最终响应核对。','visual-note'));
    const request=node('div',null,'chain-request');request.append(node('span',context.original_need?'原始需求':'任务上下文','chain-label'),node('p',context.original_need||context.description||`任务 ${row.task_id}；本记录未提供可直接展示的原始需求。`));
    if(context.executed_query)request.append(node('p','确认检索词：'+context.executed_query,'visual-note'));root.append(request);
    const rows=chainData(row);if(!rows.length){root.append(node('p','当前没有已提交引用；已有候选与读取仍可在时间线查看，不补交答案。','visual-empty'));return}
    for(const [index,item] of rows.entries()){const c=item.citation,card=node('details',null,'citation-chain-card');card.dataset.docId=c.doc_id;const summary=node('summary');summary.append(node('span',c.version_key||c.doc_id),node('span',item.verified?'本次来源一致':'证据链未完整核实',item.verified?'chain-pass':'chain-warning'));card.append(summary);card.open=index===0;
      if(!item.verified){card.append(node('p','读取、版本、摘录或提交关联缺失；不在证据链中展示为已验证摘录。','notice'));root.append(card);continue}
      const steps=node('ol',null,'chain-steps');
      const sources=node('li');sources.append(node('span','取得候选','chain-label'));for(const e of item.retrieved)sources.append(button(`#${e.attempt} ${names[e.tool]} · 原排名 ${e.result.papers.findIndex(p=>p.doc_id===c.doc_id)+1}`,()=>hooks.call?.(e.attempt),'chain-call'));steps.append(sources);
      const read=node('li');read.append(node('span','成功读取原摘要','chain-label'),button(`#${item.read.attempt} read_paper · ${c.doc_id}`,()=>hooks.call?.(item.read.attempt),'chain-call'));const original=node('details');original.append(node('summary','展开本次返回的完整原摘要'),node('p',item.read.result.abstract,'original-abstract'));read.append(original);steps.append(read);
      const quote=node('li');quote.append(node('span','逐字摘录 · quote_index '+c.quote_index,'chain-label'),node('blockquote',c.quote),button(`#${item.finalize.attempt} 提交中的实际引用`,()=>hooks.call?.(item.finalize.attempt),'chain-call'));steps.append(quote);
      const source=node('li');source.append(node('span','论文版本与来源','chain-label'),node('strong',c.title),node('code',`${c.doc_id} · ${c.version_key}`),safeLink('打开对应版本 ↗',c.source_url));if(hooks.paper)source.append(button('定位实际候选 ↗',()=>hooks.paper(c.doc_id),'chain-call'));steps.append(source);card.append(steps);root.append(card);
    }
  }
  function evaluation(root,agent,hooks={}) {
    if(!root)return;
    section(root,'4 TASKS × 3 STRATEGIES','协议结果，一格一条真实记录。','✓ 协议完成 · × 未完成 · … 未结束。点击格子定位原始结果；此处不是语义质量评分。');
    const rows=agent.rows||[],policyOrder=['fixed','llm_agent','constrained'],tasks=[...new Set(rows.map(r=>r.task_id))],labels={'e73-search':'主题搜索','e73-recommend':'个性化推荐','e73-mixed':'搜索＋推荐','e73-empty':'无结果控制'};
    const grid=node('table',null,'outcome-matrix'),head=node('tr');head.append(node('th','受控任务'));for(const p of policyOrder)head.append(node('th',policies[p]));for(const h of head.children)h.scope='col';const th=node('thead');th.append(head);grid.append(th);const body=node('tbody');
    for(const task of tasks){const tr=node('tr'),label=node('th');label.scope='row';label.append(node('strong',labels[task]||task),node('small',task));tr.append(label);for(const policy of policyOrder){const r=rows.find(x=>x.task_id===task&&x.policy===policy),td=node('td'),state=r?.status==='complete'?(r.completed_protocol?'pass':'fail'):'pending';const b=button('',()=>r&&hooks.cell?.(r.cell),'outcome '+state);if(!r)b.disabled=true;
        b.dataset.cell=r?.cell||'';b.dataset.state=state;b.setAttribute('aria-label',`${labels[task]||task} / ${policies[policy]}：${state==='pass'?'协议完成':state==='fail'?'未完成提交':'未结束'}`);
        b.append(node('span',state==='pass'?'✓':state==='fail'?'×':'…','outcome-icon'),node('span',state==='pass'?'协议完成':state==='fail'?'未完成提交':'未结束'));if(state==='fail'){b.append(node('small','查看失败原因 ↗'));b.title=r.failure_reason||r.failure_kind||'查看原始失败记录'}td.append(b);tr.append(td)}body.append(tr)}grid.append(body);const scroll=node('div',null,'visual-scroll');scroll.append(grid);root.append(scroll);
    const charts=node('div',null,'cost-charts');const methods=policyOrder.map(p=>({policy:p,...agent.methods[p]}));
    for(const spec of [{key:'tokens',title:'模型 Token',unit:'Token',value:m=>num(m.input_tokens)&&num(m.output_tokens)?m.input_tokens+m.output_tokens:null},{key:'seconds',title:'执行耗时',unit:'秒',value:m=>m.execution_seconds}]){
      const chart=node('section',null,'cost-chart');chart.dataset.unit=spec.key;chart.append(node('h4',spec.title),node('p','同策略 4 条任务合计 · 从 0 起','visual-note'));
      const values=methods.map(spec.value),max=Math.max(0,...values.filter(num)),axis=node('div',null,'cost-axis');axis.append(node('span','0'),node('span',(spec.key==='seconds'?max.toFixed(2):max.toLocaleString())+' '+spec.unit));chart.append(axis);
      methods.forEach((m,i)=>{const value=values[i],line=node('div',null,'cost-row');line.dataset.policy=m.policy;if(num(value))line.dataset.value=String(value);const track=node('div',null,'cost-track'),bar=node('div',null,'cost-bar '+m.policy);bar.style.width=(num(value)&&max?value/max*100:0)+'%';track.append(bar);line.append(node('span',policies[m.policy]),track,node('strong',num(value)?(spec.key==='seconds'?value.toFixed(2):value.toLocaleString()):'未记录'));line.setAttribute('aria-label',policies[m.policy]+' '+(value??'未记录')+' '+spec.unit);chart.append(line)});charts.append(chart);
    }root.append(charts,node('p','Token = 输入＋输出；固定流程为 0。执行耗时不含 worker 装载；含装载的墙钟耗时和输入/输出拆分见下方原表。单次结果受缓存与执行顺序影响。','visual-caption'));
  }
  window.PapertrailVisuals={clear,candidateFlow,rankChanges,rankData,citationChain,chainData,evaluation};
})();
