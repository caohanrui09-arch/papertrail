"""Adapt only the new copied bundle and create one unambiguous entry point."""
from pathlib import Path

ROOT=Path('deploy/stage52')


def replace_once(path: Path,old: str,new: str) -> None:
    text=path.read_text(encoding='utf-8')
    assert text.count(old)==1,(str(path),old)
    path.write_text(text.replace(old,new),encoding='utf-8',newline='\n')


def main() -> None:
    if Path('papertrail.cmd').exists():raise FileExistsError('Preserve launch entry')
    main=ROOT/'web/main.mjs'
    replace_once(main,'SID 诊断实验<span>04</span></a>',
        'SID 结构诊断<span>04</span></a><a class="nav-item project-nav" href="/evidence.html"><${Icon} name="activity"/>实验与证据<span>05</span></a>')
    replace_once(main,'${searchForm}<div class="bottom-note"',
        '<a class="project-teaser evidence-teaser" href="/evidence.html"><span class="project-teaser-index">EVIDENCE / 2026.11</span><span><strong>让结果，决定下一步。</strong><small>162 篇网页目录 · 9,000 篇离线实验 · 可核验的结果与取舍</small></span><b aria-hidden="true">↗</b></a>${searchForm}<div class="bottom-note"')
    replace_once(ROOT/'web/minionerec.mjs','本站推荐仍使用内容方法，尚未训练或接入 MiniOneRec 模型。',
        '本站推荐仍使用内容方法；已完成独立 T5＋SID 受控实验并收尾，不是官方 MiniOneRec 完整模型复现。')
    replace_once(ROOT/'web/minionerec.mjs','<section id="pipeline" class="project-section">',
        '<a class="sid-lab-entry" href="/evidence.html"><span>最新实验结论</span><strong>9,000 篇受控训练与证据 ↗</strong><small>查看完整分母、频率参照与停止加量理由</small></a><section id="pipeline" class="project-section">')
    replace_once(ROOT/'web/sid-lab.html','<body><div id="app">',
        '<body><aside class="snapshot-banner">历史结构快照 · 162 篇 CPU 诊断 <a href="/evidence.html">查看 9,000 篇 SFT 与最新收尾结论 ↗</a></aside><div id="app">')
    with (ROOT/'web/sid-lab.css').open('a',encoding='utf-8') as f:
        f.write('\n.snapshot-banner{display:flex;justify-content:center;gap:24px;flex-wrap:wrap;padding:12px 25px;background:#e6eddf;color:#314e30;font-size:13px;border-bottom:1px solid #bfccb7}.snapshot-banner a{font-weight:600;text-underline-offset:4px}\n')
    run=Path('scripts/run_sid_local.py').read_text(encoding='utf-8')
    run=run.replace('v43','v52').replace('deploy/stage43','deploy/stage52').replace('8789','8791').replace('from trialsite.sidlab import','from trialsite.delivery import')
    Path('scripts/run_demo_delivery_local.py').write_text(run,encoding='utf-8')
    control=Path('scripts/sid_control.py').read_text(encoding='utf-8')
    control=control.replace('.cache/stage43','.cache/stage52').replace('8789','8791').replace('scripts.run_sid_local','scripts.run_demo_delivery_local').replace('papertrail-sid.cmd','papertrail.cmd')
    Path('scripts/demo_delivery_control.py').write_text(control,encoding='utf-8')
    Path('papertrail.cmd').write_text('@echo off\nsetlocal\ncd /d "%~dp0"\n".cache\\stage17\\runtime\\Scripts\\python.exe" -E -s -m scripts.demo_delivery_control %*\nexit /b %errorlevel%\n',encoding='ascii')
    print({'entry':'papertrail.cmd','url':'http://127.0.0.1:8791','previous_files_preserved':True})


if __name__=='__main__':main()
