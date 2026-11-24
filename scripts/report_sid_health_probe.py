"""Summarize the fixed-model probe; all positions, strata, seeds and failure retained."""
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import statistics

from gsearch.quality_protocol import digest,save

ROOT=Path('reports/stage47');DATA=Path('data/stage47-health')


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def csv_write(path,rows):
    with path.open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def mean(values):return statistics.mean(values)


def main() -> None:
    output=Path('reports/阶段47_冻结模型历史与损失探针.md')
    if output.exists():raise FileExistsError('Preserve health report')
    assert read(ROOT/'validation.json')['status']=='passed'
    protocol=read(ROOT/'protocol.json');execution=read(ROOT/'execution.json')
    history_summary=[];loss_summary=[];pairs=[];summary={};beam_seconds=0;max_amp_error=0;max_precision_delta=0
    sample_exposure=read('data/stage46-audit/item-exposure.json')
    prefix_rows=read(DATA/'prefixes.json')
    nonpilot_target_seen=sum(row['exposure_group']=='pool_not_pilot' and sample_exposure[row['target_doc_id']]['pilot_label_count']>0 for row in prefix_rows)
    for run in protocol['models']:
        history=read(DATA/run/'history-probe.json');loss=read(DATA/run/'position-loss.json')
        beam_seconds+=sum(batch['seconds'] for batch in history['batches'])
        h_all=None
        for cohort in ['all','history1','history20']:
            rows=[r for r in history['paired'] if cohort=='all' or r['history_length']==int(cohort.removeprefix('history'))]
            score_deltas=[r['common_doc_mean_abs_sequence_score_change'] for r in rows if r['common_doc_mean_abs_sequence_score_change'] is not None]
            row={'run':run,'cohort':cohort,'profiles':len(rows),'jaccard_mean':mean(r['jaccard'] for r in rows),
                'jaccard_min':min(r['jaccard'] for r in rows),'jaccard_max':max(r['jaccard'] for r in rows),
                'top1_changed':sum(not r['top1_equal'] for r in rows),
                'ordered_list_changed':sum(not r['ordered_equal'] for r in rows),
                'overlap_mean':mean(r['overlap_fraction'] for r in rows),
                'footrule_mean':mean(r['footrule_missing_rank11_div110'] for r in rows),
                'common_doc_sequence_score_abs_change_mean':mean(score_deltas) if score_deltas else None,
                'new_donor_history_items':sum(r['newly_returned_donor_history_items'] for r in rows)}
            history_summary.append(row)
            if cohort=='all':h_all=row
        pairs.extend({'run':run,**row} for row in history['paired'])
        groups=defaultdict(list)
        for row in loss['samples']:
            for position in row['positions']:
                for group in ['all',row['exposure_group'],'history'+str(row['history_length']),row['exposure_group']+':history'+str(row['history_length'])]:
                    groups[(group,position['position'])].append(position)
        for (cohort,position),rows in groups.items():
            loss_summary.append({'run':run,'cohort':cohort,'position':position,'samples':len(rows),
                'fp32_full_vocab_nll_mean':mean(r['full_vocab_nll'] for r in rows),
                'native_amp_full_vocab_nll_mean':mean(r['native_amp_full_vocab_nll'] for r in rows),
                'position_conditional_nll_mean':mean(r['position_conditional_nll'] for r in rows),
                'position_mass_mean':mean(r['position_mass'] for r in rows),
                'full_vocab_top1_accuracy':mean(float(r['full_vocab_top1_correct']) for r in rows),
                'position_top1_accuracy':mean(float(r['position_top1_correct']) for r in rows),
                'uniform_position_nll':rows[0]['uniform_position_nll'],
                'pilot_position_prior_nll_mean':mean(r['pilot_position_prior_nll'] for r in rows)})
        semantic=[position for row in loss['samples'] for position in row['positions'][:3]]
        all_positions=[position for row in loss['samples'] for position in row['positions']]
        semantic_summary={'tokens':len(semantic),'fp32_full_vocab_nll':mean(p['full_vocab_nll'] for p in semantic),
            'conditional_nll':mean(p['position_conditional_nll'] for p in semantic),
            'uniform_nll':math.log(64),'pilot_prior_nll':mean(p['pilot_position_prior_nll'] for p in semantic),
            'position_mass':mean(p['position_mass'] for p in semantic),
            'position_top1_accuracy':mean(float(p['position_top1_correct']) for p in semantic),
            'share_of_total_fp32_nll':sum(p['full_vocab_nll'] for p in semantic)/sum(p['full_vocab_nll'] for p in all_positions)}
        max_amp_error=max(max_amp_error,max(row['native_amp_abs_error'] for row in loss['native_batch_checks']))
        max_precision_delta=max(max_precision_delta,max(abs(row['fp32_minus_native_amp_mean']) for row in loss['native_batch_checks']))
        summary[run]={'history':h_all,'semantic_positions':semantic_summary}
    csv_write(ROOT/'history-summary.csv',history_summary)
    csv_write(ROOT/'position-loss-summary.csv',loss_summary)
    csv_write(DATA/'paired-observations.csv',pairs)
    needs_budget=all(r['semantic_positions']['conditional_nll']>=r['semantic_positions']['uniform_nll'] for r in summary.values())
    responds=all(r['history']['ordered_list_changed']>0 for r in summary.values())
    decision={'status':'recommend_bounded_training_budget_validation_not_started' if needs_budget and responds else 'continue_health_diagnosis_before_training',
        'posthoc_recommendation_not_preregistered_quality_test':True,
        'observations':{'all_six_outputs_respond_to_history':responds,
                        'all_six_mean_semantic_conditional_nll_not_better_than_uniform64':needs_budget},
        'recommendation':'128→512 steps with same base/SID/source-order/batch/optimizer/seeds; retain both content and shuffled arms',
        'samples':'same frozen source permutation, first4096; budget increase also increases exposure, not a pure fixed-sample optimizer-step effect',
        'reproducibility_gate':'restart from same base; save native optimizer/RNG at128 and512; verify128 checkpoint reproduces prior reference before relying on paired comparison',
        'selection':'predeclare checkpoints and unchanged full-denominator tuning metrics; condition1801 is diagnostic; no best-seed selection',
        'resource_estimate':'six-run128 training331.24s x4≈22.1min training only; illustrative linear estimate, actual preflight and decode/evaluation costs separate',
        'not_proven':['512steps improve Recall/NDCG','history sensitivity means preference understanding','SID beats shuffled or content baseline'],
        'training_started':False,'rl_started':False,'dev_evaluated':False}
    save(ROOT/'decision.json',decision)
    costs={'beam_batch_seconds_total':beam_seconds,'continuation_wall_seconds':execution['continuation_wall_seconds'],
        'gpu_reserved_peak_gib':max(r['gpu_reserved_peak_bytes'] for r in execution['costs'])/2**30,
        'process_peak_gib':max(r['process_peak_bytes'] for r in execution['costs'])/2**30,
        'beam_requests_total':384,'reused_beam_requests':execution['reused_beam_requests'],'successful_teacher_samples':192,
        'diagnostic_teacher_samples':execution['numerical_diagnostic_forward_samples'],
        'interrupted_teacher_samples_upper_bound':execution['interrupted_first_attempt_teacher_samples_upper_bound'],
        'teacher_attempt_samples_upper_bound':execution['teacher_forward_attempt_samples_upper_bound'],'max_native_amp_mean_error':max_amp_error,
        'max_fp32_minus_native_amp_batch_mean_abs':max_precision_delta,
        'scope':'beam sum includes retained first attempt; continuation wall excludes startup/tests and first attempt; failed timing not fully measured'}
    save(ROOT/'summary.json',{'protocol_sha256':digest(ROOT/'protocol.json'),
        'continuation_lock_sha256':digest(ROOT/'continuation-lock.json'),'runs':summary,'costs':costs,
        'nonpilot_prefixes_with_pilot_seen_target_paper':nonpilot_target_seen,'decision':decision})
    history_table=[];semantic_table=[]
    for run,row in summary.items():
        h=row['history'];s=row['semantic_positions']
        history_table.append(f"| {run} | {h['jaccard_mean']:.4f} | {h['top1_changed']}/32 | {h['ordered_list_changed']}/32 | {h['new_donor_history_items']} |")
        semantic_table.append(f"| {run} | {s['conditional_nll']:.4f} | {s['uniform_nll']:.4f} | {s['pilot_prior_nll']:.4f} | {100*s['position_top1_accuracy']:.2f}% | {100*s['share_of_total_fp32_nll']:.2f}% |")
    positions_table=[]
    for position in ['semantic1','semantic2','semantic3','identity','eos']:
        rows=[r for r in loss_summary if r['cohort']=='all' and r['position']==position]
        def limits(field):return f"{min(r[field] for r in rows):.4f}–{max(r[field] for r in rows):.4f}"
        positions_table.append(f"| {position} | {limits('fp32_full_vocab_nll_mean')} | {limits('position_conditional_nll_mean')} | {limits('position_mass_mean')} | {limits('full_vocab_top1_accuracy')} |")
    if execution['numerical_diagnostic_forward_samples']:
        precision_story='首个模型完成64个A请求后，原“FP32未约简均值必须等于AMP模型loss、容差1e-4”的门槛失败。8样本诊断中，原模型AMP loss为3.79277372、同AMP直接CE为3.79277372，显式FP32 CE为3.79382968。该实验只能确认计算口径不同，没有把具体CUDA舍入机制当成已查明结论。'
        precision_retention='保留原协议、代码、失败日志、8样本诊断、首64请求轨迹；另行封存continuation-lock.json。'
    else:
        precision_story='本次从修正后的入口直接运行，没有发生旧的精度核验中断或额外诊断前向。原生AMP loss与FP32分析CE分别记录，不混用计算口径。'
        precision_retention='本次入口与输入由continuation-lock.json另行封存。'
    window_note='首模型的内存前后窗口仅覆盖续跑B，A来自保留的原固定checkpoint尝试；其余五个窗口覆盖A+B。' if execution['reused_beam_requests'] else '六模型的内存参数前后窗口均覆盖本次A+B。'
    text=f'''# 阶段47：冻结模型历史扰动与分位置损失检查

日期：2026-11-04（Asia/Hong_Kong）。六个既有128步模型固定，384个beam请求、192个正式teacher-forcing样本完成；0优化更新，未跑完整tuning/dev，未改网站或依赖。首轮数值核验失败和诊断额外开销全部保留。

## 结论与下一步决定

**模型对输入历史有反应，但这批样本上的SID语义位置预测仍弱，值得做一次有上限的128→512步预算验证。** 这是下一次实验的建议，不是已证明增大预算能提升推荐质量；本轮没有追加训练。建议保持基础权重、SID映射、抽样流、有效batch、学习率/优化器与种子固定，保留内容/打乱两臂，不同时改ID设计或加入RL。

历史对调后六模型全部32列表的顺序均有变化，平均Top10 Jaccard约0.27–0.55；不能再笼统说完全忽略历史。另一方面，在固定32训练前缀上，三个语义码位置平均条件NLL六模型均不优于64类均匀预测，且未优于pilot位置频率先验；该小样本结果支持继续检验训练健康/预算，而非宣称SID设计已失效。

## 事前固定的样本与对照

- A：从训练截止画像中分别按固定hash取16个历史长度1、16个长度20的用户。同长组内用原生SciPy最小代价指派一对一置换，排除自配和完全相同历史；全组历史文档边际频率保持不变。接收者的9000目录、正/负seen mask、模型、beam10、精度固定，只改encoder历史。
- B：32个严格训练前缀，pilot事件/监督池未抽事件各16，每类长度1/20各8。来自32个用户，目标不进输入；只用原事件严格更早历史，不用截止画像倒填。未抽事件中有{nonpilot_target_seen}个目标论文已在其他pilot事件出现，不能把该事件分组叫“未见目标论文”。
- 输入、模型、tokenizer、代码和原协议先封存。没有用tuning/dev命中或目标挑样本。抽样只含历史长度两个端点，不代表全体用户；32用户、32前缀在六模型间重复，不能将384请求或960位置当作独立样本作显著性检验。

## A：历史敏感性

Jaccard是同一接收者两个Top10集合的交并比，越低只表示列表变化越大，不表示推荐更好。每行32用户；两种历史的长度、接收者过滤完全一致。

| 运行 | 平均Jaccard | 首位改变 | 列表顺序改变 | 新增捐赠者历史项总数 |
|---|---:|---:|---:|---:|
'''+ '\n'.join(history_table)+f'''

交换历史可能与接收者seen集合不一致，是反事实输入探针，不是真实用户画像更新。新增捐赠者历史项只有0–2个/运行，已单独记录；即使列表变化，也可能是复制输入或分布外效应，不能据此证明理解兴趣、产生质量提升或恢复了旧评价的漏召回。

原生HF中间beam输入、有限合法分支数、最终beam_indices及compute_transition_scores均保存。19200个祖先链接与19200个中间前缀独立核对，返回SID合法、唯一、未读、EOS完整；转移分数和与原生序列分数在1e-4内一致。完整词表每步分数未落盘，只保留可核对的路径/祖先/返回token转移值；该新轨迹只覆盖这32探针，不能追溯旧完整评价的首次剪枝时刻。

## B：分位置损失

前向激活/logits采用BF16 autocast；下列分析NLL将保存于内存的BF16 logits提升到FP32后用原生PyTorch交叉熵重新计算。原生AMP loss另记录，不混用数值口径。位置码本条件NLL先把该位置合法token的概率重新归一化；它不是seen-filtered trie分支NLL。单位为nat，越低越好。

表内范围是六模型各自32样本均值的最小–最大，不是置信区间或单个样本范围。概率质量为该位置码本占完整词表概率之和的逐样本平均。

| 位置 | 完整词表NLL（FP32分析） | 位置条件NLL | 位置码本概率质量 | 完整词表Top1准确率 |
|---|---:|---:|---:|---:|
'''+ '\n'.join(positions_table)+'''

三个语义位置只把约20%–40%的概率质量放在对应码本内；条件化后平均预测也仍接近均匀/频率先验水平。身份码容易受常见消歧码支配，EOS条件码本只有1个token，其条件NLL=0是定义上的必然，不代表EOS在完整词表中总能预测正确。均值不可直接代入逐样本log恒等式。

| 运行 | 三语义码平均条件NLL | 64类均匀NLL | pilot频率先验NLL | 位置条件Top1准确率 | 语义码占总FP32 NLL |
|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(semantic_table)+f'''

先验仅用1024个pilot目标的各位置计数与Laplace α=1，不读取未来标签。Teacher forcing给了真实的先前目标token；这不是自由生成质量。pilot/未抽事件不是随机处理组，位置难度和频率也可能不同，因此不把组间差异解释为训练曝光的因果作用。全部分组（pilot/未抽、历史长短及交叉单元）见position-loss-summary.csv。

## 数值核验失败与修正

{precision_story}

{precision_retention}执行仍用1e-4门槛，只将比较对象改为同AMP路径未约简CE的均值；FP32分解保留并明确标注。24个原生均值核对最大误差{max_amp_error:.8g}，FP32与原AMP批均值最大差{max_precision_delta:.8g}。

384 beam请求没有增加：复用{execution['reused_beam_requests']}，本次新增{execution['new_beam_requests_in_continuation']}。192个正式位置诊断样本之外，另有{execution['numerical_diagnostic_forward_samples']}个数值诊断前向；中断核验前向按{execution['interrupted_first_attempt_teacher_samples_upper_bound']}上界计入，上界总共{execution['teacher_forward_attempt_samples_upper_bound']}样本。中断记录缺少批次索引时采用保守上界。没有将重试隐藏为192总前向，也没有改样本或挑结果。

## 冻结、资源与下一轮边界

六模型内存参数指纹在执行前后相同、全部参数requires_grad=False且grad=None，磁盘checkpoint与旧封存哈希相同。{window_note}旧资产仍另外做全量哈希核验。

- 384请求的可核对beam批次耗时合计{beam_seconds:.3f}秒（包含保留首轮A）；续跑全程{execution['continuation_wall_seconds']:.3f}秒，不含原进程初始化/测试、首轮完整开销及单独数值诊断进程。
- 续跑GPU reserved峰值{costs['gpu_reserved_peak_gib']:.3f}GiB，进程峰值{costs['process_peak_gib']:.3f}GiB。只是小规模诊断成本，不是生产QPS或完整推荐评价耗时。
- 下一轮建议从同一基础权重重跑至512，保留原128及512检查点；先核对128参考可重复性。原128只有模型、缺原生优化器状态，不能声称直接精确续训。
- 使用同一冻结排列的前4096条时，步数和监督曝光随预算共同增长；不能单独归因更多更新或更多数据。其余因素保持固定，继续报告两臂三种子和原完整分母tuning，1801子集只诊断，不选最好种子。
- 六跑128训练实测331.24秒，线性四倍约22.1分钟仅是训练预算估计；需要新运行锁/资源验收，完整解码与计分成本另算。512训练尚未执行，也未证明会提升NDCG/Recall。网站默认、dev和RL保持原状态。

## 交付与复核

协议、续跑锁、19项不同边界测试（7数据＋10张量＋2精度）、独立验证、完整组表和decision.json在reports/stage47。逐用户原始结果在Git忽略data/stage47-health；不公开分发衍生画像、样本或模型。探针只用于训练健康诊断，论文元数据/交互许可与原版本边界不变。

复跑与最终验收见docs/SID_HEALTH_PROBE_V47.md。最终封存入口scripts.verify_sid_health_probe；源实现对照与许可见THIRD_PARTY_NOTICES.md。没有重新训练或在完整tuning/dev上追加推理。
'''
    output.write_text(text,encoding='utf-8')
    print({'report':str(output),'decision':decision['status'],'costs':costs},flush=True)


if __name__=='__main__':main()
