"""Versioned HTML/display hooks for paper-first progressive disclosure."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=ROOT/'research76/lab.html';s=p.read_text(encoding='utf8')
    s=s.replace('<section class="task-bar"','<details id="task-settings" class="task-settings" open><summary>本次任务设置 <span id="compact-task">输入需求，核对检索词与画像后执行</span></summary><section class="task-bar"',1)
    s=s.replace('</section>\n<div class="run-strip">','</section></details>\n<div class="run-strip">',1)
    flow='<section id="candidate-flow" aria-label="实际候选流转图"><p class="visual-empty">等待本次工具返回。</p></section>'
    assert flow in s;s=s.replace(flow,'')
    before='<details class="raw"><summary>核对本次候选的来源、状态与原始字段</summary>'
    after='<details id="flow-details" class="flow-disclosure"><summary><span>候选流转</span><span id="flow-mini" class="flow-mini">等待真实工具返回</span><span class="disclosure-action">展开图形 ↗</span></summary>'+flow+'</details>'+before
    assert before in s;s=s.replace(before,after)
    reader='''<div class="result-tabs" role="group" aria-label="查看本次结果"><button type="button" id="show-abstract" aria-pressed="true">原摘要 <span id="read-count">0</span></button><button type="button" id="show-answer" aria-pressed="false">最终回答</button><button type="button" id="show-process">查看过程 ↗</button></div><div id="result-area" class="result-area" data-view="abstract"><section id="task-reader" aria-label="本次实际返回的原摘要"><p class="empty">模型成功读取摘要后，在这里阅读；不会补读或生成原文。</p></section><div id="answer"></div></div>'''
    target='<div id="execution-stages" class="execution-stages" aria-label="已记录流程"></div>'
    s=s.replace(target,reader+'<details id="timeline-details" class="process-disclosure"><summary>工具调用与实际过程 <span id="compact-process">尚无记录</span></summary>'+target,1)
    s=s.replace('<div id="answer"></div><section id="citation-chain"','</details><details id="citation-details" class="process-disclosure"><summary>核对引用证据链与完整来源</summary><section id="citation-chain"',1)
    s=s.replace('</section><p id="custom-result-boundary"','</section></details><p id="custom-result-boundary"',1)
    p.write_text(s,encoding='utf8')
    p=ROOT/'research76/lab.js';s=p.read_text(encoding='utf8')
    s=s.replace('function renderTimeline(row){visualRow=row;','function renderTimeline(row){visualRow=row;window.PapertrailWorkspace?.reader(row);',1)
    s=s.replace("function focusCitation(doc){", "function focusCitation(doc){$('citation-details').open=true;",1)
    s=s.replace("$('trace').textContent=JSON.stringify(row,null,2);", "$('trace').textContent=JSON.stringify(row,null,2);window.PapertrailWorkspace?.result(row);",1)
    s=s.replace("function clearAcceptedView(){", "function clearAcceptedView(){window.PapertrailWorkspace?.reset();",1)
    p.write_text(s,encoding='utf8')
    p=ROOT/'research76/candidate-ui.js';s=p.read_text(encoding='utf8')
    s=s.replace('function invalidateActual(message){','function invalidateActual(message){window.PapertrailWorkspace?.reset(message);',1)
    s=s.replace('function jumpTimeline(attempt){',"function jumpTimeline(attempt){$('timeline-details').open=true;",1)
    s=s.replace('function renderActual(value){','function renderActual(value){window.PapertrailWorkspace?.actual(value);',1)
    p.write_text(s,encoding='utf8');print('Step1 display adapters installed')


if __name__=='__main__':main()
