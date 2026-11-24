"""Generate audit tables from actual sealed runs; no hand-entered quality numbers."""
import csv
import json
from pathlib import Path
import statistics

from gsearch.quality_protocol import digest,save

ROOT=Path('reports/stage45')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main() -> None:
    output=Path('reports/阶段45_SID与受控SFT试验.md')
    if output.exists():raise FileExistsError('Preserve generated report')
    results=read(ROOT/'tuning-results.json');lock=read(ROOT/'run-lock.json')
    runs=[read(p) for p in sorted(Path('runs/stage45').glob('*/training.json'))]
    costs=[read(p) for p in sorted(Path('runs/stage45').glob('*/prediction-cost.json'))]
    baseline=read(ROOT/'baseline-cost.json')
    metrics=results['three_seed_summary']
    rows=[]
    for name in ['popular','content','sar']:
        result=results['all_comparisons'][name]['user_macro']
        rows.append(f"| {name} | {100*result['ndcg@10']:.4f}% | {100*result['recall@10']:.4f}% | {100*result['mrr@10']:.4f}% |")
    for arm in ['content','shuffled']:
        values=metrics[arm]
        rows.append('| '+arm+' SID（三种子均值±样本SD） | '+' | '.join(
            f"{100*values[key]['mean']:.4f}% ± {100*values[key]['sample_sd']:.4f}%" for key in ['ndcg@10','recall@10','mrr@10'])+' |')
    deltas=results['paired_content_minus_shuffled_ndcg']
    paired=', '.join(f'{100*d:+.4f}个百分点' for d in deltas)
    best_baseline=max(results['all_comparisons'][name]['user_macro']['ndcg@10'] for name in ['popular','content','sar'])
    content_mean=metrics['content']['ndcg@10']['mean']
    judgement=('内容SID三种子均优于打乱SID，但这里只支持当前映射与当前小预算的配对观察；不能据此宣称普遍或显著收益。'
               if all(d>0 for d in deltas) else '内容SID相对打乱SID没有三种子一致的正向结果；当前不能宣称语义ID提高推荐质量。')
    if content_mean<=best_baseline:
        judgement+=' 内容SID均值未超过本轮最佳传统基线，继续保留原网站默认方法，不进入RL。'
    else:
        judgement+=' 内容SID均值超过本轮传统基线；仍需更充分训练、误差分析及未使用时段验证，网站默认方法不变，不进入RL。'
    group_rows=[]
    for name,result in results['all_comparisons'].items():
        for group,values in result['groups'].items():
            group_rows.append({'method':name,'group':group,'events':values['events'],'users':values['users'],**values['user_macro']})
    with (ROOT/'group-results.csv').open('x',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(group_rows[0]));writer.writeheader();writer.writerows(group_rows)
    curves=[]
    for run in runs:
        for row in run['log_history']:
            if 'loss' in row:curves.append({'arm':run['arm'],'seed':run['seed'],'step':row['step'],'loss':row['loss']})
    with (ROOT/'training-curves.csv').open('x',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['arm','seed','step','loss']);writer.writeheader();writer.writerows(curves)
    extrapolation=sum(r['elapsed_seconds'] for r in runs)*(98887/1024)/3600
    neural_times=[c['neural_amortized_seconds_per_user'] for c in costs]
    summary={'training_seconds':sum(r['elapsed_seconds'] for r in runs),
        'training_reserved_gib':max(r['gpu_reserved_bytes'] for r in runs)/2**30,
        'training_process_peak_gib':max(r['process_peak_bytes'] for r in runs)/2**30,
        'prediction_seconds':sum(c['elapsed_seconds'] for c in costs),
        'prediction_reserved_gib':max(c['gpu_reserved_bytes'] for c in costs)/2**30,
        'neural_amortized_ms_range':[1000*min(neural_times),1000*max(neural_times)],
        'full_one_epoch_six_runs_naive_hours':extrapolation,
        'extrapolation_caveat':'linear pilot scaling only, not a scheduled run or validated full-training duration'}
    save(ROOT/'cost-summary.json',summary)
    body=f'''# 阶段45：9000篇SID与受控SFT试验

日期：2026-11-03（Asia/Hong_Kong）。交付为本机离线非商业研究；网站、旧目录、旧实验和依赖不改。

## 结论

{judgement}

已完成两组SID、原始token-ID监督、实际训练配置封存、资源与真实解码预检、六个SFT运行、三条基线及完整tuning评价。本轮不读dev标签、不启动RL、不改变产品默认方案。没有新独立测试、真人相关性或线上收益证据。

## 监督、结构与受控条件

9000篇明确v1训练时目录；98887条真实时序监督，每臂494435目标token。每跑实际消费1024条、5120目标token（约1.04%监督池）；128次更新、batch8、三种子42/2024/3407，固定排列与预算。T5-small原始权重/tokenizer哈希、两臂映射、训练顺序、代码和基线均在训练前封存。每对种子新增词嵌入初始化哈希相同。见run-lock.json（SHA256 `{digest(ROOT/'run-lock.json')}`）。

复用官方PRQ CPU，文本输入是训练目录的TF-IDF+SVD128，不是官方预训练文本编码器；9000篇全部有唯一可逆token-ID序列。原始1197次超额碰撞/2046篇受影响论文由身份后缀消歧；内容与打乱两组保留相同完整SID及树结构，碰撞组不变、6954篇单例按训练频率桶打乱。身份后缀不构成语义。结构近邻保留仅为输入表示自洽，不是论文相关性或推荐效果。

先于正式训练完成两臂各4次dry backward，无optimizer更新；beam10/EOS/已读正负mask/唯一ID/重复输入与附加遮挡通过。随后丢弃dry模型，从相同基础权重训练。18个适配边界测试、全量两臂98887条源到token核验及20个封存评价边界测试通过。计分适配另有10个对抗等价测试，九组各512条固定索引真实事件与原evaluate逐字段相同。

## tuning结果：全部正反馈分母

46352条正反馈，3571名用户；先在用户内平均，再对用户平均。目录外目标也计入漏召回。所有预测槽位有效且无重复。每模型处理2128名有历史用户；1443名空画像用户与基线统一使用冻结流行度。下列均为百分数，SD是三种子样本标准差。

| 方法 | user-macro NDCG@10 | Recall@10 | MRR@10 |
|---|---:|---:|---:|
'''+ '\n'.join(rows)+f'''

内容−打乱的配对NDCG差（种子42/2024/3407）：{paired}。只保存预先固定的128步，没有按tuning追加训练或隐去较弱种子。原始逐跑分数见tuning-results.json，冷热用户/论文结果见group-results.csv及每个score.json；不根据单个种子或微小差值宣称显著性。

三条基线共享9000目录、last20正反馈历史及全部训练已见屏蔽。SAR调用官方Jaccard拟合7994篇有合规训练正反馈的论文，其余1006篇协同分数为0，三例评分与原生pseudo-history接口一致；内容用同一训练目录冻结TF-IDF，空画像全方法统一popularity。传统基线使用完整训练反馈，SFT只使用1024条监督，因此基线是实用参考，不能当成相同训练曝光量对照；两组SID才是相同SFT预算的受控比较。所有预测生成后，独立CPU进程直接复用阶段44封存计分器读取标签。

## 资源与成本

| 项目 | 实测 |
|---|---:|
| 文本表示、官方量化与结构审计 | 21.31秒；进程峰值374.61MiB |
| 六跑SFT训练合计 | {summary['training_seconds']:.2f}秒 |
| 单跑训练范围 | {min(r['elapsed_seconds'] for r in runs):.2f}–{max(r['elapsed_seconds'] for r in runs):.2f}秒 |
| SFT最大GPU reserved | {summary['training_reserved_gib']:.3f}GiB |
| SFT进程峰值 | {summary['training_process_peak_gib']:.3f}GiB |
| 六模型tuning预测合计 | {summary['prediction_seconds']:.2f}秒 |
| 预测最大GPU reserved | {summary['prediction_reserved_gib']:.3f}GiB |
| 神经部分每用户摊销（batch16） | {min(neural_times)*1000:.2f}–{max(neural_times)*1000:.2f}毫秒 |
| 三基线联合拟合/打分 | {baseline['total_seconds']:.2f}秒；SAR拟合{baseline['fit_sar_seconds']:.2f}秒 |

预测为离线batch16，固定画像复用、同用户多事件复用列表；摊销时延不是单请求p95或生产QPS。基线成本是三方法联合测量，不能伪装成各方法独立延迟。训练耗时不包含进程导入、读取/哈希、保存与计分；预测总耗时范围见prediction-cost.json。按pilot线性换算六跑各完整一遍98887样本约{extrapolation:.2f}小时，只是粗略预算，未实际执行，也不是已承诺的训练时长。独立CUDA包清单保持原38项，无依赖安装。

## 限制与下一步依据

固定目录内可排序目标仅6445/46352（13.90%）；用户平均可排序比例10.84%仅宽松oracle覆盖上限。目录外漏召回不可能靠SID模型消除。无训练点赞目标只有14条，不能声称稳定冷论文提升。量化seed42与打乱seed2024各一套；三种子只反映训练随机性，不代表量化或映射总体方差。元数据的时间可用性仍为明确的保守代理，非历史线上日志；旧tuning/dev已参与前期研究，不能把重新封存当作新盲测。

下一步先依据原始错误与目录覆盖拆分收益来源，再决定扩大训练；不直接加大训练量或进入RL。要改变预算/基础模型/映射，另建版本，保留本轮全部运行、失败、预测和配置，不覆盖本轮选择。

## 复跑、来源与失败记录

命令及文件说明见 `docs/SID_SFT_V45.md`；来源/许可/安全与适配对比见 `reports/stage45/THIRD_PARTY_NOTICES.md`。首次GPU入口因共享环境无pandas而在训练前失败，保留initial-import-failure.log；改为JSONL适配并在原CPU环境复用计分器，未安装共享依赖。未丢弃失败的正式训练或预测。

原计分器对每条空画像事件重复排序9000篇，原入口在尚未生成分数文件时中止，按scoring-addendum.json先冻结操作优化再计分：全用户预测一致性逐行核对后，只合并不变画像的共同兜底检查，实际全部46352事件仍调用原score_rows。阶段44公式、文件、阈值和阶段45训练锁没有变；10个对抗测试和九组各512条真实事件的逐字段比较见real-scoring-equivalence.json。原全数据慢入口没有完成，不虚报全数据独立实现对照或加速倍数。

模型、逐用户监督/预测/轨迹仅在Git忽略data/与runs/，遵守已有本地非商业研究范围，不作为公开数据包、网站访客数据或可商业分发权重。旧阶段43的103项资产和阶段44的34项资产另行核验；本轮最终哈希收据见final-validation.json。
'''
    output.write_text(body,encoding='utf-8')
    print({'report':str(output),'cost':summary,'paired_ndcg_delta':deltas},flush=True)


if __name__=='__main__':main()
