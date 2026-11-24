# 阶段49离线审计

工作目录：`<repo>`。
报告：`reports/阶段49_512步收益与集中度审计.md`；核心交付：`reports/stage49/audit-table.csv`。

## 现有结果验收

```powershell
Set-Location '<repo>'
& '.\.cache\stage17\runtime\Scripts\python.exe' -E -s -m scripts.verify_sid_budget_changes
```

只读哈希与证据校验，不重新训练、拟合、生成或计分。会核对旧阶段48及其45/46/47收据链，并核对本阶段协议和新文件。目录版本、模型、网站与访客偏好均保持原状。

## 输出与计算口径

- `audit-table.csv`：增益来源、退步、覆盖、典型案例、后续验证及解释限制。
- `gain-attribution.csv`：六对模型的完整/可用性/目标曝光分组、命中转移及完整用户分母加权贡献。
- `output-coverage.csv`：2128独立有历史用户的目录覆盖、首位份额、源频率与归一化标签频率。
- `terminal-prefix.csv`：每跑1801条件事件的终局缺失层统计，不能解读为实际中间beam剪枝。
- `source-frequency-slots.csv`：固定源训练赞数0、1–4、5–19、20+的槽位分布。
- `audit.json`：全部原生指标、曝光、频率、前缀、用户/论文收益集中度和损益共现。
- `data/stage49-audit/cases.md`：22个固定规则最小qid案例，真实原摘要/版本/链接及两组Top10。逐用户连接仅本地ignored。
- 同目录`*.changes.jsonl`及`*.terminal-prefix.jsonl`保存59变化记录和六组各1801配对终局记录，不能公开分发。

前1024/新增到4096/仍未抽按**目标论文曾否作为标签**划分，不按该未来事件是否在训练中划分。输入历史曝光单独保存，新增2014目标中1410早已出现在旧输入历史。完整训练期零点赞单独保留，不能把未抽到目标叫论文冷启动。

全部46352事件与3571用户保留，每条事件NDCG差乘`1/(3571×该用户完整事件数)`。分组贡献可加还原全指标，条件组宏平均不可加。最大用户/论文份额除以gross-positive贡献，避免用小净值制造夸大的占比。三个种子复用事件，不作独立样本统计推断。

输出频率以独立画像的Top10槽位统计；新增/移除候选均值只是共现。完整评价只有最终SID，没有中间beam祖先/分数，无法证明具体挤出对象或首次剪枝时刻。

## 当前核验修正

原审计源码、样本和protocol不改。原独立校验器的`group`循环变量覆盖了同名分组函数，第一跑后失败。`validation-failure.log`与原源码保留；v2仅将此循环变量及相关引用改名，不改条件、阈值、数据或公式。最终验收器自动对比v2与原文件的确定性改名结果。12个边界测试和全部独立核验均成功；失败日志不计成功测试。

另一次多余括号在封存协议前的语法检查被发现并修复，详情`preprotocol-syntax-error.json`，未执行错误版本审计。旧模型/结果均没有受影响。

## 新本地研究副本复跑

仅用于已有阶段48完整输入/收据、尚无stage49输出的独立本地副本。不要删除当前封存文件或直接覆盖重跑。

```powershell
$cpuAudit = '.\.cache\stage17\runtime\Scripts\python.exe'
& $cpuAudit -E -s -m unittest discover -s tests -p test_sid_budget_audit.py -v
& $cpuAudit -E -s -u -m scripts.audit_sid_budget_changes
& $cpuAudit -E -s -m unittest discover -s tests -p test_sid_budget_audit.py -v 2>&1 | Out-File -Encoding utf8 reports/stage49/tests.log
& $cpuAudit -E -s -u -m scripts.validate_sid_budget_changes_v2
& $cpuAudit -E -s -m scripts.report_sid_budget_changes
& $cpuAudit -E -s -m scripts.verify_sid_budget_changes
```

逐条检查退出码，失败立即停止并保留输出。首次测试在协议前做边界检查，ROOT由审计器建立后再存正式成功日志；不是24项不同测试。直接运行v2即可，无须故意制造旧变量名错误。该复跑是当前电脑已有CPU环境的本地复跑，不等于第二台机器实测。

CPU57包环境足够，未加载torch/transformers、未安装依赖。旧权重文件可能作为既有封存链的一部分读取字节校验哈希，这不等于加载模型或推理。

## 决定

事先固定的优先级启发式：至少2/3内容SID种子中新增标签组超过50%正向NDCG贡献，才优先考虑固定1024重复4轮对比4096单遍的512预算试验。实际0/3满足。此启发式不是统计检验，目标分组不能排除共享前缀/输入历史的间接曝光效应；训练对照仍可能有价值。

建议下一次另行冻结小规模512模型历史扰动与分位置损失/4096标签先验探针，复用阶段47的32画像和32严格前缀。该建议未执行，当前0新生成/训练/RL/dev评价，默认内容推荐保持。

逐用户材料、衍生监督和模型遵守Scholar Inbox原CC BY-NC-ND4.0限制，不随网站/公共仓库分发；元数据条款按已核验来源保留，详见本阶段THIRD_PARTY_NOTICES。
