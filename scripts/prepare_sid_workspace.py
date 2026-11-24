"""Expose frozen CPU diagnostics; never fit models in a web request."""
import json
from pathlib import Path
import shutil

import numpy as np
from gsearch.quality_protocol import save, digest

DEST = Path('deploy/stage43')


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding='utf-8', newline='\n')


def main() -> None:
    if DEST.exists():
        raise FileExistsError('New workspace already exists')
    shutil.copytree('deploy/stage41',DEST,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    report = json.loads(Path('reports/stage43/results.json').read_text(encoding='utf-8'))
    vectors = np.load('data/stage43-sid/input-vectors.npy',allow_pickle=False)
    vocabulary = json.loads(Path('data/stage43-sid/vectorizer.json').read_text(encoding='utf-8'))['vocabulary']
    names = [None]*len(vocabulary)
    for word,index in vocabulary.items():
        names[index] = word
    for i,paper in enumerate(report['papers']):
        order = np.argsort(-vectors[i],kind='stable')[:6]
        paper['keywords'] = [{'word':names[j],'weight':float(vectors[i,j])} for j in order if vectors[i,j]>0]
    report['source'] = {'name':'MiniOneRec optional CPU PRQ-KMeans','commit':'526306229326013a7ca46f5b2d8f55ea669aa159',
                        'url':'https://github.com/AkaliKong/MiniOneRec/tree/526306229326013a7ca46f5b2d8f55ea669aa159/sid_generation',
                        'input_note':'沿用标题与原摘要的 TF-IDF；教学变体，不是 Qwen 嵌入或论文效果复现。',
                        'shuffle_note':'冻结碰撞组；只在训练点赞频次桶内打乱单例论文与完整 SID 对应。码本、词表、树与 SID 多重集保持一致。'}
    save(DEST/'sid-lab.json',report)
    save(DEST/'sid-lab-receipt.json',{'sha256':digest(DEST/'sid-lab.json'),'results_sha256':digest(Path('reports/stage43/results.json')),
                                    'protocol_sha256':digest(Path('reports/stage43/protocol.json'))})
    shutil.copyfile('third_party/minionerec_sid_cpu/LICENSE',DEST/'web/vendor/LICENSE-minionerec.txt')
    main = (DEST/'web/main.mjs').read_text(encoding='utf-8')
    anchor = '</a></nav><div class="rail-divider"/>'
    replacement = '</a><a class="nav-item project-nav" href="/sid-lab.html"><${Icon} name="activity"/>SID 诊断实验<span>04</span></a></nav><div class="rail-divider"/>'
    assert main.count(anchor) == 1
    main = main.replace(anchor,replacement)
    anchor = '<span class="project-teaser-index">FIELD NOTES / 04</span>'
    # Preserve the prior project teaser; a separate entry gives the new experiment a clear destination.
    old = '</a>${searchForm}'
    new = '</a><a class="project-teaser sid-teaser" href="/sid-lab.html"><span class="project-teaser-index">EXPERIMENT / 01</span><span><strong>让 SID 的分组，接受一次对照。</strong><small>查看真实量化、碰撞、码本使用与打乱映射，沿着论文核对。</small></span><b aria-hidden="true">↗</b></a>${searchForm}'
    assert main.count(old) == 1
    write(DEST/'web/main.mjs',main.replace(old,new))
    project = (DEST/'web/minionerec.mjs').read_text(encoding='utf-8')
    old = '<section id="pipeline" class="project-section">'
    new = '<a class="sid-lab-entry" href="/sid-lab.html"><span>从概念到一次真实实验</span><strong>打开 CPU SID 诊断台 ↗</strong><small>162 篇论文 · 3 个拟合种子 · 60 次受控打乱</small></a><section id="pipeline" class="project-section">'
    assert project.count(old) == 1
    write(DEST/'web/minionerec.mjs',project.replace(old,new))
    with (DEST/'web/minionerec.css').open('a',encoding='utf-8') as stream:
        stream.write('\n.sid-lab-entry{display:flex;align-items:center;gap:25px;padding:21px 25px;margin-top:24px;border:1px solid #c5d5b1;border-radius:11px;background:#e6efda;color:#304d2b;text-decoration:none;font-size:12px}.sid-lab-entry strong{font-size:17px;font-weight:500}.sid-lab-entry small{margin-left:auto;font-size:11px}.sid-lab-entry:hover{background:#dcebc8}\n')
    run = Path('scripts/run_minionerec_local.py').read_text(encoding='utf-8')
    write(Path('scripts/run_sid_local.py'),run.replace('v41','v43').replace('deploy/stage41','deploy/stage43').replace('8787','8789').replace('from trialsite.minionerec import','from trialsite.sidlab import'))
    control = Path('scripts/minionerec_control.py').read_text(encoding='utf-8')
    write(Path('scripts/sid_control.py'),control.replace("ROOT=Path('.cache/stage41').resolve()","ROOT=Path('.cache/stage43').resolve()").replace('8787','8789').replace('scripts.run_minionerec_local','scripts.run_sid_local').replace('papertrail-minionerec.cmd','papertrail-sid.cmd').replace('private .cache/stage41/logs','private .cache/stage43/logs'))
    write(Path('papertrail-sid.cmd'),Path('papertrail-minionerec.cmd').read_text().replace('scripts.minionerec_control','scripts.sid_control'))
    print({'bundle':str(DEST),'frozen_fits':len(report['fits']),'papers':len(report['papers'])})


if __name__ == '__main__':
    main()
