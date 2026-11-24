"""Apply narrow display hooks to versioned copies; no tool/schema/budget changes."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def edit(name, changes):
    path=ROOT/'research74'/name
    value=path.read_text(encoding='utf8')
    for old,new in changes:
        assert old in value, (name,old[:80])
        value=value.replace(old,new)
    path.write_text(value,encoding='utf8')


def main():
    assets='<link rel="stylesheet" href="/visuals.css?v=74.1"><script src="/visuals/vendor/d3-path.min.js" defer></script><script src="/visuals/vendor/d3-shape.min.js" defer></script><script src="/visuals.js?v=74.1" defer></script>'
    edit('lab.html',[
        ('<script src="/live-events.js',assets+'<script src="/live-events.js'),
        ('/candidate-ui.js?v=72.1','/candidate-ui.js?v=74.1'),('/lab.js?v=72.1','/lab.js?v=74.1'),
        ('<div id="actual-candidates">','<section id="candidate-flow" aria-label="实际候选流转图"><p class="visual-empty">等待本次工具返回。</p></section><div id="actual-candidates">'),
        ('<div class="method-tabs" id="methods"','<section id="rank-flow" aria-label="共享池排名变化图"><p class="visual-empty">运行独立诊断后，展示同池重排名次。</p></section><div class="method-tabs" id="methods"'),
        ('<div id="answer"></div>','<div id="answer"></div><section id="citation-chain" aria-label="引用证据链"><p class="visual-empty">完成实际读取与提交后，在这里核对来源。</p></section>'),
    ])
    edit('server.py',[
        ("    @app.get('/lab/presets')",'''    @app.get('/visuals.js')
    def visuals_script():return FileResponse(ROOT/'research74/visuals.js',media_type='text/javascript')
    @app.get('/visuals.css')
    def visuals_style():return FileResponse(ROOT/'research74/visuals.css',media_type='text/css')
    @app.get('/visuals/vendor/{filename}')
    def visual_vendor(filename:str):
        if filename not in ('d3-path.min.js','d3-shape.min.js'):raise HTTPException(404,'Unknown visualization asset')
        return FileResponse(ROOT/'research74/vendor'/filename,media_type='text/javascript')
    @app.get('/lab/presets')''')
    ])
    edit('candidate-ui.js',[
        ('function invalidateActual(message){',"function invalidateActual(message){PapertrailVisuals.clear($('candidate-flow'),message);PapertrailVisuals.clear($('citation-chain'),message);visualRow=null;"),
        ('function invalidateCandidateContext(message){',"function invalidateCandidateContext(message){PapertrailVisuals.clear($('rank-flow'),'输入已变更，等待当前查询的独立诊断。');"),
        ("n.querySelector('details').open=true", "n.tabIndex=-1;n.focus({preventScroll:true});const d=n.querySelector('details');if(d)d.open=true"),
        ('function renderActual(value){',"function renderActual(value){PapertrailVisuals.candidateFlow($('candidate-flow'),value,{paper:focusActual,call:jumpTimeline,citation:focusCitation});"),
        ('function renderRanks(){if(!rankings)return;',"function renderRanks(){if(!rankings)return;PapertrailVisuals.rankChanges($('rank-flow'),rankings,{paper:focusDiagnostic});"),
        ('async function loadRanks(){',"async function loadRanks(){PapertrailVisuals.clear($('rank-flow'),'等待本次诊断；不沿用旧名次。');"),
    ])
    edit('lab.js',[
        ("const intents=", "let visualRow=null;\nfunction focusCitation(doc){const n=[...document.querySelectorAll('.citation-chain-card')].find(n=>n.dataset.docId===doc);if(n){n.open=true;n.scrollIntoView({block:'center',behavior:'instant'});n.querySelector('summary').focus({preventScroll:true})}else $('citation-chain').scrollIntoView({block:'center',behavior:'instant'})}\nfunction focusDiagnostic(doc){selectedMethod='profile_rerank';renderRanks();const n=[...document.querySelectorAll('.diagnostic-paper')].find(n=>n.dataset.docId===doc);if(n){n.tabIndex=-1;n.scrollIntoView({block:'center',behavior:'instant'});n.focus({preventScroll:true})}}\nconst intents="),
        ('function renderTimeline(row){', 'function renderTimeline(row){visualRow=row;'),
        ("function renderAnswer(answer){$('answer').replaceChildren();", "function renderAnswer(answer){PapertrailVisuals.citationChain($('citation-chain'),visualRow?{...visualRow,answer}:null,resultContext||{description:$('task-description').textContent},{call:jumpTimeline,paper:focusActual});$('answer').replaceChildren();"),
        ('renderAnswer(row.answer);renderTimeline(row);','renderTimeline(row);renderAnswer(row.answer);'),
    ])
    edit('site.py',[
        ("root/'research74/evaluation.css'", "root/'research73/evaluation.css'"),
        ("    @app.get('/api/evaluation/protocol')", """    @app.get('/visuals/v74/evaluation/tasks')
    def visual_task_contexts():
        tasks=read(DATA/'inputs/agent-tasks.json')
        return {'version':74,'evaluation_stage':73,'tasks':[{k:t.get(k) for k in ('id','intent','original_need','query','at')} for t in tasks],
                'scope':'read-only task context for the frozen stage73 result display; no new evaluation'}
    @app.get('/api/evaluation/protocol')"""),
    ])
    edit('evaluation.html',[
        ('<script src="/evaluation.js" defer>',assets+'<script src="/evaluation.js?v=74.1" defer>'),
        ('<div id="agent-summary"', '<section id="evaluation-visuals" aria-label="冻结任务协议结果矩阵及成本图"></section><div id="agent-summary"'),
    ])
    edit('evaluation.js',[
        ("function el(tag", "let visualTaskContexts={};\nfunction locateCell(cell){const n=[...document.querySelectorAll('#agent-cells .cell')].find(n=>n.dataset.cell===cell);if(n){n.querySelector('details').open=true;n.tabIndex=-1;n.focus({preventScroll:true});n.scrollIntoView({block:'center',behavior:'instant'});n.classList.add('visual-located');setTimeout(()=>n.classList.remove('visual-located'),1600)}}\nfunction el(tag"),
        ("const raw=el('details');", "const chain=el('section');PapertrailVisuals.citationChain(chain,v.result,visualTaskContexts[v.result.task_id]||{},{call:attempt=>{const n=[...list.children].find(n=>n.dataset.attempt===String(attempt));if(n){n.querySelector('details').open=true;n.tabIndex=-1;n.focus();n.scrollIntoView({block:'center',behavior:'instant'})}}});box.append(chain);const raw=el('details');"),
        ("const n=el('li');n.append", "const n=el('li');n.dataset.attempt=String(e.attempt);n.append"),
        ("const [v,p]=await Promise.all([get('/api/evaluation/summary'),get('/api/evaluation/protocol')]);", "const [v,p,context]=await Promise.all([get('/api/evaluation/summary'),get('/api/evaluation/protocol'),get('/visuals/v74/evaluation/tasks')]);visualTaskContexts=Object.fromEntries(context.tasks.map(t=>[t.id,{original_need:t.original_need,executed_query:t.query}]));PapertrailVisuals.evaluation($('evaluation-visuals'),v.agent,{cell:locateCell});"),
    ])
    print('Versioned presentation hooks installed')


if __name__=='__main__':main()
