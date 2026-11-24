"""Independent supplement; preserve the sealed stage40 and all catalog bytes."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path('deploy/stage41')


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8', newline='\n')


def main() -> None:
    if ROOT.exists():
        raise ValueError('Do not overwrite an existing supplement bundle')
    shutil.copytree('deploy/stage40', ROOT, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    sources = json.loads(Path('reports/stage41/sources.json').read_text(encoding='utf-8'))
    acquired = json.loads(Path('reports/stage41/papers.json').read_text(encoding='utf-8'))
    assert acquired['error'] is None
    raw = Path(acquired['requests'][0]['raw_path'])
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == acquired['requests'][0]['raw_sha256']
    shutil.copyfile(raw, ROOT/'project-original.atom')
    papers = []
    guides = {
        '2305.05065': ('TIGER', '先理解 Semantic ID', '跟随摘要找出：物品内容怎样变成多层码字，模型为什么可以直接生成下一物品的标识？', 'We use a hierarchical method called RQ-VAE to generate these codewords.'),
        '2510.24431': ('MiniOneRec', '再看端到端框架', '把 SID 构建、监督微调、推荐强化学习连起来；分清论文报告的实验和本站实际实现。', 'spanning SID construction, supervised fine-tuning, and recommendation-oriented reinforcement learning'),
        '2510.12211': ('ReRe', '最后理解 RL 的难点', '为什么无效或重复物品会浪费采样？为什么只有命中与否的奖励不够细？', 'ranking supervision is sparse since most items receive identical zero rewards.'),
    }
    for row in acquired['records']:
        name, step, question, evidence = guides[row['doc_id']]
        assert evidence in row['abstract']
        papers.append({k: row[k] for k in ['doc_id', 'title', 'abstract', 'version', 'source_url', 'published_at', 'authors']} |
                      {'name': name, 'step': step, 'question': question, 'evidence': evidence,
                       'version_key': 'arxiv:'+row['doc_id']+'v1', 'source_verified': True})
    project = {'slug': 'minionerec', 'title': 'MiniOneRec', 'editorial': True,
               'scope': 'independent_educational_supplement', 'as_of': '2026-11-02',
               'historic_catalog_admission': False, 'model_trained_here': False,
               'repository': 'https://github.com/AkaliKong/MiniOneRec',
               'commit': sources['commit'], 'license': 'Apache-2.0',
               'raw_sha256': acquired['requests'][0]['raw_sha256'], 'papers': papers,
               'code': sources['files']}
    write(ROOT/'project.json', json.dumps(project, ensure_ascii=False, indent=2)+'\n')
    text = (ROOT/'web/main.mjs').read_text(encoding='utf-8')
    old = '</nav><div class="rail-divider"/>'
    new = '<a class="nav-item project-nav" href="/minionerec.html"><${Icon} name="spark"/>MiniOneRec 导读<span>03</span></a></nav><div class="rail-divider"/>'
    assert text.count(old) == 1
    text = text.replace(old, new)
    old = '<${TopicGallery} onChoose=${openGuide} motion=${motion}/>${searchForm}'
    new = '<${TopicGallery} onChoose=${openGuide} motion=${motion}/><a class="project-teaser" href="/minionerec.html"><span class="project-teaser-index">FIELD NOTES / 04</span><span><strong>MiniOneRec：下一篇推荐，也可以逐词生成。</strong><small>从 SID 到 SFT、强化学习，沿着论文与源码读懂生成式推荐。</small></span><b aria-hidden="true">↗</b></a>${searchForm}'
    assert text.count(old) == 1
    write(ROOT/'web/main.mjs', text.replace(old, new))
    index = (ROOT/'web/index.html').read_text(encoding='utf-8')
    write(ROOT/'web/index.html', index.replace('<script type="importmap">','<link rel="stylesheet" href="/project-entry.css"><script type="importmap">'))
    launch = Path('scripts/run_learning_local.py').read_text(encoding='utf-8')
    write(Path('scripts/run_minionerec_local.py'), launch.replace('v40','v41').replace('deploy/stage40','deploy/stage41').replace('8785','8787').replace('from trialsite.learning import','from trialsite.minionerec import'))
    control = Path('scripts/learning_control.py').read_text(encoding='utf-8')
    write(Path('scripts/minionerec_control.py'), control.replace("ROOT=Path('.cache/stage40').resolve()", "ROOT=Path('.cache/stage41').resolve()").replace('8785','8787').replace('scripts.run_learning_local','scripts.run_minionerec_local').replace('papertrail-learn.cmd','papertrail-minionerec.cmd').replace('private .cache/stage40/logs','private .cache/stage41/logs'))
    write(Path('papertrail-minionerec.cmd'), Path('papertrail-learn.cmd').read_text().replace('scripts.learning_control','scripts.minionerec_control'))
    print({'bundle': str(ROOT), 'papers': len(papers), 'catalog_unchanged': True})


if __name__ == '__main__':
    main()
