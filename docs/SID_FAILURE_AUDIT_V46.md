# SID失败归因审计：阅读与复跑

本轮只读取既有监督、映射、预测和最终token轨迹。没有训练、模型加载、生成、数据获取或目录变更。哈希校验会读取已保存的权重字节，但不实例化模型。最终收据为 `reports/stage46/final-validation.json`。

## 建议阅读顺序

1. `reports/阶段46_SID失败归因审计.md`：完整“观察/候选原因—数量—案例—下一步验证”表，及条件指标、分母、曝光和前缀解释。
2. `reports/stage46/failure-audit.csv`：可筛选的12行审计表，每行有口径、证据、下一步验证和不可作出的强结论。
3. `data/stage46-audit/cases.md` / `cases.json`：36个按预先规则选择的本地详细案例，含真实历史、目标、基线排名、原摘要/v1链接及完整SID路径；这些是逐用户衍生，保持本地非商业，不放入公开网站/分享包。
4. `reports/stage46/conditional-metrics.csv`、`terminal-prefix-counts.csv`、`output-concentration.json`：全部九组、六个SID运行与补充诊断的精确结果。
5. `reports/stage46/next-step-decision.json`：下一步建议的冻结模型健康检查；状态是建议、尚未执行。

主要口径：完整46352事件分为目录外39907、目录内无上下文4644、目录内有上下文1801（528用户）。后者是事后条件诊断，不替代原主指标。用户内事件先平均，再用户间平均；不把重复事件当独立用户。

“源训练无点赞”“代理规则下无合规反馈”“没有next-item目标监督”“监督池中有目标但没进pilot”是不同状态。用户未进入pilot也不等于用户冷启动，模型输入没有用户ID。目标映射不变的碰撞组也不是纯负控制，因为历史映射可能变化。

前缀诊断只观察最终Top10：第四层是身份后缀；没有保存中间beam/logits/祖先，所以不能还原首次剪枝时刻。输出集中同样不证明模型忽略历史，差异也可能来自seen mask。下一步需要控制接收者过滤条件，只交换历史作小规模敏感性探针，再决定训练预算。

## 验收已有交付

```powershell
Set-Location '<repo>'
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.verify_sid_failure_audit
```

再次运行只核验本轮文件和此前303项资产，不覆盖统计、案例、数据或旧实验。原阶段45收据仍为 `reports/stage45/final-validation-v2.json`，SHA256 `2e7bf16a10f196f42cde8ce2bd75055f3e611951b3ecbbcef73d91d879bf0949`。

## 从没有阶段46输出的独立本地研究副本复跑

保持阶段44/45文件、原CPU环境和数据来源不变；所有脚本均拒绝覆盖已完成输出：

```powershell
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.validate_sft_delivery_v2
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.prepare_sid_failure_audit
& .cache/stage17/runtime/Scripts/python.exe -E -s -m unittest discover -s tests -p test_sid_failure_audit.py -v
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.audit_sid_failures
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.probe_sid_audit_outputs
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.validate_sid_failure_audit
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.report_sid_failure_audit
```

第一次封存还需保存真实的12项成功测试日志为 `reports/stage46/tests.log`，不能手工补写“通过”。本机交付已包含真实执行日志及独立验证结果；这些命令没有使用GPU运行环境。本轮不声称第二台机器复现。

目录外数据只作来源诊断；既有万篇元数据以外的论文没有本轮可核验标题/摘要/版本，不能据此估算可扩容论文数或选择未来命中候选。未来点赞只能用于诊断/评价，不能反向挑训练样本或入库论文。
