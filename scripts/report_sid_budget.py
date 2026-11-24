"""Retain all seeds, fixed metrics and resource scopes for the budget comparison."""
from collections import Counter
import csv
from pathlib import Path
import statistics

from gsearch.quality_protocol import digest, save
from gsearch.sid_budget import ROOT, RUNS, SEEDS, ARMS, read


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open('x',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main() -> None:
    output=Path('reports/阶段48_受控训练预算对照.md')
    if output.exists(): raise FileExistsError('Preserve final report')
    assert read(ROOT/'validation.json')['status']=='passed'
    results=read(ROOT/'tuning-results.json'); exposure=read(ROOT/'data-validation.json')['exposure']
    rows=[]; groups=[]; losses=[]; resources=[]; concentrations=[]
    for budget in [128,512]:
        report=Path('reports/stage45') if budget==128 else ROOT
        runs=Path('runs/stage45') if budget==128 else RUNS
        for seed in SEEDS:
            for arm in ARMS:
                name=arm+'-'+str(seed); score=read(report/(name+'.tuning.score.json'))
                rows.append({'arm':arm,'seed':seed,'steps':budget,'samples':budget*8,
                    'ndcg@10':score['user_macro']['ndcg@10'],'recall@10':score['user_macro']['recall@10'],
                    'mrr@10':score['user_macro']['mrr@10'],'valid_slot_rate':score['valid_slot_rate'],
                    'duplicate_slot_rate':score['duplicate_slot_rate']})
                for group,value in score['groups'].items():
                    groups.append({'arm':arm,'seed':seed,'steps':budget,'group':group,
                        'events':value['events'],'users':value['users'],**value['user_macro']})
                training=read(runs/name/'training.json'); cost=read(runs/name/'prediction-cost.json')
                for entry in training['log_history']:
                    if 'loss' in entry: losses.append({'arm':arm,'seed':seed,'budget':budget,'step':entry['step'],
                        'loss':entry['loss'],'grad_norm':entry['grad_norm'],'lr':entry['learning_rate']})
                resources.append({'arm':arm,'seed':seed,'steps':budget,'training_seconds':training['elapsed_seconds'],
                    'prediction_seconds':cost['elapsed_seconds'],
                    'training_gpu_reserved_gib':training['gpu_reserved_bytes']/2**30,
                    'training_process_peak_gib':training['process_peak_bytes']/2**30,
                    'prediction_gpu_reserved_gib':cost['gpu_reserved_bytes']/2**30,
                    'prediction_process_peak_gib':cost['process_peak_bytes']/2**30,
                    'neural_amortized_seconds_per_user':cost['neural_amortized_seconds_per_user']})
                raw=read(runs/name/'raw-user-decoding.json')
                active=[r['doc_ids'] for r in raw.values() if not r['fallback']]
                tops=Counter(r[0] for r in active)
                concentrations.append({'arm':arm,'seed':seed,'steps':budget,'neural_users':len(active),
                    'unique_top10_papers':len({d for r in active for d in r}),
                    'catalog_coverage':len({d for r in active for d in r})/9000,
                    'top1_max_share':max(tops.values())/len(active)})
    for method in ['popular','content','sar']:
        score=read(Path('reports/stage45')/(method+'.tuning.score.json'))
        rows.append({'arm':method,'seed':'','steps':'baseline','samples':'full allowed history',
            'ndcg@10':score['user_macro']['ndcg@10'],'recall@10':score['user_macro']['recall@10'],
            'mrr@10':score['user_macro']['mrr@10'],'valid_slot_rate':score['valid_slot_rate'],
            'duplicate_slot_rate':score['duplicate_slot_rate']})
    write_csv(ROOT/'quality-comparison.csv',rows);write_csv(ROOT/'group-comparison.csv',groups)
    write_csv(ROOT/'loss-curves.csv',losses);write_csv(ROOT/'resource-comparison.csv',resources)
    write_csv(ROOT/'output-concentration.csv',concentrations)
    full={}
    for arm in ARMS:
        full[arm]={}
        for budget in [128,512]:
            chosen=[r for r in rows if r['arm']==arm and r['steps']==budget]
            full[arm][str(budget)]={metric:{'mean':statistics.mean(r[metric] for r in chosen),
                'sample_sd':statistics.stdev(r[metric] for r in chosen)} for metric in ['ndcg@10','recall@10']}
    content_baseline=next(r for r in rows if r['arm']=='content' and r['steps']=='baseline')['ndcg@10']
    budget_consistent={a:all(d>0 for d in results['budget_ndcg_deltas_512_minus128'][a]) for a in ARMS}
    sid_consistent=all(d>0 for d in results['content_minus_shuffled_ndcg512'])
    exceeds=full['content']['512']['ndcg@10']['mean']>content_baseline
    decision={'status':'bounded_budget_comparison_complete', 'next_training_started':False,
        'all_seed_budget_ndcg_improvement':budget_consistent,
        'all_seed_content_sid_beats_shuffled512':sid_consistent,
        'content_sid512_mean_exceeds_content_baseline':exceeds,
        'default_changed':False,'rl_started':False,'dev_evaluated':False,
        'interpretation':'descriptive budget+exposure effect; single dataset/SID pair, reused tuning; not a causal update-only or significance claim',
        'recommendation':'keep practical default; inspect target/prefix exposure and fresh quality evaluation before any further budget or RL'}
    save(ROOT/'decision.json',decision)
    cost_summary={str(b):{'training_seconds':sum(r['training_seconds'] for r in resources if r['steps']==b),
        'prediction_seconds':sum(r['prediction_seconds'] for r in resources if r['steps']==b),
        'training_gpu_reserved_peak_gib':max(r['training_gpu_reserved_gib'] for r in resources if r['steps']==b),
        'process_peak_gib':max(max(r['training_process_peak_gib'],r['prediction_process_peak_gib']) for r in resources if r['steps']==b)} for b in [128,512]}
    save(ROOT/'summary.json',{'metrics':full,'cost':cost_summary,'decision':decision,
        'budget_deltas':results['budget_ndcg_deltas_512_minus128'],'sid_deltas512':results['content_minus_shuffled_ndcg512'],
        'exposure':exposure,'protocol_sha256':digest(ROOT/'protocol.json')})
    table=[]
    for arm in ARMS:
        for b in [128,512]:
            m=full[arm][str(b)]
            table.append(f"| {arm} SID | {b} | {m['ndcg@10']['mean']:.9f} ± {m['ndcg@10']['sample_sd']:.9f} | {m['recall@10']['mean']:.9f} |")
    for row in rows:
        if row['steps']=='baseline': table.append(f"| {row['arm']}基线 | — | {row['ndcg@10']:.9f} | {row['recall@10']:.9f} |")
    delta_table=[]
    for i,seed in enumerate(SEEDS):
        delta_table.append(f"| {seed} | {results['budget_ndcg_deltas_512_minus128']['content'][i]:+.9f} | {results['budget_ndcg_deltas_512_minus128']['shuffled'][i]:+.9f} | {results['content_minus_shuffled_ndcg512'][i]:+.9f} |")
    conditional_table=[]
    for seed in SEEDS:
        for arm in ARMS:
            name=arm+'-'+str(seed); v=read(ROOT/(name+'.tuning.score.json'))['conditional_diagnostic']
            conditional_table.append(f"| {name} | {v['user_macro']['ndcg@10']:.9f} | {v['user_macro']['recall@10']:.9f} |")
    cost_table=[]
    for b in [128,512]:
        c=cost_summary[str(b)]
        cost_table.append(f"| {b} | {c['training_seconds']:.2f} | {c['prediction_seconds']:.2f} | {c['training_gpu_reserved_peak_gib']:.3f} | {c['process_peak_gib']:.3f} |")
    output.write_text('''# 阶段48：128→512步受控预算对照

日期：2026-11-04，Asia/Hong_Kong。两组SID、42/2024/3407三个种子全部完成；本阶段从同一基础权重分别训练512步，128检查点属于本轮训练，不是从旧的缺优化器状态的模型续训。没有进入RL、没有评价dev、没有更改网站默认。

## 设计与复现门槛

基础权重、tokenizer、9000目录、SID映射、原始token-ID标签、数据seed271828排列、batch8、学习率0.0005、AdamW参数、constant调度、BF16/确定性设置均沿用阶段45。新增的只有预算/监督曝光与原生检查点保存。原生Seq2SeqTrainer负责优化和检查点，适配回调仅控制128/512保存、资源检查及128复现门槛。

六跑在各自128步，保存权重逐张量bitwise等于旧final；16..128的8条loss/grad_norm/lr逐项相等。epoch字段由1/4训练长度变化而不同，不作为优化轨迹比较。第一次128门槛通过后才封存实际512锁；每跑均通过后才继续到129。原生optimizer.pt、scheduler.pt、rng_state.pth、trainer_state.json、training_args.bin及模型/tokenizer均保留在两检查点。保存并不代表已独立验证中断恢复等价，本轮运行是连续训练。

128读冻结排列前1024条（843用户/913目标），512读前4096条（2431用户/2927目标），每样本5标签token。不是同1024样本重复4轮，不能把结果单独归因更多更新或更多数据。全部8192双臂输入逐源重建，训练流4096顺序完整核对；训练未读取未来标签。

## 完整分母质量

主指标沿用完整46352正反馈、3571用户的user-macro NDCG@10；目录外39907仍计miss。目录内无上下文4644，目录内且有上下文1801仅作诊断。beam10/未读过滤/原始ID/1443空画像流行度兜底不变。旧128结果只在六跑严格权重重现后复用，没有再花一次完整128解码预算。每组512结果完整解码/计分，保留所有种子，不选最好值。

±后为三个固定种子的样本标准差，不是置信区间；基线为既有同目录/过滤的确定性结果。

| 方法 | 步数 | NDCG@10均值 ± SD | Recall@10均值 |
|---|---:|---:|---:|
'''+ '\n'.join(table)+'''

| 种子 | 内容SID 512−128 NDCG | 打乱SID 512−128 NDCG | 512内容−打乱 NDCG |
|---|---:|---:|---:|
'''+ '\n'.join(delta_table)+f'''

内容SID预算三种子均改善：{budget_consistent['content']}；打乱SID均改善：{budget_consistent['shuffled']}；512内容SID三种子均胜打乱：{sid_consistent}；512内容SID均值超过实用内容基线：{exceeds}。这些是描述性比较，不宣称统计显著或MiniOneRec完整复现。

## 条件组与冷启动

下表只含1801个目录内且有训练上下文的事件（528用户），不替代主分母。完整用户cold/sparse/warm及论文no_train_like/trainliked/outside_catalog组在group-comparison.csv；无训练点赞目标仅14事件，不能对其推广结论。1443空画像用户全用共同兜底，其组指标与旧128完全一致；该组收益不能归功于神经模型。用户冷启动和论文冷启动分开列出。

| 512运行 | 条件NDCG@10 | 条件Recall@10 |
|---|---:|---:|
'''+ '\n'.join(conditional_table)+'''

覆盖与集中度见output-concentration.csv，统计2128独立有历史用户，报告不同Top10论文并集/9000及最大首位占比，不把事件重复输出当覆盖。

## 资源与边界

| 预算 | 六跑训练秒 | 六跑完整预测秒 | 训练GPU reserved峰值GiB | 训练/预测进程峰值GiB |
|---|---:|---:|---:|---:|
'''+ '\n'.join(cost_table)+'''

新训练时间包含原生检查点保存、128张量/损失检查及回调哈希开销；旧128没有同等检查点开销，两者不是纯计算速度对照。机器负载与运行时状态没有额外控制，预测耗时差也不能归因为训练步数或算法加速。process_peak是进程生命周期累计高水位，同一进程内后续运行不是独立的峰值内存观测。预测按batch16，2128神经画像复用到全部事件；摊销时间不是交互p95、生产QPS或线上性能。计分、CPU核验及整体进程初始化另计。没有为补图安装matplotlib或改环境，完整loss轨迹保存在loss-curves.csv。

## 决定与限制

本次授权预算已用完，保留实用默认和全部对照。后续若继续研究，应依据曝光/目标前缀诊断另设实验，先获得新的质量证据，再决定预算或RL；本轮结果不能直接支持RL收益。当前tuning已多次用于研究选型，现有dev也已使用，均不冒充新独立测试。单数据集、固定一套内容/打乱SID和三个种子限制了外推；模型总训练只覆盖98887池中4096条。

源设计、完整结果、分组、资源、暴露、失败记录和decision.json在reports/stage48。用户级训练/预测在ignored data/stage48-budget和runs/stage48，仅本地研究使用，不随网站公开或分发模型。原阶段45/46/47封存资产保持不变。复核说明docs/SID_BUDGET_V48.md；最终入口scripts.verify_sid_budget。训练/评分代码在运行前冻结，报告生成与验收另行封存。
''',encoding='utf-8')
    print({'report':str(output),'summary':full,'decision':decision},flush=True)


if __name__=='__main__': main()
