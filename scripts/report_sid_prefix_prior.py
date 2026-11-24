"""Freeze the diagnosis closure, tradeoffs and verifiable resume supplement."""
import csv
from pathlib import Path
import statistics

from gsearch.quality_protocol import save
from gsearch.sid_prefix_prior import ROOT,read


def main() -> None:
    output=Path('reports/阶段51_SID前缀先验与诊断收尾.md')
    supplement=Path('docs/SID_EXPERIMENT_CLOSURE_V51.md')
    if output.exists() or supplement.exists():raise FileExistsError('Preserve closure materials')
    assert read(ROOT/'validation.json')['status']=='passed'
    comparison=read(ROOT/'comparison.json');decision=read(ROOT/'decision.json')
    with (ROOT/'four-method-comparison.csv').open(encoding='utf-8-sig',newline='') as handle:
        aggregate=list(csv.DictReader(handle))
    table=[]
    for run,r in comparison['summary'].items():
        table.append(f"| {run} | {r['marginal_nll']:.4f} | {r['prefix_nll']:.4f} | {r['model128_nll']:.4f} | {r['model512_nll']:.4f} | {r['model512_minus_prefix_nll']:+.4f} |")
    position_table=[];exposure_table=[]
    for arm in ['content','shuffled']:
        for position in ['semantic1','semantic2','semantic3','identity','eos']:
            rows=[r for r in aggregate if r['run'].startswith(arm+'-') and r['group']=='all' and r['position']==position]
            values=[statistics.mean(float(r[field]) for r in rows) for field in ['marginal_nll','prefix_nll','model128_nll','model512_nll']]
            position_table.append(f"| {arm} | {position} | "+' | '.join(f'{v:.4f}' for v in values)+' |')
        for group in ['event:first1024','event:not_selected4096','paper:first1024','paper:added1025to4096','paper:not_labelled4096']:
            rows=[r for r in aggregate if r['run'].startswith(arm+'-') and r['group']==group and r['position']=='semantic_mean']
            values=[statistics.mean(float(r[field]) for r in rows) for field in ['marginal_nll','prefix_nll','model128_nll','model512_nll']]
            exposure_table.append(f"| {arm} | {group} | {rows[0]['samples']} | "+' | '.join(f'{v:.4f}' for v in values)+' |')
    old=read(Path('reports/stage48/summary.json'));baseline=read(Path('reports/stage45/content.tuning.score.json'))
    before=old['metrics']['content']['128']['ndcg@10']['mean'];after=old['metrics']['content']['512']['ndcg@10']['mean']
    baseline_ndcg=baseline['user_macro']['ndcg@10']
    closed=decision['closure_condition_met'];status='关闭当前设计下的预算加量路线' if closed else '本轮诊断收尾，训练继续暂缓'
    text=f'''# 阶段51：SID前缀条件频率基线与诊断收尾

日期：2026-11-04，Asia/Hong_Kong。**{status}。** 六个512模型中{len(decision['model512_runs_beating_prefix_prior'])}/6的三语义平均条件NLL优于匹配前缀先验；本轮只做CPU计数和归档损失对照，0训练、0模型前向/解码，无RL、dev、网站或依赖变化。

## 固定定义

对位置j，前缀只含真实目标SID的第0到j−1个token。用冻结训练顺序前4096标签，计算：

`P(s_j | s_<j) = (count(s_<j, s_j)+1) / (count(s_<j)+K_j)`。

K为与保存的模型位置条件NLL完全相同的完整位置码本，依次64/64/64/11/1，**不改为目录树子节点集**。未见上下文count=0时均匀分布，不回退到边际先验。第一位置空前缀等于4096边际先验；EOS的K=1使NLL恒为0，不能当作学习能力。

直接复用collections.Counter与阶段50的Laplace NLL实现；新代码只准备前缀上下文计数和同口径比较，不引入训练/解码框架或新包。本轮属于离线小适配，沿用AGENTS的额外调研例外；没有把计数参照称作原创推荐算法。

## 四组主对照

同阶段47/50原32严格训练前缀，不按当前结果挑例。每跑主要判据为32×3个语义位置的平均NLL（nat，越低越好）；六模型复用同一批样本，不将576个语义记录当作独立用户。正的512−先验意味着模型更差。原128/512 NLL均直接读取已封存位置条件损失，不需要完整logits或新前向。

| SID与种子 | 4096位置先验 | 4096前缀先验 | 128步模型 | 512步模型 | 512−前缀先验 |
|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(table)+f'''

规则在本轮计算前固定：若没有任何512跑的主NLL比对应前缀先验低超过1e-12，就结束当前预算加量路线；否则只记混合证据、保持训练暂缓，也不自动进入RL。实际触发关闭条件：{closed}。这是项目取舍门槛，不是统计显著性检验，亦不证明更大模型或其他设计永远无效。

## 分位置结果

下表为每臂三个种子的描述性均值，先验在同映射内相同。身份码、EOS不混入主要三语义指标；没有用容易的后缀平均掉语义位置问题。

| SID | 位置 | 位置先验 | 前缀先验 | 128模型 | 512模型 |
|---|---|---:|---:|---:|---:|
'''+ '\n'.join(position_table)+'''

## 训练曝光分组

每行样本数是32前缀中的独立前缀数，不乘三个种子。event按该监督事件是否被4096抽到划分，paper按目标论文是否曾在标签中出现划分；两个分组维度不能相加。原1024抽到的16事件仍在4096，另16事件仍未抽到；目标论文为18旧标签、4新增、10仍未标签。每种SID的三种子均值仅作描述，完整逐种子/历史长度分组在four-method-comparison.csv。

| SID | 分组 | 前缀数 | 位置先验 | 前缀先验 | 128模型 | 512模型 |
|---|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(exposure_table)+f'''

## 解释边界

- 前缀先验与teacher forcing模型都看到真实的先前SID；先验没有用户encoder历史，而模型还有历史信息。未做目录级先验排序或生成，因此不能把先验NLL胜出写成推荐Recall/NDCG胜出。
- 先验使用整个4096标签，包括16个已选查询事件自身，不做leave-one-out；512模型同样训练过这些事件。其余16事件未抽到，也不等于目标论文没在其他标签或输入历史出现。样本来自训练源，不能称独立测试。
- 128模型只有1024条训练预算，而两项先验及512模型使用4096标签；128是归档参考，不声称等数据预算。标签计数按各自SID映射构建，内容/打乱先验不同，但同映射内对两个模型预算一致。
- 本轮损失是完整位置码本内归一化的条件损失，不是完整词表NLL或seen-filtered trie分支损失。原始logits未保留，本轮没有重新计算模型概率，只核对存档值与参照。
- 主要均值收尾不等于每个位置或每个曝光子组都落后；全部细分仍保留，不选择有利子组替代事前主判据。无显著性、个性化有效、CTR、生产QPS或新泛化结论。

## 最终实验取舍

1. 保留阶段45/48的9000唯一SID、原始token-ID监督、HF原生Trainer/beam与合法ID/已读过滤链路，作为可复现研究实现；不冒充MiniOneRec完整模型复现。
2. 内容SID的完整tuning NDCG均值由{before:.9f}到{after:.9f}，但仍低于内容推荐基线{baseline_ndcg:.9f}；目录外39907/46352事件保留miss，三种子内容−打乱仍2正1负，不能写线上或稳定泛化收益。
3. 阶段49发现收益集中和覆盖收缩；阶段50显示仍响应历史但平均集合变化减小，且位置边际先验未被超过。本轮补齐前序SID信息后仍不满足主参照，{status}，不继续默认加步数/叠RL。
4. 保留现有内容推荐默认和完整失败/对照证据；重新开启需新的具体假设及冻结设计，不把项目其他搜索/阅读/推荐功能随实验关闭。

## 验收与交付

10项边界测试通过；独立逐源重建每映射4096标签，检查320个查询和14369个已观测上下文分布归一化、1920个归档模型位置损失、960条宽表和288个聚合行。旧32前缀不变，第一位置等于边际、未见上下文均匀、EOS零损失均验证。核心CPU比较{comparison['seconds']:.3f}秒，不含旧资产哈希/独立验证/报告，不是模型推理性能。

本轮无执行失败或重试；旧模型/数据/报告不改。源样本、计数和逐前缀记录仅ignored data/stage51-prefix-prior；公开材料只用聚合和来源索引，许可范围不变。复核scripts.verify_sid_prefix_prior；运行说明docs/SID_PREFIX_PRIOR_V51.md；简历/面试补充docs/SID_EXPERIMENT_CLOSURE_V51.md；许可见本阶段THIRD_PARTY_NOTICES.md。
'''
    output.write_text(text,encoding='utf-8')
    supplement.write_text(f'''# SID生成式推荐：实验收尾与简历证据补充

截至2026-11-04。该文件补充现有RESUME_2026/INTERVIEW_2026，不改写其已封存版本；仅涵盖阶段43–51的SID研究，不替代整项目的搜索、推荐、Agent证据。

## 可直接采用的精简条目

构建9000篇论文的SID生成式推荐实验，复用MiniOneRec CPU量化组件、Hugging Face Seq2SeqTrainer和ZeroGR约束树，完成双SID、三种子128/512步受控训练；通过曝光分组、历史扰动及无历史前缀频率参照定位输出集中与语义位置预测不足，保留内容推荐默认并完成可复现封存。

## 算法岗位展开版（按简历空间选用）

- 在9000篇论文目录上构建唯一可逆SID及原始token-ID监督，接通时序历史到下一篇的T5训练、beam10合法ID约束与统一已读过滤；训练器、量化器和树组件明确复用上游实现。
- 固定基础权重、两组SID、样本顺序与三个种子完成128→512步预算对照，128检查点与旧模型逐张量一致；完整未来反馈分母评价并区分用户冷启动、论文冷启动与目录覆盖。
- 将命中迁移、用户/论文收益集中度、终局前缀、冻结模型历史扰动和同SID前缀先验接成诊断链；据实用基线及损失参照关闭当前加量路线，保留全部对照、原始输出和复核入口。

## 数字及证据映射

| 可核验事实 | 来源 | 使用边界 |
|---|---|---|
| 9000唯一SID、两映射、原始token标签 | reports/stage45/tokenization.json及data-validation.json | 研究实现，不是原创量化算法或MiniOneRec完整复现 |
| 两臂三种子，每跑512步；128逐张量重现 | reports/stage48/validation.json与各reference128-gate.json | 六跑新训练，128检查点包含在512预算内，不是从旧缺优化器模型精确续训 |
| 内容SID NDCG {before:.9f}→{after:.9f}；内容基线{baseline_ndcg:.9f} | reports/stage48/tuning-results.json及summary.json | 重复用过的tuning，46352完整正反馈分母；预算和曝光同时变化，不写CTR或独立泛化 |
| 内容三个种子新增/丢失命中14/1、17/3、5/5 | reports/stage49/audit.json | 同一批事件跨种子重复，不能汇总为36个独立成功或新论文 |
| 384冻结512小请求、32画像及32严格前缀、0更新 | reports/stage50/execution.json及validation.json | 输入敏感性和训练健康，不等于个性化有效 |
| 六个512跑均未超过前缀参照的三语义平均NLL | reports/stage51/decision.json与four-method-comparison.csv | 训练前缀loss诊断，不是推荐排序胜负；不能外推所有生成式方法无效 |

## 面试说明

**为什么停止加量？** 当前内容SID在完整tuning上仍低于内容推荐；增益集中于少数用户/论文，部分种子输出覆盖明显收缩。32训练前缀上，512模型也没有超过仅依赖前序真实SID的频率参照。因此当前设计缺少继续加量的实证依据，选择保留实用默认，而不是直接叠RL。这个决定只针对当前T5/映射/监督设计，不宣称该方向没有上限。

**为什么前缀先验比位置先验更合适？** teacher forcing模型看到先前真实目标token。位置边际先验没有该信息；前缀先验补齐了这一参照，仍不使用用户历史。它是token损失参照，不能直接当作已经测过Top10的推荐系统。

**为何NDCG很低？** 采用逐未来点赞事件、先用户内再跨用户平均，目录外39907/46352仍计miss。必须交代分母和目录覆盖；也仍有真实排序差距，不能用覆盖问题掩盖内容基线更强。

**哪些是自己的工作？** 时序与样本契约、原子token-ID适配、受控预算/复现门槛、共同过滤与评价、曝光/集中度/前缀诊断、实验取舍与可追溯封存。量化、Trainer、beam和树组件明确来自上游，不包装为自研框架。

**还能展示哪些可靠性证据？** 阶段47数值口径中断与阶段49校验器变量名错误都有失败记录、独立修正及收据；不能说项目从未失败。当前阶段没有新训练/模型前向/解码，没有把旧失败覆盖为成功。

## 展示与分享范围

可在本机讲解源码、聚合表和复核入口；逐用户画像、交互衍生、SID轨迹和训练模型仍受原CC BY-NC-ND4.0及源条款限制，不直接随简历/公共仓库发布。不能写线上CTR、生产QPS、真人相关性提升、真实第二台机器复现、RL收益或优于Google Scholar。

当前收尾状态：{status}；保留现有内容推荐默认，项目其他功能按原交付运行。本次没有重新验收或发布旧网站，也没有修改默认Agent流程。
''',encoding='utf-8')
    save(ROOT/'closure-evidence.json',{'status':'complete','report':str(output),'resume_supplement':str(supplement),
        'branch_status':decision['training_branch'],'new_training_or_generation':False,'personalization_claim':False})
    print({'report':str(output),'resume_supplement':str(supplement),'closure':closed},flush=True)


if __name__=='__main__':main()
