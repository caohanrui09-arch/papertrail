"""Read-only delivery check; one-time seal runs actual CLI and historical checks."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import unittest
from gsearch.quality_protocol import digest,save
from gsearch.portfolio_evidence import collect,markdown,REPORT
from gsearch.portfolio_demo import ROOT,validate_run
from gsearch.showcase import verify_receipt

DOCS=['docs/DELIVERY_GUIDE.md','docs/ALGORITHM_EVIDENCE_2026.md','docs/RESUME_2026.md','docs/INTERVIEW_2026.md']
CODE=['gsearch/portfolio_demo.py','gsearch/portfolio_evidence.py','scripts/verify_portfolio_delivery.py',
    'portfolio-demo.cmd','portfolio-check.cmd']
RECEIPT=REPORT/'final-validation.json'


def check_links() -> int:
    count=0;project=Path.cwd().resolve()
    for name in DOCS:
        for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)',Path(name).read_text(encoding='utf-8')):
            if link.startswith(('https:','http:','#')):continue
            target=(Path(name).parent/link.split('#')[0]).resolve()
            if not target.is_relative_to(project) or not target.is_file():raise ValueError('Broken local document link: '+link)
            count+=1
    return count


def check_evidence() -> int:
    evidence=json.loads((REPORT/'evidence-index.json').read_text(encoding='utf-8'))
    if evidence!=collect():raise ValueError('Source fact or hash drift')
    if markdown(evidence)!=Path(DOCS[1]).read_text(encoding='utf-8'):raise ValueError('Generated evidence table differs')
    if evidence['claims']['agent.invalid_v1_used']['value'] is not False:raise ValueError('Invalid v1 used')
    return len(evidence['claims'])


def actual_cli(log: Path,arguments: list[str],expected: int) -> Path:
    from scripts.manage_stage17_env import environment
    before=set(ROOT.glob('run-*/result.json'))
    with log.open('w',encoding='utf-8') as stream:
        process=subprocess.run(['cmd.exe','/c','portfolio-demo.cmd']+arguments,env=environment(),
            stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,timeout=240,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    after=set(ROOT.glob('run-*/result.json'))-before
    if len(after)!=1 or process.returncode!=expected:raise ValueError('Actual CLI output/exit mismatch')
    path=next(iter(after));raw=json.loads(path.read_text(encoding='utf-8'))
    if (raw['validation']['status']=='passed')!=(expected==0):raise ValueError('CLI falsely reports demonstration completion')
    return path


def seal() -> None:
    if RECEIPT.exists():raise ValueError('Already sealed; use --check')
    claims=check_evidence();links=check_links()
    logs=Path('.cache/stage22');logs.mkdir(parents=True,exist_ok=True)
    from scripts.verify_isolated_delivery import SchemaCleanupResult
    with (logs/'regression-tests.log').open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
        suite=unittest.TextTestRunner(stream=stream,resultclass=SchemaCleanupResult).run(unittest.defaultTestLoader.discover('tests'))
    if not suite.wasSuccessful():raise ValueError('Regression failed; see private log')
    from gsearch.benchmark_cold_fusion import history
    history();counts={}
    groups={15:('code','data','outputs','report'),16:('code','materials','outputs','private_data','report'),
        17:('code','docs','outputs','report','private_replay_assets'),18:('code','docs','outputs','report'),
        19:('code','outputs','private_data','docs','report'),20:('code','vendor','outputs','private_data','docs','report')}
    for stage,fields in groups.items():counts[str(stage)]=verify_receipt(Path(f'reports/stage{stage}/final-validation.json'),fields)
    fields21=('code','outputs','private_data','invalidated_v1_assets','docs','report')
    counts['21-isolated']=verify_receipt(Path('reports/stage21-isolated/final-validation.json'),fields21)
    from gsearch.relocated_demo import verify_bundle
    from scripts.manage_stage17_env import BASE,VENV,environment
    bundle=verify_bundle(BASE/'replica')
    probe=subprocess.run([str(VENV/'Scripts/python.exe'),'-E','-s','-c',
        "import json,importlib.metadata as m;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"],
        env=environment(),capture_output=True,text=True,check=True)
    versions=json.loads(probe.stdout)
    if versions!=json.loads(Path('reports/stage17/runtime-versions.json').read_text())['installed_versions']:
        raise ValueError('CPU packages changed')
    passed=actual_cli(logs/'actual-cli.log',[],0)
    raw=json.loads(passed.read_text(encoding='utf-8'));validate_run(raw['run'])
    # Fixed sentinel tests incomplete presentation reporting; not an evaluation task.
    failed=actual_cli(logs/'empty-search-cli.log',['--query','stage22demonomatch31bcb62d9ac54439ac8c820f15794012'],1)
    negative=json.loads(failed.read_text(encoding='utf-8'))
    if negative['run']['trace']['trace'][0]['result']['papers']:raise ValueError('Sentinel unexpectedly matched')
    from gsearch.metadata_fetch import upstream
    from gsearch.paper_identity import arxiv_identity
    rows={r['doc_id']:r for r in json.loads(Path('data/stage13-expansion/documents.json').read_text(encoding='utf-8'))}
    originals=[]
    for event in raw['run']['trace']['trace']:
        if event['tool']!='read_paper':continue
        original=event['result'];row=rows[original['doc_id']];source=Path(row['provenance']['raw_path'])
        if digest(source)!=row['provenance']['raw_sha256']:raise ValueError('Original raw response changed')
        matches=[p for p in upstream()._feed.parse(source.read_bytes()).results if arxiv_identity(p.entry_id)==(original['doc_id'],1)]
        if len(matches)!=1 or original['abstract']!=matches[0].summary or original['title']!=matches[0].title:
            raise ValueError('Original native parser differs')
        originals.append(original['doc_id'])
    from gsearch.human_quality import load_state
    queries,mapping,runs,labels,confirmed=load_state()
    if labels or confirmed:raise ValueError('Human preparation changed; review scope')
    acceptance={'status':'passed','regression_tests':suite.testsRun,'failures':0,'errors':0,
        'source_claims_recounted':claims,'local_document_links':links,'stages3_21_unchanged':True,
        'historical_asset_counts':counts,'migrated_assets_unchanged':len(bundle['files']),
        'independent_cpu_packages_unchanged':len(versions),'actual_full_cli':str(passed),'actual_cli_exit_code':0,
        'actual_tool_chain':['search_papers','recommend_papers','read_paper','read_paper','finalize'],
        'original_v1_ids_independently_reparsed':originals,'llm_calls':0,'negative_cli':str(failed),
        'incomplete_demo_exit_code':1,'no_silent_fallback':True,'human_labels':0,
        'new_quality_experiments_or_training':False,'physical_second_machine_tested':False}
    save(REPORT/'acceptance.json',acceptance)
    report=Path('reports/阶段22_项目交付与简历证据.md')
    report.write_text(f'''# 第二十二阶段：项目交付与简历证据

四项授权均已完成：完整固定流程演示、算法证据索引、架构/复现/面试材料、可核验简历条目。入口见[交付导航](../docs/DELIVERY_GUIDE.md)。

真实portfolio-demo.cmd成功exit0：搜索→训练画像推荐→两篇不同原v1摘要读取→ID/版本/链接/原摘录最终提交，共5次工具，LLM调用0。用户和默认已知标题查询按训练信息固定hash选择，不读未来反馈、不按排名成败重挑。负向空搜索完整演示exit1并保留全部轨迹，未以部分引用冒充完整链路；不是新质量评测。

{claims}项事实从旧冻结JSON直接提取，含源路径/JSON Pointer/SHA；生成式SciFact、万篇推荐、统一BM25服务和Agent对照边界明确，内容/fixed默认不变。新增[证据表](../docs/ALGORITHM_EVIDENCE_2026.md)、[简历](../docs/RESUME_2026.md)、[面试讲解](../docs/INTERVIEW_2026.md)，旧阶段16文档保留。

{suite.testsRun}回归、{links}个本地文档链接、两篇原v1原生重解析、阶段3—21冻结检查、481迁移资产及57包核对通过。阶段21作废首批资产完整性也复核，不将其指标作为有效比较。真实第二台机器、人工相关性、独立新反馈/CTR/生产QPS仍未验证，真人标签0。

本轮复用已有fixed/ToolClient、原服务控制器、choose_user及安全原文字面展示，不重写算法或Agent循环；属于既有成果离线整理与接口薄适配，沿用已有GitHub/许可审计，无新增依赖、训练、调参或发布。报告与个人轨迹分开：私有输出仍在忽略data/.cache，不创建可分发的私有数据压缩包。

本轮初读两处历史收据/报告文件名猜错，随后用rg/实际history入口定位；未更改源资产。展示器在验收前补充错误响应的字面呈现分支，失败轨迹保持原样。完整收据见[final-validation.json](stage22/final-validation.json)，后续portfolio-check.cmd只读校验，不覆盖本次封存。
''',encoding='utf-8')
    old_receipts=[Path(f'reports/stage{n}/final-validation.json') for n in range(15,21)]+[Path('reports/stage21-isolated/final-validation.json')]
    value={'status':'complete','default_workflow':'fixed','default_recommendation':'content','source_claims':claims,
        'regression_tests':suite.testsRun,'new_quality_claims':False,'public_or_external_publish_performed':False,
        'code':{p:digest(Path(p)) for p in CODE},'docs':{p:digest(Path(p)) for p in DOCS},
        'outputs':{str(p):digest(p) for p in REPORT.glob('*.json') if p!=RECEIPT},
        'report':{str(report):digest(report)},'previous_receipts':{str(p):digest(p) for p in old_receipts},
        'private_data':{str(p):digest(p) for root in (ROOT,logs) for p in root.rglob('*') if p.is_file()}}
    save(RECEIPT,value)
    print(json.dumps({'status':'complete','receipt_sha256':digest(RECEIPT),'tests':suite.testsRun,'claims':claims}),flush=True)


def check() -> None:
    count=verify_receipt(RECEIPT,('code','docs','outputs','report','previous_receipts','private_data'))
    claims=check_evidence();links=check_links()
    print(json.dumps({'status':'passed','sealed_assets':count,'source_claims':claims,'local_links':links,
        'scope':'read-only delivery/source check; not a full historical prediction re-evaluation or new-machine install'}),flush=True)


def main() -> None:
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--seal',action='store_true');mode.add_argument('--check',action='store_true');args=parser.parse_args()
    seal() if args.seal else check()


if __name__=='__main__':main()
