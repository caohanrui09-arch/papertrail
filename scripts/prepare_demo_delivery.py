"""New v52 site: preserve historic bundles and expose only explicit aggregate evidence."""
import csv
import io
from pathlib import Path
import shutil
import subprocess
import sys

from gsearch.quality_protocol import digest,save
from gsearch.sid_prior_probe import read

DEST=Path('deploy/stage52');REPORT=Path('reports/stage52')


def main() -> None:
    if DEST.exists() or REPORT.exists():raise FileExistsError('Preserve previous delivery attempt')
    subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_prefix_prior'],check=True)
    REPORT.mkdir(parents=True)
    shutil.copytree('deploy/stage43',DEST,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    sources=[Path('reports/stage51/final-validation.json'),Path('reports/stage48/tuning-results.json'),
        Path('reports/stage48/summary.json'),Path('reports/stage51/comparison.json'),Path('reports/stage51/decision.json'),
        Path('reports/stage49/audit.json'),Path('reports/stage50/summary.json'),Path('reports/stage43/results.json')]
    sources.extend(Path('reports/stage45')/(name+'.tuning.score.json') for name in ['popular','content','sar'])
    save(REPORT/'evidence-source-lock.json',{'frozen_before_web_evidence_export':True,
        'private_input_policy':'extract named aggregate fields only; never publish original audit/sample/model directories',
        'files':{str(p):digest(p) for p in sources}})
    sft=read(Path('reports/stage48/tuning-results.json'));old=read(Path('reports/stage48/summary.json'))
    prior=read(Path('reports/stage51/comparison.json'));audit=read(Path('reports/stage49/audit.json'))
    health=read(Path('reports/stage50/summary.json'));structure=read(Path('reports/stage43/results.json'))
    quality=[]
    for method in ['popular','content','sar']:
        score=read(Path('reports/stage45')/(method+'.tuning.score.json'))
        quality.append({'method':method,'steps':None,'ndcg':score['user_macro']['ndcg@10'],'recall':score['user_macro']['recall@10']})
    for arm in ['content','shuffled']:
        for budget in [128,512]:
            quality.append({'method':arm+'_sid','steps':budget,'ndcg':old['metrics'][arm][str(budget)]['ndcg@10']['mean'],
                'recall':old['metrics'][arm][str(budget)]['recall@10']['mean']})
    priors=[{'run':name,**{k:r[k] for k in ['marginal_nll','prefix_nll','model128_nll','model512_nll']}} for name,r in prior['summary'].items()]
    gains=[]
    for seed in [42,2024,3407]:
        name='content-'+str(seed);r=audit['runs'][name];left=r['output']['128'];right=r['output']['512']
        gains.append({'seed':seed,'new_hits':r['changes']['full']['transitions']['new_hit'],
            'lost_hits':r['changes']['full']['transitions']['lost_hit'],'coverage128':left['unique_papers'],'coverage512':right['unique_papers'],
            'top_user_positive_share':r['concentration']['top1_user_share_of_gross_positive']})
    artifacts=DEST/'experiment-artifacts';artifacts.mkdir()
    copies={'tuning':('quality.csv',Path('reports/stage48/quality-comparison.csv'),'text/csv','完整tuning汇总'),
        'priors':('prefix-priors.csv',Path('reports/stage51/four-method-comparison.csv'),'text/csv','四方法分组损失'),
        'closure':('closure.md',Path('reports/阶段51_SID前缀先验与诊断收尾.md'),'text/plain','诊断收尾报告'),
        'resume':('resume-sid.md',Path('docs/SID_EXPERIMENT_CLOSURE_V51.md'),'text/plain','SID简历与面试证据')}
    downloads={}
    for key,(name,path,media,label) in copies.items():
        shutil.copyfile(path,artifacts/name)
        downloads[key]={'filename':name,'media_type':media,'label':label,'sha256':digest(artifacts/name),'source':str(path).replace('\\','/')}
    payload={'release':'stage52','as_of':'2026-11-04','title':'实验与证据','status':'current_budget_design_closed',
        'live':{'catalog':162,'default_search':'SQLite FTS5 BM25','default_recommendation':'基于实际收藏的 TF-IDF 内容余弦',
            'workflow':'确定性工具流程','llm_in_live_path':False,'scope':'当前网页主题试用目录，与9000篇离线SFT目录分开。'},
        'structure':{'catalog':162,'codebooks':'3 × 16','fit_seeds':[42,2024,3407],'shuffle_controls':60,
            'scope':'早期CPU结构与碰撞诊断；近邻保留不是推荐相关性指标。','page':'/sid-lab.html'},
        'sft':{'catalog':9000,'supervision_pool':98887,'samples128':1024,'samples512':4096,'steps':[128,512],
            'seeds':[42,2024,3407],'arms':['content','shuffled'],'batch':8,'beam':10,'raw_token_ids':True,
            'events':46352,'outside_catalog_events':39907,'rankable_with_context':1801,'quality':quality,
            'paired_content_minus_shuffled':sft['content_minus_shuffled_ndcg512'],
            'scope':'重复使用的tuning，完整正反馈分母，先用户内再用户宏平均；不是独立测试/线上CTR。'},
        'diagnosis':{'primary':'32严格训练前缀的3语义位置平均条件NLL，越低越好','priors':priors,'gain_loss':gains,
            'prefix_prior':'冻结4096标签；前序真实SID；Laplace α=1；完整位置码本；未见前缀均匀',
            'models_beating_prefix_prior':len(prior['decision']['model512_runs_beating_prefix_prior']),
            'history_probe':{'profiles':32,'beam_requests':384,'model_updates':0,
                'jaccard512_min':min(r['512']['history']['jaccard_mean'] for r in health['runs'].values()),
                'jaccard512_max':max(r['512']['history']['jaccard_mean'] for r in health['runs'].values())},
            'decision':'关闭当前T5/SID/监督设计下的预算加量路线；保留内容推荐默认。',
            'limits':['训练前缀损失参照，不是目录Top10排序比较。','未证明有效个性化，不外推所有生成式推荐无效。',
                '128→512同时增加步数与样本曝光，不能单独归因步数。','原始逐用户案例、预测和模型不通过网站分发。']},
        'downloads':downloads,'sources':[{'path':str(p).replace('\\','/'),'sha256':digest(p)} for p in sources]}
    save(DEST/'evidence-data.json',payload)
    save(DEST/'evidence-receipt.json',{'sha256':digest(DEST/'evidence-data.json'),'downloads':{key:r['sha256'] for key,r in downloads.items()}})
    save(REPORT/'preparation.json',{'bundle':str(DEST),'source_lock_sha256':digest(REPORT/'evidence-source-lock.json'),
        'previous_bundle_preserved':True,'public_payload_contains_only_named_aggregates':True,'downloads':list(downloads)})
    print({'bundle':str(DEST),'web_catalog':162,'offline_sft_catalog':9000,'explicit_artifacts':list(downloads)},flush=True)


if __name__=='__main__':main()
