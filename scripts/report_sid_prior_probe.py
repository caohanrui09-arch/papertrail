"""Compare archived128 and frozen512 probes under the same4096 position prior."""
import csv
from pathlib import Path
import statistics

from gsearch.quality_protocol import digest,save
from gsearch.sid_prior_probe import ROOT,DATA,read


def write_csv(path: Path,rows: list[dict]) -> None:
    with path.open('x',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main() -> None:
    output=Path('reports/阶段50_冻结512模型历史与频率先验.md')
    if output.exists():raise FileExistsError('Preserve probe report')
    assert read(ROOT/'validation.json')['status']=='passed'
    protocol=read(ROOT/'protocol.json');execution=read(ROOT/'execution.json')
    metadata={r['sample_id']:r for r in read(DATA/'prefix-exposure.json')}
    history_rows=[];position_rows=[];paired_rows=[];summary={};history_table=[];loss_table=[]
    for run in protocol['models']:
        histories={128:read(Path('data/stage47-health')/run/'history-probe.json'),512:read(DATA/run/'history-probe.json')}
        losses={128:read(DATA/run/'reference128-rescored.json'),512:read(DATA/run/'position-loss.json')}
        summary[run]={}
        for budget in [128,512]:
            h=histories[budget];loss=losses[budget]
            h_summary=None
            for group in ['all','history1','history20']:
                rows=[r for r in h['paired'] if group=='all' or r['history_length']==int(group.removeprefix('history'))]
                row={'run':run,'model_steps':budget,'group':group,'profiles':len(rows),
                    'jaccard_mean':statistics.mean(r['jaccard'] for r in rows),
                    'top1_changed':sum(not r['top1_equal'] for r in rows),'ordered_changed':sum(not r['ordered_equal'] for r in rows),
                    'footrule_mean':statistics.mean(r['footrule_missing_rank11_div110'] for r in rows),
                    'new_donor_history_items':sum(r['newly_returned_donor_history_items'] for r in rows)}
                history_rows.append(row)
                if group=='all':h_summary=row
            groups=['all','pilot','pool_not_pilot','history1','history20','paper:first1024','paper:added1025to4096','paper:not_labelled4096']
            for group in groups:
                rows=[r for r in loss['samples'] if group=='all' or r['exposure_group']==group or
                    group=='history'+str(r['history_length']) or group=='paper:'+metadata[r['sample_id']]['target_paper_exposure']]
                if not rows:continue
                for pos in range(5):
                    records=[r['positions'][pos] for r in rows]
                    position_rows.append({'run':run,'model_steps':budget,'group':group,'position':records[0]['position'],'samples':len(records),
                        'full_vocab_nll_fp32':statistics.mean(r['full_vocab_nll'] for r in records),
                        'native_amp_full_vocab_nll':statistics.mean(r['native_amp_full_vocab_nll'] for r in records),
                        'position_conditional_nll':statistics.mean(r['position_conditional_nll'] for r in records),
                        'position_mass':statistics.mean(r['position_mass'] for r in records),
                        'uniform_nll':records[0]['uniform_position_nll'],
                        'label1024_prior_nll':statistics.mean(r['label1024_position_prior_nll'] for r in records),
                        'label4096_prior_nll':statistics.mean(r['label4096_position_prior_nll'] for r in records),
                        'position_top1_accuracy':statistics.mean(float(r['position_top1_correct']) for r in records),
                        'label4096_prior_top1_accuracy':statistics.mean(float(r['label4096_prior_top1_correct']) for r in records)})
            semantic=[p for r in loss['samples'] for p in r['positions'][:3]]
            sem={key:statistics.mean(p[field] for p in semantic) for key,field in [
                ('conditional_nll','position_conditional_nll'),('full_vocab_nll_fp32','full_vocab_nll'),
                ('position_mass','position_mass'),('uniform_nll','uniform_position_nll'),
                ('prior1024_nll','label1024_position_prior_nll'),('prior4096_nll','label4096_position_prior_nll')]}
            sem['position_top1_accuracy']=statistics.mean(float(p['position_top1_correct']) for p in semantic)
            sem['prior4096_top1_accuracy']=statistics.mean(float(p['label4096_prior_top1_correct']) for p in semantic)
            sem['conditional_minus_common4096_prior_nll']=sem['conditional_nll']-sem['prior4096_nll']
            summary[run][str(budget)]={'history':h_summary,'semantic':sem}
        old_pairs={r['user_key']:r for r in histories[128]['paired']}
        for row in histories[512]['paired']:
            paired_rows.append({'run':run,'history_length':row['history_length'],
                'jaccard512_minus128':row['jaccard']-old_pairs[row['user_key']]['jaccard'],
                'top1_changed128':not old_pairs[row['user_key']]['top1_equal'],'top1_changed512':not row['top1_equal']})
        old=summary[run]['128'];new=summary[run]['512']
        assert old['semantic']['prior4096_nll']==new['semantic']['prior4096_nll']
        history_table.append(f"| {run} | {old['history']['jaccard_mean']:.4f} | {new['history']['jaccard_mean']:.4f} | {old['history']['top1_changed']}→{new['history']['top1_changed']}/32 | {new['history']['ordered_changed']}/32 | {new['history']['new_donor_history_items']} |")
        loss_table.append(f"| {run} | {old['semantic']['conditional_nll']:.4f} | {new['semantic']['conditional_nll']:.4f} | {new['semantic']['prior4096_nll']:.4f} | {new['semantic']['conditional_minus_common4096_prior_nll']:+.4f} | {100*new['semantic']['position_top1_accuracy']:.2f}% |")
    write_csv(ROOT/'history-comparison.csv',history_rows);write_csv(ROOT/'position-comparison.csv',position_rows)
    write_csv(ROOT/'history-paired-changes.csv',paired_rows)
    beats_prior=[run for run,r in summary.items() if r['512']['semantic']['conditional_nll']<r['512']['semantic']['prior4096_nll']]
    improves_loss=[run for run,r in summary.items() if r['512']['semantic']['conditional_nll']<r['128']['semantic']['conditional_nll']]
    less_sensitive=[run for run,r in summary.items() if r['512']['history']['jaccard_mean']>r['128']['history']['jaccard_mean']]
    decision={'status':'fixed512_probe_complete; training_remains_deferred','semantic_nll_better_than128_runs':improves_loss,
        'semantic_nll_better_than_common4096_marginal_prior_runs':beats_prior,
        'mean_jaccard_increased_runs':less_sensitive,'interpretation':'small source-only health/sensitivity probe, not relevance or preference understanding',
        'training_started':False,'rl_started':False,'full_tuning_or_dev_rerun':False,'default_changed':False,
        'recommendation':'retain practical content default; record generative result as research comparison; any further quality/architecture experiment needs separate evidence and a frozen design'}
    save(ROOT/'decision.json',decision)
    costs={'wall_seconds':execution['wall_seconds'],
        'beam_batch_seconds':sum(b['seconds'] for run in protocol['models'] for b in read(DATA/run/'history-probe.json')['batches']),
        'gpu_reserved_peak_gib':max(r['gpu_reserved_peak_bytes'] for r in execution['costs'])/2**30,
        'process_peak_gib':max(r['process_peak_bytes'] for r in execution['costs'])/2**30,
        'max_native_amp_mean_error':max(b['native_amp_abs_error'] for run in protocol['models'] for b in read(DATA/run/'position-loss.json')['native_batch_checks'])}
    save(ROOT/'summary.json',{'protocol_sha256':digest(ROOT/'protocol.json'),'runs':summary,'costs':costs,'decision':decision})
    paper_counts={group:sum(r['target_paper_exposure']==group for r in metadata.values()) for group in ['first1024','added1025to4096','not_labelled4096']}
    position_table=[]
    for position in ['semantic1','semantic2','semantic3','identity','eos']:
        rows=[r for r in position_rows if r['model_steps']==512 and r['group']=='all' and r['position']==position]
        def span(field):return f"{min(r[field] for r in rows):.4f}–{max(r[field] for r in rows):.4f}"
        position_table.append(f"| {position} | {span('full_vocab_nll_fp32')} | {span('position_conditional_nll')} | {span('label4096_prior_nll')} | {span('position_mass')} |")
    output.write_text(f'''# 阶段50：冻结512模型的历史敏感性与位置频率先验

日期：2026-11-04，Asia/Hong_Kong。六个512模型冻结，384个小样本beam请求、192个teacher-forcing样本完成；0优化更新，无完整tuning/dev解码、RL或网站/依赖变化。原128结果从归档读取，只离线重新计算先验，不重新推理。

## 结论

相对归档128，六模型中有 **{len(improves_loss)}/6** 的三语义位置平均条件NLL降低；但只有 **{len(beats_prior)}/6** 优于同一个4096标签位置频率先验。有 **{len(less_sensitive)}/6** 的历史交换平均Jaccard升高（表示列表更相近，不表示推荐更好）。这些只是固定32样本上的健康/敏感性证据，训练继续暂缓，实用内容推荐默认保留。

## 样本、先验与公平比较

原样复制阶段47的32画像（历史长度1/20各16）和32严格训练前缀，字节哈希相同，没有按阶段48/49结果重选。历史同长度一对一交换，接收者目录、seen mask、beam10、BF16及batch16不变。全组历史文档频次保持，反事实历史可能与接收者seen不一致，因此另报新增捐赠者历史项。

32前缀仍为16个旧pilot事件和16个4096仍未选事件；目标论文曝光则为{paper_counts['first1024']}个前1024已标签、{paper_counts['added1025to4096']}个新增标签、{paper_counts['not_labelled4096']}个仍未标签。事件未选不等于目标未见，标签未见也不等于输入历史未见。目标不进encoder输入，历史时间严格早于目标。

先验只由冻结训练排列前1024/4096标签的各位置计数构建，Laplace α=1、位置码本64/64/64/11/1。**同一SID映射内，两个模型预算都使用同一个4096先验**；内容/打乱映射各自计算token计数。旧128的原模型损失原样保留，只重新计算基线NLL；1024先验也保留。不能把不同先验间的差异误当作模型进步。

## 历史敏感性

| 模型 | 128平均Jaccard | 512平均Jaccard | 首位改变128→512 | 512列表顺序改变 | 512新增捐赠者历史项总数 |
|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(history_table)+f'''

Jaccard是两种历史Top10集合的交并比，更大表示输出集合变化更小。长度分组、footrule及逐画像配对变化见history-comparison.csv/history-paired-changes.csv；同32用户在六模型重复，不能当192个独立用户作显著性推断。历史敏感性不等于兴趣理解；更敏感或更不敏感都不能直接证明推荐质量。没有在这些反事实历史上计算相关性分数。

## 三语义位置与同一频率先验

以下是每模型32前缀×3语义位置的平均，单位nat，越低越好。均匀64类NLL为4.1589。正的“模型−先验”表示模型更差。Top1是位置码本内准确率，不是论文推荐命中率。

| 模型 | 128位置条件NLL | 512位置条件NLL | 共用4096先验NLL | 512模型−先验 | 512位置Top1 |
|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(loss_table)+'''

完整词表NLL与位置码本内归一化NLL分开；后者不是seen-filtered trie分支NLL。Teacher forcing向模型提供先前真实目标token，而位置频率先验不看历史或先前目标token，因此先验是弱参照；即使模型优于它，也可能来自目标token间依赖，不能独立证明个性化。频率先验不是已评价的目录级排序器。

| 512位置 | FP32完整词表NLL | 位置条件NLL | 4096先验NLL | 码本概率质量 |
|---|---:|---:|---:|---:|
'''+ '\n'.join(position_table)+f'''

范围表示六模型各自32样本均值的最小–最大，不是置信区间。EOS条件码本只有1个token，其NLL=0是定义必然，不代表完整词表EOS预测总正确。分组位置数据和完整/AMP口径见position-comparison.csv，包含旧pilot/未抽事件、历史长短及目标论文曝光组；新增标签只有4前缀，不能外推该组质量。

## 执行与核验

直接复用原生HF generate/beam_indices/compute_transition_scores和阶段47身份观察器，分数原样返回；直接调用原生PyTorch CE，不重写beam或训练框架。前向BF16 logits的显式FP32分析CE与原生AMP loss分别保存，均值只在相同AMP口径比较，容差仍1e-4；最大误差{costs['max_native_amp_mean_error']:.8g}。

六模型完整A+B窗口的内存参数指纹前后相同，磁盘checkpoint哈希不变；全部requires_grad=False且grad=None。20项不同测试（8先验＋10张量＋2精度）、384请求/19200中间前缀/19200原生祖先链接、960新位置与960旧位置先验重算、24同AMP均值独立核对。完整词表logits未落盘，不能声称可从保存的全logits重算全部概率。

新probe执行窗口{costs['wall_seconds']:.3f}秒，可核对beam批次合计{costs['beam_batch_seconds']:.3f}秒，GPU reserved峰值{costs['gpu_reserved_peak_gib']:.3f}GiB、进程峰值{costs['process_peak_gib']:.3f}GiB。窗口不含Python初始化、协议哈希及边界测试；process_peak为进程累计高水位。这不是生产QPS，也不将与旧128的耗时差归因算法加速。

本轮模型探针没有失败重试或额外模型前向；两项随机logits精度测试是合成张量测试，不计入192个模型teacher样本。旧阶段47的历史失败与额外诊断开销仍在原收据内，没有改写为新的成功成本。

## 交付与边界

protocol/validation/execution/summary/decision与三份CSV在reports/stage50。逐用户画像、原生路径、分位置损失和重评分在ignored data/stage50-health，不随网站或公共仓库分发。旧阶段45–49不变。说明docs/SID_PRIOR_PROBE_V50.md；验收scripts.verify_sid_prior_probe；许可与复用见本阶段THIRD_PARTY_NOTICES。

这是源训练前缀的小样本诊断，不能替代新相关性标注、未用过的质量评价或当前完整tuning结果；没有证明新的NDCG/Recall收益。后续若需要更强的无历史参照，应另行冻结包含前序SID条件的频率基线或目录排序对照，不用本轮位置边际先验冒充等信息基线。本轮训练继续暂缓、不进入RL，默认保持。
''',encoding='utf-8')
    print({'report':str(output),'better_than128':improves_loss,'beats_common4096_prior':beats_prior,
        'mean_jaccard_increased':less_sensitive,'costs':costs},flush=True)


if __name__=='__main__':main()
