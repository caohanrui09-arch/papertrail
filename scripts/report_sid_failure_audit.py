"""Create the requested evidence/count/case/next-check audit table from real artifacts."""
from collections import Counter
import json
from pathlib import Path
import statistics

from gsearch.quality_protocol import digest,save
from gsearch.supervision import json_rows
from scripts.audit_sid_failures import write_csv

ROOT=Path('reports/stage46')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main() -> None:
    output=Path('reports/阶段46_SID失败归因审计.md')
    if output.exists():raise FileExistsError('Preserve audit report')
    audit=read(ROOT/'audit.json');concentration=read(ROOT/'output-concentration.json')
    assert read(ROOT/'validation.json')['status']=='passed'
    labels=list(json_rows(Path('data/stage44-supervision/tuning.labels.jsonl')))
    outside=[r for r in labels if not r['rankable'] and r['miss_reason']=='outside_frozen_catalog']
    outside_counts=Counter('existing_10000_post_cutoff' if r['in_original_10000_corpus'] and r['after_training_catalog_cutoff']
        else 'not_in_existing_10000_metadata' if not r['in_original_10000_corpus'] else 'other_in_10000' for r in outside)
    save(ROOT/'outside-catalog-diagnostic.json',{'events':len(outside),'metadata_snapshot_groups':dict(outside_counts),
        'with_original_training_likes':sum(r['target_train_positive_count']>0 for r in outside),
        'without_original_training_likes':sum(r['target_train_positive_count']==0 for r in outside),
        'scope':'outcome-based diagnosis only; no candidate selection, acquisition or date inference for missing metadata'})
    coverage=audit['coverage'];runs=[a+'-'+str(s) for s in [42,2024,3407] for a in ['content','shuffled']]
    case_index=audit['case_index']
    def case(prefix: str) -> str:
        return next((r['case_id'] for r in case_index if r['case_type'].startswith(prefix)),'无事件案例')
    failures=[]
    def add(scope: str,observation: str,count: str,denominator: str,reference: str,evidence: str,next_check: str,limit: str):
        failures.append(dict(scope=scope,observation=observation,count=count,denominator=denominator,
            case_ref=reference,evidence=evidence,next_validation=next_check,causal_limit=limit))
    add('完整分母互斥分组','目标在冻结目录外','39907','46352事件',case('partition:unrankable:outside_frozen_catalog'),
        '目录成员与冻结标签一致；所有方法均无法返回目录外目标',
        '按训练期来源、领域及明确版本可用时间审计扩容，不按未来点赞挑候选','不等同于已找到39907篇可扩容论文，事件与论文数不同，缺元数据不能推断日期')
    add('完整分母互斥分组','目录内可排序，但无可用正反馈上下文','4644','46352事件；6445目录内可排序事件',
        case('partition:rankable_without_context'),'所有方法遵守共同训练流行度兜底',
        '作为用户冷启动/无上下文单独跟踪；不用于判断SID个性化收益','无上下文不等于论文冷启动，也不等于用户没进入pilot')
    add('完整分母互斥分组','目录内可排序且有历史','1801','46352事件；528名用户',case('exposure:'),
        '本轮个性化条件诊断的固定子集；原主指标仍包含全部46352事件',
        '在相同子集比较传统基线与全部六跑、避免目录覆盖掩盖排序差距','事后条件指标不能替代原主指标或当独立新测试')
    add('1801事件曝光互斥分组','目标源训练期无点赞','4','1801事件；全部目录内同类14事件',case('exposure:no_source_train_like'),
        '源训练点赞为0；与有赞但未入pilot不同',
        '仅描述冷论文证据；若扩充评价须靠预先固定目录/时段规则','4条条件事件和14条总事件不足以证明稳定冷论文收益')
    add('1801事件曝光互斥分组','源训练有赞，但代理可用规则下无合规正反馈','5','1801事件',
        case('exposure:train_liked_without_proxy_eligible_feedback'),
        '源训练点赞>0、proxy-eligible点赞=0，不是真正源论文冷启动',
        '核查原v1来源和时间代理后决定是否另建数据版本','不能凭未来命中改时间代理或追溯回填旧监督')
    add('1801事件曝光互斥分组','合规有赞，但没有next-item目标监督','0','1801事件；目录中2篇此类论文','无本组未来事件',
        '最早正反馈缺少严格更早历史，不能成为next-item监督',
        '保留审计分类，避免与抽样缺失混淆','本组在当前条件评价中没有事件，不解释本轮排序损失')
    add('1801事件曝光互斥分组','有完整监督池目标样本，但没入本轮1024条','1504','1801事件',
        case('exposure:pool_target_not_selected_in_pilot'),
        '监督池中有目标，pilot目标标签计数=0；约83.51%的条件事件处于该分组',
        '先检查未见/已见目标的分位置损失，必要时单独增加训练预算','这是曝光状态，不是已证明的失分因果；不能按tuning目标补采训练样本')
    add('1801事件曝光互斥分组','目标已入本轮训练标签','288','1801事件；各SID运行仍漏287–288条',
        case('exposure:pilot_target_seen'),'每跑对此组仅0或1次命中；监督缺失不是唯一现象',
        '固定权重，分开检查三个语义token与身份后缀/EOS的teacher-forced损失','已见目标不保证该用户/上下文被训练，也不能由此断言SID设计错误')
    missing=[audit['terminal_prefix'][m]['counts'].get('missing_at_depth_1',0) for m in runs]
    add('终局前缀诊断，非互斥原因总表','最终Top10首层未覆盖目标前缀',f'{min(missing)}–{max(missing)}',
        '每运行1801事件',case('content_only:'),
        '完整保存路径的首层覆盖观察；约86.23%–94.34%',
        '下次小规模调用保存中间beam状态/索引以确认首次掉榜；本轮不重跑',
        '不是实际剪枝时刻；无法区分早期未进入beam与后期掉榜')
    neural=[concentration['metrics'][m]['all_context_users']['unique_recommended_papers'] for m in runs]
    add('全体有历史用户的聚合诊断','SID输出论文覆盖集中',f'{min(neural)}–{max(neural)}篇；内容基线4807篇',
        '每运行2128名独立有历史用户的Top10','无单例代表；见output-concentration.json',
        '对独立画像先去重后统计推荐论文全集；没有混入空画像兜底',
        '固定候选/接收者seen mask，仅交换历史输入，测Top10变化与分位置损失',
        '列表有差异可能来自历史也可能来自seen mask，不能仅凭集中度断言忽略历史')
    add('基线独有命中诊断','内容推荐命中、SID未命中','82','每运行同一1801事件，六跑均为82',
        case('content_only:'),'82个基线命中事件中没有一个被六个SID运行命中；SID另有0–5个独有命中',
        '复核本地案例中的严格历史、目标监督曝光、真实v1文本和终局前缀',
        '不是人工相关性判断，不能把点赞预测解释成语义相关性金标准')
    add('映射对照解释边界','目标SID不变的碰撞组，历史SID仍改变','384','389个目标碰撞组条件事件',
        case('content_only:content-42:pilot_target_seen:unchanged_collision_target'),
        '按每个用户真实历史检查至少一个历史论文映射变化',
        '同时报告目标映射组和历史变化，不把该组当纯负控制',
        '目标不变不意味着模型输入不变，不能据此单独归因SID映射的因果作用')
    write_csv(ROOT/'failure-audit.csv',failures)
    decision={'status':'recommended_not_executed','priority':'frozen-model health and history sensitivity probe before larger training',
        'reason':['targets already exposed in pilot still miss287–288 of288 conditional events',
                  'terminal first-prefix absence1553–1699 of1801','recommended item union54–163 versus content4807'],
        'probe_A':{'frozen_model_runs':runs,'unique_profiles':32,'histories':['original','training-only deterministically swapped'],
            'beam_requests_total_cap':384,'sample_selection':'training-cutoff positive-context profiles, source-only fixed hash; no tuning hits or targets',
            'change_only':'encoder history; keep receiving profile candidate catalog/seen positive+negative mask/weights/beam10/precision fixed',
            'measure':['paired Top10 overlap/rank changes','terminal/intermediate prefix paths and beam indices','latency'],
            'causal_scope':'sensitivity to controlled history input, not an offline recommendation quality win'},
        'probe_B':{'training_prefix_samples':32,'selection':'16pilot-labelled +16pool-not-pilot, source-only deterministic selection',
            'histories':'use original strict-past training sample history, not full-cutoff profile containing the target',
            'measure':'native teacher-forced unreduced cross-entropy separately at3 semantic tokens, identity suffix, EOS',
            'meaning':'training-prefix diagnostic, not independent generalization evaluation'},
        'optimizer_updates':0,'no_source_acquisition':True,
        'after_probe':'If no interface/label/decoder defect and semantic positions remain underlearned, separately freeze128→512-step same-order budget comparison; do not change ID design simultaneously.',
        'catalog_track':'source/time/domain based metadata audit separately; future likes only diagnose and evaluate, never select candidate or train-sampling targets',
        'not_started':['probe inference','extra training','dev evaluation','RL','website changes']}
    save(ROOT/'next-step-decision.json',decision)
    availability_rows=[]
    for group in ['unrankable:outside_frozen_catalog','rankable_without_context','rankable_with_context']:
        n=audit['availability_partition'][group]
        availability_rows.append(f'| {group} | {n:,} | {100*n/46352:.2f}% |')
    failure_rows=['| '+ ' | '.join([r['observation'],r['count'],r['denominator'],r['case_ref'],r['next_validation']])+' |' for r in failures]
    metric_rows=[]
    for method in ['popular','content','sar']+runs:
        row=audit['metrics'][method]['rankable_with_context']
        metric_rows.append(f"| {method} | {row['hit_events']} | {row['user_macro']['recall@10']:.8f} | {row['user_macro']['ndcg@10']:.8f} | {row['user_macro']['mrr@10']:.8f} |")
    prefix_rows=[]
    for method in runs:
        c=audit['terminal_prefix'][method]['counts']
        prefix_rows.append('| '+method+' | '+' | '.join(str(c.get(k,0)) for k in ['hits','missing_at_depth_1','missing_at_depth_2','missing_at_depth_3','missing_at_depth_4'])+' |')
    coverage_rows=[]
    for arm,levels in coverage['prefix_coverage'].items():
        for row in levels:
            coverage_rows.append(f"| {arm} | {row['depth']} | {row['catalog_prefixes']} | {row['full_pool_label_prefixes']} | {row['pilot_label_prefixes']} | {row['pilot_history_prefixes']} | {100*row['pilot_label_pool_coverage']:.2f}% |")
    group_rows=[]
    for method in runs:
        for group in ['context_mapping:changed_singleton_target','context_mapping:unchanged_collision_target']:
            row=audit['metrics'][method][group]
            group_rows.append(f"| {method} | {group.split(':')[1]} | {row['events']} | {row['hit_events']} | {row['user_macro']['ndcg@10']:.8f} |")
    paired=[]
    for seed in [42,2024,3407]:
        full=audit['metrics']['content-'+str(seed)]['full']['user_macro']['ndcg@10']-audit['metrics']['shuffled-'+str(seed)]['full']['user_macro']['ndcg@10']
        conditional=audit['metrics']['content-'+str(seed)]['rankable_with_context']['user_macro']['ndcg@10']-audit['metrics']['shuffled-'+str(seed)]['rankable_with_context']['user_macro']['ndcg@10']
        paired.append(f'| {seed} | {full:+.9f} | {conditional:+.9f} |')
    body='''# 阶段46：SID失败归因审计

日期：2026-11-04（Asia/Hong_Kong）。复用阶段44/45封存监督与预测，CPU描述性审计；没有加载模型、重新生成、训练、评价dev、增加依赖或修改网站。

## 决策与证据边界

下一步优先固定现有六个权重做**32画像历史扰动＋32训练前缀分位置损失检查**，再决定是否另建128→512步预算对照。本轮没有执行该探针或追加训练。目录覆盖不足和个性化排序不足同时存在；扩大目录本身不能解释目录内有历史子集的排序差距。

现有轨迹只保存最终Top10完整token路径，没有中间beam候选/分数/祖先。下文的“第几层缺失”是**最终Top10首次不覆盖目标前缀的层**，不是已观察的首次剪枝时刻。第四层为身份后缀，不是第四层语义。

全部原46352事件主分母保留，九组原全量分数以1e-14容差复现。条件分组均为事后诊断，不替换原主指标，不构成新独立测试，不作因果或显著性断言。三种子只反映训练随机性；完整反馈传统基线与1024条SFT不是相同监督曝光量对照。

## 失败原因、数量、案例与下一步验证

下表为审计观察和验证方向，不能把每一行都称为已证实的因果。前3行互斥且覆盖46352事件；其后曝光分组覆盖1801条件事件，其他诊断行与它们重叠，不可相加。

| 观察/候选原因 | 数量 | 分母/口径 | 典型案例 | 下一步验证 |
|---|---:|---|---|---|
'''+ '\n'.join(failure_rows)+'''

案例的分组内qid字典序最小规则先于计算固定，没有人工挑选。36个详细案例仅保存在Git忽略的 [本地案例文件](../data/stage46-audit/cases.md)；按实际可用性记录真实历史、曝光次数、内容基线排名和明确v1原摘要，SID对照案例另含完整路径。目录外缺原文时明确记未知，不补写标题、摘要或版本；点赞预测案例也不等于人工相关性金标准。逐行证据及限制见failure-audit.csv。

## 目录与画像分母

| 分组 | 正反馈事件 | 占完整分母 |
|---|---:|---:|
'''+ '\n'.join(availability_rows)+f'''

只有1801条、528名用户可用于“目录内且有历史”条件诊断。其余4644条目录内正反馈全部走共同流行度兜底，不能用来宣称SID个性化有收益。39907条目录外事件继续作为漏召回，诊断不删除分母。

目录外来源诊断：{dict(outside_counts)}；其中源训练期已有点赞的事件{sum(r['target_train_positive_count']>0 for r in outside):,}条，其余{sum(r['target_train_positive_count']==0 for r in outside):,}条。缺既有万篇元数据的记录无法判断明确版本、日期或扩容成本；这些是事件数，不是可扩容论文数。未来点赞仅用于解释，不用于新候选选择。

## 1024条训练监督到底覆盖多少

| 指标 | 计数/分母 |
|---|---:|
| 完整next-item监督 | 98,887条；7,236用户；7,992目标论文 |
| pilot | 1,024条；843用户；913目标论文 |
| 用户覆盖（相对监督池） | 843 / 7,236（11.65%） |
| 目标覆盖（相对监督池） | 913 / 7,992（11.42%） |
| 作为历史输入出现的论文 | 5,009篇，11,825次历史项曝光 |
| 仅作历史输入、没作pilot目标 | 4,338篇 |
| 有监督池目标但未进pilot | 7,079篇目录论文 |
| 源训练期零点赞 | 1,000篇目录论文；14条tuning事件，其中4条有历史 |
| 源有赞但无proxy-eligible点赞 | 6篇；6条tuning事件，其中5条有历史 |
| 有eligible点赞但无next-item目标 | 2篇；当前tuning无此类事件 |

“没被pilot抽到”不是论文冷启动；“用户没在pilot出现”也不是没有训练截止历史。T5输入没有用户ID，843用户覆盖是监督上下文覆盖统计，不是ID嵌入是否训练。

| 映射 | 前缀深度 | 目录前缀 | 全监督池目标前缀 | pilot目标前缀 | pilot历史前缀 | pilot/全池目标前缀 |
|---|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(coverage_rows)+'''

两组监督条数、目标token数相同。内容SID首层已覆盖61/64，然而终局首层对目标的覆盖仍低，不能把全部失败都解释成那3个未监督首层码。进入历史输入也不等于接受过对应完整SID的目标监督。

## 固定1801事件、528用户的条件质量

下表仍使用原metrics函数，先用户内平均再用户间平均，数值为0–1原始值。命中数为事件计数，两种单位不要混淆。

| 方法 | 命中事件 | user-macro Recall@10 | NDCG@10 | MRR@10 |
|---|---:|---:|---:|---:|
'''+ '\n'.join(metric_rows)+'''

内容基线命中82条，SID六跑各0–5条，且没有命中这82条基线命中事件。该差距在排除目录外与共同兜底后仍存在，不只是完整分母稀释造成。

| 种子 | 原全分母内容SID−打乱SID NDCG | 条件分母对应差值 |
|---|---:|---:|
'''+ '\n'.join(paired)+'''

条件分母对同一用户平均时，分母从该用户全部未来事件变为其目录内有历史事件；不同用户会被重新加权。因此条件NDCG差可以与全量差改变符号，不能把事后选出的条件差值替代原“2正1负”结论，更不能据此宣布语义SID胜出。

## 终局前缀与输出集中

每行分母均1801事件；命中与四层首次缺失之和恰为1801。第1–3层为语义码，第4层为身份消歧码。

| 运行 | 命中 | 首层终局未覆盖 | 第二层首次未覆盖 | 第三层首次未覆盖 | 身份层首次未覆盖 |
|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(prefix_rows)+'''

终局首层未覆盖1553–1699条（86.23%–94.34%）。身份层首次缺失为0，是这批最终列表中的观察，不能证明身份后缀在中间beam从未影响排序。

在2128名独立有历史用户中，各SID运行推荐论文并集仅54–163篇，内容推荐为4807篇、SAR为5436篇；同一论文占首位的用户比例约29.28%–82.24%。模型列表并非全相同，但seen mask也随用户变化，尚不能由集中度或列表差异推断模型忽略/使用了历史。原始摘要案例也不能替代受控历史扰动。

## 映射改变组与碰撞组

| 运行 | 目标映射组 | 事件 | 命中 | user-macro NDCG |
|---|---|---:|---:|---:|
'''+ '\n'.join(group_rows)+'''

目标映射改变单例组1412事件，目标不变碰撞组389事件；后者384条仍有历史SID改变。目标SID不变并不是输入不变的负控制，这两组只能作描述性诊断，不能隔离语义编码的因果贡献。

## 下一次具体验证

1. 固定六个已训练模型、9000目录、beam10、精度和接收者的正/负seen mask，从训练截止画像按固定hash选择32个有历史用户，只对调encoder历史，比较Top10重合/排序和中间前缀；总beam请求上限384。不按tuning命中挑用户，不重新跑完整评价。
2. 从训练监督选择32个严格历史前缀（pilot已见/池中未抽各16），teacher forcing按位置统计3个语义token、身份码、EOS的损失。使用原严格更早历史，不能把完整截止画像中已包含的目标放入输入。该结果是训练前缀健康检查，不是独立泛化质量。
3. 仅当未发现标签/接口/解码问题，且语义位置仍明显未学好时，再另建版本固定128→512步预算阶梯；目录、SID设计与其他参数同时保持固定。当前预算阶梯、探针和RL均未执行。

目录扩容属于另一条数据覆盖验证：候选依据训练期来源、领域和明确版本可用时间选入；未来点赞只诊断/评价，不据此补选未来命中的论文或训练目标。研究数据/逐用户衍生物继续仅本地非商业，网站默认不变。

## 验证与追溯

12项边界测试通过；两臂全监督池与pilot曝光独立重建，9000篇曝光字段核对；9组条件指标直接调用旧score_rows核对；10806个方法×条件事件用另一种前缀集合算法复核；36例均核对源qid、最小qid选择、原v1标题/摘要/链接。九组全量分数与旧封存值以1e-14容差一致。

旧303资产入口为scripts.validate_sft_delivery_v2，新审计最终入口为scripts.verify_sid_failure_audit。复跑说明见docs/SID_FAILURE_AUDIT_V46.md；数据与案例在被Git忽略data/stage46-audit，表格/统计/证据边界在reports/stage46。
'''
    output.write_text(body,encoding='utf-8')
    print({'report':str(output),'failure_table_rows':len(failures),'cases':len(case_index),
           'next':'frozen-model history/loss health probe, not larger training yet'},flush=True)


if __name__=='__main__':main()
