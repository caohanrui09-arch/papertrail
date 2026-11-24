"""Constrained changes to v39 copies; no old assets or learned scores are modified."""
from pathlib import Path
import shutil

ROOT=Path('deploy/stage40')
shutil.copyfile('reports/stage40/learning-paths.json',ROOT/'learning-paths.json')
path=ROOT/'trialsite/app.py'
text=Path('deploy/stage39/trialsite/app.py').read_text(encoding='utf-8')
assert 'def main():' in text and 'uvicorn.run(create_app(settings)' in text
path.write_text(text.replace('def main():','def main(factory=create_app):').replace('uvicorn.run(create_app(settings)','uvicorn.run(factory(settings)'),encoding='utf-8')
path=ROOT/'web/main.mjs'
text=Path('deploy/stage39/web/main.mjs').read_text(encoding='utf-8')

def change(old,new):
    global text
    if text.count(old)!=1:raise ValueError('Expected one UI anchor: '+old[:100])
    text=text.replace(old,new)

change("import {TopicGallery} from './topics.mjs';","import {TopicGallery} from './topics.mjs';\nimport {LearningPathIntro,LearningCardPrompt,LearningReaderPrompt} from './learning.mjs';")
change("if(spaceMode==='search'||view!=='work')return", "if(spaceMode==='search'||spaceMode==='guide'||view!=='work')return")
change(" function openSearch(){invalidate();setSpaceMode('search');setView('work');setReadingFocus(false);}",
       " function openSearch(){invalidate();setSpaceMode('search');setView('work');setReadingFocus(false);requestAnimationFrame(()=>document.getElementById('query')?.focus());}")
change(' async function search(e,override={})', ''' async function openGuide(nextTopic='generative'){
  invalidate();setTopic(nextTopic);setQ(meta.topics[nextTopic].core);setSpaceMode('guide');setView('work');setTab('read');setReadingFocus(false);setError('');setStatus('loading');
  const n=++seq.current,c=new AbortController();searchAbort.current=c;
  try{const value=await api('/api/learning-path/'+encodeURIComponent(nextTopic),c.signal);if(n===seq.current){setResult(value);setStatus(value.papers.length?'returned':'empty');}}
  catch(e){if(n===seq.current&&e.name!=='AbortError'){setError(e.message);setStatus('error');}}
 }
 async function search(e,override={})''')
text=text.replace("work&&spaceMode!=='search'?", "work&&spaceMode!=='search'&&spaceMode!=='guide'?")
text=text.replace("work&&spaceMode!=='search'&&html", "work&&spaceMode!=='search'&&spaceMode!=='guide'&&html")
change("RESEARCH STUDIO</i>","READING STUDIO</i>")
change("<${Icon} name=\"compass\"/>发现<span>01</span>","<${Icon} name=\"compass\"/>从这里开始<span>01</span>")
change("<${Icon} name=\"grid\"/>检索工作台<span>02</span>","<${Icon} name=\"grid\"/>自由搜索<span>02</span>")
change('<p class="rail-label">EXPLORE TOPICS</p>','<p class="rail-label">START WITH A QUESTION</p>')
change('onClick=${()=>choose(key,true)}','onClick=${()=>openGuide(key)}')
change("${spaceMode==='recommend'?'从你的收藏，找到下一篇'", "${spaceMode==='guide'?(result?.guide.title||'选一篇，带着问题读'):spaceMode==='recommend'?'从你的收藏，找到下一篇'")
change("${spaceMode==='search'?topics[topic].label:'当前浏览器画像'}", "${spaceMode==='guide'?'编辑入门路径':spaceMode==='search'?topics[topic].label:'当前浏览器画像'}")
change('<h1>沿着线索，<br/>发现<em>下一篇。</em></h1>', '<h1>读懂第一篇，<br/>找到<em>下一篇。</em></h1>')
change('从一个好问题，到一篇值得读的论文。<br/>让检索、兴趣与证据，在这里相遇。', '给搜广推与 Agent 初学者的论文阅读空间。<br/>先读原摘要，再用收藏找到下一篇。')
change('<div class="hero-proof">', '<div class="learning-entry"><button type="button" class="learning-start" onClick=${()=>openGuide(topic)}>开始入门阅读 <span aria-hidden="true">↗</span></button><button type="button" class="learning-search" onClick=${openSearch}>我已有问题，直接搜索</button></div><div class="hero-proof">')
change("const buttonLabel=busy?'正在检索…':status==='error'?'重试检索':work?'重新检索':'开始检索';", "const buttonLabel=busy?'正在加载…':status==='error'?(spaceMode==='guide'?'重试阅读路径':'重试检索'):spaceMode==='guide'?'搜索相关论文':work?'重新检索':'开始检索';")
change("onInput=${e=>{setQ(e.target.value);invalidate();}}", "onInput=${e=>{setQ(e.target.value);setSpaceMode('search');invalidate();}}")
change("onChange=${e=>{setMethod(e.target.value);invalidate();}}", "onChange=${e=>{setMethod(e.target.value);setSpaceMode('search');invalidate();}}")
change("onChange=${e=>{setContext(e.target.value);invalidate();}}", "onChange=${e=>{setContext(e.target.value);setSpaceMode('search');invalidate();}}")
change("onClick=${()=>{invalidate();setQ(meta.topics[topic].core);}}", "onClick=${()=>{setSpaceMode('search');invalidate();setQ(meta.topics[topic].core);}}")
change("研究空间 <span>/</span><strong>${work?'检索工作台':'发现'}", "论文阅读 <span>/</span><strong>${work?(spaceMode==='guide'?'入门阅读':'阅读工作台'):'从这里开始'}")
change('<form class="search-box" onSubmit=${search}', '<form class="search-box" onSubmit=${e=>{if(spaceMode===\'guide\'&&status===\'error\'){e.preventDefault();openGuide(topic);}else search(e);}}')
change("'找到论文，读到依据'}<span>。</span></h1>", "'找到论文，读到依据'}<span>${spaceMode==='guide'?'':'。'}</span></h1>")
change('<div class="search-options">','<details class="search-settings"><summary>调整搜索方式</summary><div class="search-options">')
change('恢复核心主题 ↗</button></div>${work?', '恢复核心主题 ↗</button></div></details>${work?')
change("status==='returned'?'候选已返回。相关性需要结合原摘要判断。'", "status==='returned'?(spaceMode==='guide'?'这是编辑阅读顺序，可跳读。先带着问题看摘要。':'候选已返回。相关性需要结合原摘要判断。')")
change("${spaceMode==='recommend'?'为你推荐'", "${spaceMode==='guide'?'建议阅读顺序':spaceMode==='recommend'?'为你推荐'")
change('<p class="result-note">','<${LearningPathIntro} guide=${result.guide}/><p class="result-note">')
change("${p.explanation?'内容相近':spaceMode==='saved'?'已收藏':'已屏蔽'}", "${p.learning?'编辑导读':p.explanation?'内容相近':spaceMode==='saved'?'已收藏':'已屏蔽'}")
change('<${PaperMetadata} paper=${p} previews=${previews}/><${AbstractPreview}', '<${PaperMetadata} paper=${p} previews=${previews}/><${LearningCardPrompt} learning=${p.learning}/><${AbstractPreview}')
change('<div class="abstract-heading"><span>摘要</span>', '<${LearningReaderPrompt} learning=${selected?.learning}/><div class="abstract-heading"><span>摘要</span>')
change("if(t.tool==='个人内容推荐')", "if(t.tool==='编辑阅读路径')return '原摘要核验的编辑阅读顺序 · 可跳读 · 未参与搜索或推荐排序';if(t.tool==='个人内容推荐')")
change('<${TopicGallery} onChoose=${choose} motion=${motion}/>', '<${TopicGallery} onChoose=${openGuide} motion=${motion}/>${searchForm}')
# Move the existing search form after the path choices on the homepage; keep it in the workbench.
start=text.index('<form class="search-box"');end=text.index('</form>',start)+len('</form>')
form=text[start:end]
text=text[:start]+'${work?searchForm:null}'+text[end:]
anchor=' return html`<div ref=${root}'
change(anchor, ' const searchForm=html`'+form+'`;\n'+anchor)
change('发现之后，记得读原文。','先抓住问题，再决定要不要继续读。')
change('<h3>好线索，值得读下去。</h3>', "<h3>${spaceMode==='guide'?'先选一篇，带着问题读':'好线索，值得读下去。'}</h3>")
change('每篇候选都可以打开原始摘要，核对论文 ID、版本与来源。', '读懂一句关键想法，收藏感兴趣的论文，再到“我的推荐”寻找关联。')
change('当前是小范围试用目录，共', '这里主要帮助搜广推与 Agent 初学者选择起读论文。当前先覆盖检索、冷启动和评价三个专题，并非完整 Agent 课程。阅读路径是基于原摘要整理的编辑建议，不是难度评分或真人效果证明。当前目录共')
# Native details avoids new overlay/component dependencies. Keep input labels and behavior intact.
path.write_text(text,encoding='utf-8')
topics=ROOT/'web/topics.mjs'
text=Path('deploy/stage39/web/topics.mjs').read_text(encoding='utf-8')
text=text.replace('THE RESEARCH COLLECTION','YOUR FIRST READING PATH').replace('换一条线索，发现新方向','选一个问题，开始第一篇')
text=text.replace(' 个研究专题',' 条路径 · 每条 3 篇').replace("'探索'+t.title+'论文'","'开始'+t.title+'阅读路径'")
text=text.replace('探索论文 <span','开始阅读 <span').replace('三种视角，同一个出发点：读到值得读的论文。','编辑建议：先看摘要，再决定是否深入全文。')
topics.write_text(text,encoding='utf-8')
index=ROOT/'web/index.html'
text=Path('deploy/stage39/web/index.html').read_text(encoding='utf-8').replace('<title>Papertrail — 我的论文兴趣空间</title>','<title>Papertrail — 从第一篇开始</title>')
text=text.replace('探索主题，阅读原摘要，追溯每一次检索。','面向搜广推与Agent初学者，从编辑阅读路径开始，阅读原摘要并建立自己的兴趣。')
text=text.replace('<script type="importmap">','<link rel="stylesheet" href="/learning.css"><script type="importmap">')
index.write_text(text,encoding='utf-8')
shutil.copyfile('deploy/stage39/web/reading.mjs',ROOT/'web/reading.mjs')
