# 阶段48：受控训练预算对照

工作目录：`<repo>`。报告为 `reports/阶段48_受控训练预算对照.md`，质量、分组、loss和资源CSV在 `reports/stage48`。

## 验收现有结果

```powershell
Set-Location '<repo>'
& '.\.cache\stage17\runtime\Scripts\python.exe' -E -s -m scripts.verify_sid_budget
```

该命令只验收哈希及记录，不重训或推理。保留原阶段45/46/47；每个新模型位于 `runs/stage48/{content,shuffled}-{42,2024,3407}`。逐用户材料与模型仅本地使用，不提供公共下载。

## 实际设计

同一基础T5-small、tokenizer、SID、seed271828冻结样本排列；两臂三个种子与旧128一致。使用原 `scripts.run_sid_sft.arguments`、`OrderedExamples`、`fresh_model`，HF原生Seq2SeqTrainer负责训练。batch8，constant lr0.0005，BF16，512步读前4096条；128步读同一前1024条。预算与曝光共同增加，不能单独识别更多更新的因果作用。单个样本的5个标签为原始token IDs，避免重分词。

每跑在128原生保存检查点后，要求权重逐张量和旧final bitwise相同，并要求8条loss/grad_norm/lr完全一致；不比较epoch或耗时。首跑128验收及资源门槛通过才写实际run-lock，且在任何第129更新之前。若失败，回调直接抛错，保留输出，不能跳过门槛。

原生检查点128和512均保留模型、tokenizer、优化器、scheduler、RNG和Trainer state。没有从旧缺优化器模型精确续训；本轮连续跑512，保留恢复所需材料不等于已独立验证中断恢复重现。原生检查点包括本地pickle状态，复用时只接受本次收据锁定的可信本地文件，不能加载陌生上传检查点。

128权重重现后复用原完整tuning预测和计分；只对新512模型做六轮完整beam10预测。2128有历史用户神经解码，1443空画像共享原流行度兜底，按固定画像复用至46352事件。目录外正反馈仍计miss。1801目录内且有上下文事件仅诊断，不能事后替代主指标；旧dev不运行。

质量表保留两臂、全部三个种子、全部128/512结果以及旧实用基线，不选最好种子或检查点。计分直接调用已验证的 `accelerated_evaluate`，全部事件进入原 `score_rows`；每跑另用固定512事件与原慢 `evaluate`逐字段比较。覆盖按独立有历史用户统计。所有耗时仅本机离线批处理，不能写作生产QPS或在线p95。

## 新的本地研究副本复跑

仅在阶段47输入/环境均存在，但尚无阶段48输出的新副本执行。当前封存目录不要清空、覆盖或直接重跑训练。

```powershell
$cpuBudget = '.\.cache\stage17\runtime\Scripts\python.exe'
$gpuBudget = '..\.venv\Scripts\python.exe'
& $cpuBudget -E -s -m scripts.prepare_sid_budget
& $cpuBudget -E -s -m unittest discover -s tests -p test_sid_budget.py -v 2>&1 | Out-File -Encoding utf8 reports/stage48/tests.log
& $gpuBudget -E -s -u -m scripts.run_sid_budget train
& $gpuBudget -E -s -u -m scripts.run_sid_budget predict
& $cpuBudget -E -s -u -m scripts.score_sid_budget
& $cpuBudget -E -s -m scripts.validate_sid_budget
& $cpuBudget -E -s -m scripts.report_sid_budget
& $cpuBudget -E -s -m scripts.probe_sid_budget_environment
& $cpuBudget -E -s -m scripts.verify_sid_budget
```

逐条检查退出码，失败立即停止。训练日志应保存到新的本地文件；不要为重试覆盖失败输出。已有代码对训练/预测/分数/结果文件存在时拒绝覆盖，未实现自动续跑。原始运行stdout/stderr和退出状态另外保留；首128门槛的训练已计入总512，不是额外128预算。

环境不变：CPU57包、CUDA38包、网站26包；HF4.57.1、torch2.6.0+cu124。无需添加pandas至CUDA环境，无需安装matplotlib。CPU数据/评价与GPU训练分开。至少20GiB可用磁盘，原生检查点会保留优化器矩状态；GPU reserved<6.5GiB、进程峰值<12GiB、每跑训练<900s，预测每跑<900s。前者由训练回调按16步核查，128/512再查；不是硬操作系统隔离限额。

## 证据范围

设计及训练/计分/独立核验代码先固定于protocol.json；首128测得资源和重现门槛另存run-lock.json。原训练过程不读取tuning/dev标签；CPU计分在训练和预测完成后读取tuning。报告生成与最终封存器作为后续交付文件锁定。基线与未来反馈只用于评价，不用于选择新目录或训练样本。

交互来自Scholar Inbox，沿用既有CC BY-NC-ND4.0审核限制；衍生画像、样本、预测和模型不随网站分发。组件使用方式与许可证见 `reports/stage48/THIRD_PARTY_NOTICES.md`。该复跑是当前电脑已有环境的本地研究复跑，不冒充第二台机器或新独立测试。
