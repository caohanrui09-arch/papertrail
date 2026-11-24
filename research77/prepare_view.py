"""Narrow source presentation transforms; no handlers, algorithms or schemas changed."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent


def main():
    p=ROOT/'web/main-experience.mjs';s=p.read_text(encoding='utf8')
    start=s.index(':html`<div class="hero-copy"');end=s.index('<div data-reveal><${HeroArt}/></div>`}',start)
    s=s[:start]+''':html`<div class="hero-copy" data-reveal><h1>读懂第一篇，<br/>找到<em>下一篇。</em></h1><p>搜索论文，读原摘要，找到下一篇。</p><div class="learning-entry"><button type="button" class="learning-start learning-search" onClick=${openSearch}>开始探索 <span aria-hidden="true">↗</span></button></div></div>'''+s[end:]
    caption='<div class="art-caption"><span class="tiny-cross">+</span> IDEAS IN ORBIT <span>01—03</span></div>'
    s=s.replace(caption,'',1).replace('<div class="art-foot"><span>检索 → 发现 → 阅读</span><small>图形示意</small></div>','',1)
    s=re.sub(r' <rect x="292"[\s\S]*?PAPER 01</text>','',s,count=1)
    s=s.replace('${!work?html`<${TaskPreview}/>', '${!work?html`<section class="discovery-next"><h2>继续探索</h2><div class="discovery-shortcuts"><button type="button" onClick=${()=>openGuide(topic)}>入门阅读 ↗</button><a href="#task-preview">查看 Agent 示例 ↓</a></div></section><${TaskPreview}/>',1)
    s=s.replace('<${Icon} name="info" size=${17}/>关于此空间','<${Icon} name="info" size=${17}/>说明',1)
    p.write_text(s,encoding='utf8')
    p=ROOT/'web/index.html';s=p.read_text(encoding='utf8').replace('/main-experience76.mjs?v=76.1','/main-experience77.mjs?v=77.1').replace('</head>','<link rel="stylesheet" href="/first-view77.css?v=77.1"></head>');p.write_text(s,encoding='utf8')
    p=ROOT/'lab.html';s=p.read_text(encoding='utf8')
    s=s.replace('</head>','<link rel="stylesheet" href="/first-view77.css?v=77.1"><script src="/first-view77.js?v=77.1" defer></script></head>')
    s=s.replace('<p class="eyebrow">ALGORITHMS × AGENT / 01</p>','').replace('<h1>看见结果，<span>也看见选择。</span></h1>','<h1>想找什么论文？</h1>').replace('从候选排名到工具调用，让每一次论文发现都有迹可循。','把问题交给 Agent，沿原摘要找到依据。')
    s=s.replace('<aside class="scope">','<details class="intro-scope"><summary>范围与运行说明</summary><aside class="scope">',1).replace('</aside></div>','</aside></details></div>',1)
    s=s.replace('<div class="input-modes" role="group" aria-label="任务来源">','<details class="task-source-options"><summary>任务来源选项</summary><div class="input-modes" role="group" aria-label="任务来源">',1).replace('</div><div id="custom-composer"','</div></details><div id="custom-composer"',1)
    s=s.replace('<label for="custom-need">你想找什么论文？</label>','<label class="sr-only" for="custom-need">论文需求</label>').replace('placeholder="例如：帮我找多模态快慢思考的论文，并引用原摘要。"','placeholder="描述主题、问题或推荐需求"').replace('<label>推荐画像<select','<label>推荐画像（示例）<select').replace('>整理需求与检索词</button>','>核对需求</button>',1)
    scope=re.search(r'<p id="custom-scope"[\s\S]*?</p>',s).group();boundary=re.search(r'<p class="boundary" id="task-boundary"[\s\S]*?</p>',s).group()
    s=s.replace(scope,'',1).replace(boundary,'<details id="scope-info" class="scope-info"><summary>目录与画像范围</summary>'+scope+boundary+'</details>',1)
    s=s.replace('输入问题后，先核对实际执行的检索词。','').replace('输入需求，核对检索词与画像后执行','')
    s=s.replace('<div class="workspace">','<details id="workspace-shell" class="workspace-shell"><summary>查看候选、阅读结果与历史记录</summary><div class="workspace">',1)
    s=s.replace('<details id="task-export"','</details><details id="task-export"',1)
    s=s.replace('<section class="research-panel">','<details class="research-options"><summary>历史实验与证据</summary><section class="research-panel">',1).replace('<footer>Papertrail / Algorithm','</details><footer>Papertrail / Algorithm',1)
    p.write_text(s,encoding='utf8')
    p=ROOT/'custom-ui.js';s=p.read_text(encoding='utf8').replace('整理需求与检索词','核对需求').replace('需求或画像已变更，请重新整理并核对方案。','请核对当前需求。').replace('原问题尚未整理，或已经修改。','需求已修改。')
    s=s.replace("p.label+` · ${p.history_size}篇历史`", "p.id==='cold'?'无阅读历史':p.label")
    p.write_text(s,encoding='utf8')
    p=ROOT/'handoff-ui.js';s=p.read_text(encoding='utf8')
    old="holder.append(el('strong','已从论文工作台接入需求 · 尚未执行'),"
    assert old in s;s=s.replace(old,"const sourceDetails=el('details');sourceDetails.append(el('summary','查看原问题、检索词与来源范围'));holder.append(el('strong','需求已带入 · 尚未执行'),el('p','确认画像与范围后继续。'),sourceDetails);sourceDetails.append(",1)
    s=s.replace("holder.append(el('p','已把来源筛选", "sourceDetails.append(el('p','已把来源筛选",1).replace('holder.append(details);','sourceDetails.append(details);',1)
    p.write_text(s,encoding='utf8');print('First-view presentation prepared')


if __name__=='__main__':main()
