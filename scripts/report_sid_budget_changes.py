"""Aggregate the verified offline audit without changing predictions or selection."""
import csv
from pathlib import Path

from gsearch.quality_protocol import digest,save
from gsearch.sid_budget_audit import ROOT,DATA,read


def pct(value: float | None) -> str:
    return '—' if value is None else f'{100*value:.1f}%'


def main() -> None:
    output=Path('reports/阶段49_512步收益与集中度审计.md')
    if output.exists():raise FileExistsError('Preserve audit report')
    assert read(ROOT/'validation.json')['status']=='passed'
    audit=read(ROOT/'audit.json');runs=audit['runs'];coverage=audit['coverage']
    shares={};table=[];gain_table=[];prefix_table=[];output_table=[];frequency_table=[]
    for run,r in runs.items():
        changes=r['changes']['full'];tr=changes['transitions'];c=r['concentration']
        numerator=r['changes']['exposure:newly_labelled_1025_4096']['gross_positive_ndcg']
        share=numerator/changes['gross_positive_ndcg'] if changes['gross_positive_ndcg'] else None
        shares[run]=share
        table.append(f"| {run} | {tr['new_hit']} | {tr['lost_hit']} | {tr['retained_up']}/{tr['retained_down']} | {changes['weighted_ndcg_delta']:+.9f} | {pct(share)} | {pct(c['top1_user_share_of_gross_positive'])} |")
        for key,v in r['changes'].items():
            if key.startswith('context_exposure:'):
                gain_table.append(f"| {run} | {key.removeprefix('context_exposure:')} | {v['events']} | {v['transitions']['new_hit']} | {v['transitions']['lost_hit']} | {v['weighted_ndcg_delta']:+.9f} |")
        old=r['output']['128'];new=r['output']['512']
        output_table.append(f"| {run} | {old['unique_papers']}→{new['unique_papers']} | {pct(old['top1_max_share'])}→{pct(new['top1_max_share'])} | {old['source_likes_slot_mean']:.2f}→{new['source_likes_slot_mean']:.2f} |")
        before=r['terminal_prefix']['128'];after=r['terminal_prefix']['512'];first=new['prefix'][0]
        prefix_table.append(f"| {run} | {before.get('missing_1',0)}→{after.get('missing_1',0)} | {before['hits']}→{after['hits']} | {pct(first['largest_output_prefix_share'])} | {pct(first['largest_output_prefix_label_share'])} |")
        movement=r['profile_movement'];lost=r['lost_hit_frequency_cooccurrence']
        frequency_table.append(f"| {run} | {movement['added']['source_likes_mean']:.2f} | {movement['removed']['source_likes_mean']:.2f} | {lost.get('with_any_added_higher_source_frequency',0)}/{lost.get('lost_hit_events',0)} |")
        assert r['changes']['rankable_with_context']['transitions']['retained_same']==0
        assert r['changes']['rankable_without_context']['transitions']['retained_same']==86
    threshold_met=sum(shares['content-'+str(seed)] is not None and shares['content-'+str(seed)]>.5 for seed in [42,2024,3407])
    decision={'status':'audit_complete; prioritize_frozen512_history_and_position_prior_probe',
        'heuristic_frozen_before_current_audit':'newly-labelled share>50% gross positive NDCG in>=2of3 content seeds',
        'newly_labelled_gross_positive_shares':shares,'content_seeds_meeting_threshold':threshold_met,
        'fixed1024_repeat4_vs4096_singlepass_priority_triggered':threshold_met>=2,
        'reason':'gains concentrated in few users/papers and source-frequency-heavy outputs; direct new-label group not dominant; indirect exposure effects remain possible',
        'recommended_next':'frozen512 checkpoints: reuse stage47 source-fixed32 profiles/32 strict prefixes, matched history swap and position-loss vs4096-only frequency prior; no full tuning rerun needed for health probe',
        'recommended_next_not_executed':True,'new_training_started':False,'generation_started':False,
        'rl_started':False,'dev_evaluated':False,'default_changed':False,
        'causality_limit':'target-exposure grouping cannot isolate extra optimizer updates from extra exposure; proposed repeat comparison remains useful but not prioritized by this heuristic'}
    save(ROOT/'decision.json',decision)
    # Concrete delivery table: source aggregates plus case identifiers, never user-linked material.
    rows=[
        {'finding':'新增标签不是主要正向贡献组','quantity':'内容三种子35.8%/21.8%/16.0% gross-positive NDCG',
         'case_ids':'S49-003/S49-009/S49-013','interpretation':'目标直接标签曝光不占主导；不能排除共享token/历史带来的间接曝光效果',
         'next_validation':'优先512冻结模型历史扰动与频率先验；固定1024重复训练对照暂缓'},
        {'finding':'内容SID新增/丢失命中并存','quantity':'42:14/1；2024:17/3；3407:5/5',
         'case_ids':'S49-001/S49-004/S49-006/S49-010/S49-011',
         'interpretation':'无神经旧命中保留；不能把净改善写成全局稳定提升',
         'next_validation':'核对旧命中稳定性、相同用户历史敏感性；保留全部退步'},
        {'finding':'收益集中于少数用户/论文','quantity':'内容三种子最大用户占正向NDCG45.7%–68.7%；最大论文45.7%–75.6%',
         'case_ids':'见本地完整贡献记录；最小qid例不保证最大贡献',
         'interpretation':'主指标仍保留全部用户；不能以几个案例代表多数人',
         'next_validation':'如需检验稳健性，预先声明高贡献对象敏感性诊断，不改主结果分母'},
        {'finding':'覆盖收缩且源频率偏高','quantity':'内容覆盖163→54、72→76、99→55；平均源训练赞三种子均上升',
         'case_ids':'S49-001/S49-005/S49-006/S49-007/S49-011',
         'interpretation':'丢失命中时均伴有更高源频率候选新增，只是共现',
         'next_validation':'用固定历史扰动/位置先验区分输入作用和频率作用；不能直接断言挤出因果'},
        {'finding':'终局首层缺失仍占多数','quantity':'内容512为1528/1571/1560个事件（每组1801）',
         'case_ids':'原始终局记录data/stage49-audit/*.terminal-prefix.jsonl',
         'interpretation':'只见终局未覆盖，不知道何时剪枝；EOS/唯一身份合规不等于相关性',
         'next_validation':'只在另行冻结的小样本探针保存原生中间beam，不补造旧轨迹'},
        {'finding':'源论文冷启动未得到改善证据','quantity':'目录内源零赞14事件、其中有历史4事件，全部无命中',
         'case_ids':'该组没有变化案例，不补造典型成功例',
         'interpretation':'仍未抽到训练目标不等于源零赞；样本极小',
         'next_validation':'保留完整分母/分组，继续采用已有内容推荐作为实用默认'},
    ]
    with (ROOT/'audit-table.csv').open('x',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    case_rows='\n'.join(f"| {r['case_id']} | {r['case_type']} |" for r in audit['cases'])
    main_table='\n'.join(f"| {r['finding']} | {r['quantity']} | {r['next_validation']} |" for r in rows)
    syntax_story='协议封存前语法预检发现校验器多余括号，修正后才冻结/执行审计，记录preprotocol-syntax-error.json。' if (ROOT/'preprotocol-syntax-error.json').exists() else '本次没有协议前语法错误记录。'
    validation_story='初版独立校验器在第一跑后因group变量覆盖分组函数失败，保留原协议、源码和validation-failure.log；v2只将该循环变量改名，已通过全量复核，无审计数值、分组或样本改动。修正记录validation-correction.json。没有把失败日志当作成功。' if (ROOT/'validation-failure.log').exists() else '本次直接使用v2校验器完成全量复核；原初版代码作为既有修正来源保留，不额外制造失败。'
    output.write_text(f'''# 阶段49：512步收益、退步与输出集中度审计

日期：2026-11-04，Asia/Hong_Kong。离线复用全部128/512预测与阶段46组件，0训练、0新推理、未读dev、无网站/依赖变更。

**收益存在，但直接新增标签并非主要贡献来源，且收益和输出都较集中；下一步优先检验冻结512模型的历史作用与频率先验。** 不满足本轮事先固定的“新增标签占正向贡献多数”优先触发条件，因此暂缓固定1024重复4轮对比4096单遍的训练试验。这是诊断优先级判断，不能据此否认新增曝光的间接作用。

## 交付审计表

| 发现 | 数量 | 下一步验证 |
|---|---|---|
{main_table}

完整表带典型案例索引和解释边界：audit-table.csv。全部22个最小qid案例在本地ignored的data/stage49-audit/cases.md，含真实标题、原摘要、ID、明确版本、来源链接、最后三篇历史、两组Top10及目标频率。它们不是相关性标注，也不是人为挑选的成功案例。

## 固定口径与证据边界

协议在本轮审计计算前固定，指标/前缀/案例规则与源码哈希见protocol.json。既有tuning质量已在阶段48看过，本轮仍属事后描述性审计，不是未见数据上的预注册检验。离线任务沿用AGENTS的调研例外，实际调用原MetricAccumulator、metrics、final_prefix_status、prefix_coverage及predictions_by_user；不再引入框架。

主分母仍为46352事件/3571用户，目录外39907保留miss；可排序无上下文4644与有上下文1801分开。每条事件贡献使用原指标差×1/(3571×该用户完整事件数)。曝光组贡献可以相加还原总体NDCG差，组内user-macro指标不能这样相加。正向份额分母是所有正事件贡献之和（gross positive），不是可能很小或为负的净增益。没有把六跑复用的用户、论文或事件当成独立样本，也没有显著性宣称。

## 曝光拆分

| 目标论文分组 | 目录论文数 | 全部未来事件 | 有历史且可排序事件 |
|---|---:|---:|---:|
| 前1024已作为标签 | 913 | 1217 | 288 |
| 第1025–4096首次作为标签 | 2014 | 1834 | 484 |
| 完整监督池有目标但4096仍未抽 | 5065 | 3374 | 1020 |
| 源有赞、代理可用时间不满足 | 6 | 6 | 5 |
| 有合规点赞、无下一篇目标 | 2 | 0 | 0 |
| 源训练零点赞 | 1000 | 14 | 4 |
| 目录外 | — | 39907 | 0 |

新增标签2014篇中，**{coverage['newly_labelled_papers_already_in1024_history']}篇已经出现在前1024输入历史中**。新标签论文不等于此前完全未见论文；仍未抽目标也不等于源冷论文。使用严格训练数据计算曝光，未来点赞只做本轮评价/诊断，不选候选或训练数据。

## 新增、退步与收益集中

| 运行 | 新命中 | 丢失命中 | 仍命中升/降位 | 完整分母ΔNDCG | 新增标签占正贡献 | 最大用户占正贡献 |
|---|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(table)+f'''

每行是同一运行的46352事件配对；不同种子计数不可加成独立样本。所有运行仍命中同排名的86事件都属于共同无上下文兜底，有历史神经模型的旧命中没有保留，排名升降数也为0。内容3407新增/丢失都为5仍有正NDCG差，是命中事件的用户权重与排名不同；不是“同样命中数就无变化”。

内容三种子新增标签的gross-positive份额分别35.8%/21.8%/16.0%，仍未抽目标组才贡献更多；该组可通过共享SID token、历史曝光等路径间接受益，审计无法分离额外更新与额外数据的因果作用。最大用户分别贡献55.6%/68.7%/45.7%的正向NDCG，最大论文分别60.97%/75.63%/45.73%。这解释了少数命中也能明显改变宏平均，不代表多数用户改善。

下表仅有上下文且可排序事件；Δ仍以完整用户分母加权，不是条件分母。原生条件组指标另在audit.json。

| 运行 | 目标曝光 | 事件 | 新命中 | 丢失 | 完整分母ΔNDCG |
|---|---|---:|---:|---:|---:|
'''+ '\n'.join(gain_table)+'''

## 覆盖、频率与前缀

只对2128独立有历史用户的Top10统计（每跑21280槽位），不重复计未来事件。源训练点赞数使用相同固定尺度；1024与4096的标签计数另外各自归一化，二者都不等于目录冷启动定义。

| 运行 | 不同论文128→512 | 最常见首位份额128→512 | 槽位论文平均源训练赞128→512 |
|---|---:|---:|---:|
'''+ '\n'.join(output_table)+'''

| 运行 | 新入榜论文平均源赞（按画像槽位） | 出榜论文平均源赞 | 丢失命中伴随更高源频率候选入榜 |
|---|---:|---:|---:|
'''+ '\n'.join(frequency_table)+'''

以上为共同变动的观察；特别是每次入榜候选可有多篇，“任一更高频”门槛较弱，没有可识别的一对一替代或分数反事实。不能据此证明热门论文因果性挤出了目标，也不能笼统说所有模型更偏训练标签高频。

| 运行 | 目标首层终局未覆盖128→512（/1801） | 目标命中128→512 | 512最大首层输出槽位份额 | 该首层4096标签份额 |
|---|---:|---:|---:|---:|
'''+ '\n'.join(prefix_table)+f'''

如content-2024最大首层输出槽位占67.7%，对应训练标签首层份额5.9%。两者是不同分布（Top10输出槽位与训练样本），不是概率校准误差；只说明终局前缀集中值得进一步检查。首层终局未覆盖不等于第一步就被beam剪掉；原128/512完整评价没有保存中间beam分数和祖先，不能补造首次剪枝时刻。

## 典型案例索引

案例选择规则在审计前固定：每个运行×新增/丢失/仍命中升降×目标曝光组，取有历史可排序事件中的最小qid。没有变化的组不造案例；最大贡献对象不保证被最小qid案例覆盖。逐用户/目标可链接明细只在ignored本地案例册与changes.jsonl，公共报告仅列索引。

| 案例 | 分组 |
|---|---|
{case_rows}

## 下一次验证的选择

预先固定的优先级启发式为：新增标签目标贡献超过gross-positive NDCG的50%，且至少两个内容SID种子满足，才优先考虑固定1024重复4轮与4096单遍的同512预算训练。当前满足 **{threshold_met}/3**，不是统计检验。这个对照仍能检验更新/曝光混杂，只是不满足当前的优先触发条件。

建议另行冻结一轮小规模512模型健康对照：复用阶段47的32画像和32严格训练前缀，保持接收者seen、同长历史交换、beam10与六模型不变；用4096训练标签重算位置频率先验，与位置条件损失比较。可复用128归档结果，不需再做完整tuning预测。它只验证历史输入作用与位置预测健康，不证明推荐质量；本轮未执行这个探针，也未加训或进入RL，默认内容推荐保留。

## 验收、错误与复跑

12边界测试通过；12组原完整分数复现到1e-14；独立验证9000论文曝光、278112配对事件、21612终局前缀、59变化事件、12原生条件指标与22案例元数据/选择规则。核心审计{audit['seconds']:.3f}秒不含旧资产哈希、独立核验与报告生成；不是新模型推理成本。

{syntax_story}{validation_story}

说明docs/SID_BUDGET_AUDIT_V49.md，最终验收scripts.verify_sid_budget_changes。旧阶段45/46/47/48保持；数据和模型仍受原交互许可证限制，逐用户衍生不随网站或仓库分发。复用/许可记录见reports/stage49/THIRD_PARTY_NOTICES.md。
''',encoding='utf-8')
    print({'report':str(output),'decision':decision},flush=True)


if __name__=='__main__':main()
