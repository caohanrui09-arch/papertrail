# 阶段50：冻结512模型的小规模探针

工作目录：`<repo>`。
报告：`reports/阶段50_冻结512模型历史与频率先验.md`。

## 验收现有结果

```powershell
Set-Location '<repo>'
& '.\.cache\stage17\runtime\Scripts\python.exe' -E -s -m scripts.verify_sid_prior_probe
```

仅做文件哈希和证据验收，不重新推理或训练。会验证阶段49及其45–48旧封存链。新收据为 `reports/stage50/final-validation.json`。

## 本轮实际范围

两组SID×三种子，读取 `runs/stage48/{run}/checkpoint-512`，全参数冻结、eval、无梯度。384个beam10请求（32画像×原始/同长历史交换×六模型）和192个teacher-forcing样本（32严格前缀×六模型）。不执行完整tuning/dev解码，不启动训练、优化器或RL。

直接复用阶段47 `observed_decode`、`token_diagnostics`、`paired_rank_metrics`、`parameter_fingerprint` 和阶段45 `CatalogConstraint`。身份观察器返回原分数对象，HF原生generate/beam_indices/transition_scores负责生成与祖先追溯；没有自写beam。张量/精度测试沿用原12项，新加8项CPU先验边界，共20项不同测试。

样本原文件逐字节复制，接收者seen、目录、同长历史排列、输入/标签token IDs、BF16、batch16不变。两种历史均可能反事实；该探针不是相关性评价，也不能证明理解个人兴趣。32画像与32前缀分别为不同诊断样本，六模型复用它们，不作独立样本显著性推断。

32前缀仍为16个原1024抽到事件和16个4096仍未抽事件，目标论文则18个旧标签、4个新增标签、10个4096仍未标签。严格过去历史不含目标，不能以最终截止画像回填。原分组和新增曝光元数据在本地 `prefix-exposure.json`，没有重新挑例。

## 公共先验与损失口径

训练排列前1024/4096标签的每位置计数，位置码本64/64/64/11/1，Laplace α=1。同一SID映射内，两个模型预算都对比**同一个4096先验**，两种映射各自统计token频率。旧128模型损失从阶段47原样读取，仅离线追加两个先验NLL；没有为旧模型额外生成或前向。

原生helper输入字典的旧键`pilot_counts`仅在薄适配层使用；正式保存字段为`label1024_position_prior_nll`/`label4096_position_prior_nll`，不会把4096伪称1024 pilot。标签先验只用训练源数据，既不看用户历史，也不看先前真实目标SID token；teacher forcing模型看到后者，所以它是弱参照。位置码本条件损失不是目录树条件损失，先验NLL也不是目录级排名质量。

FP32分析使用BF16前向logits显式转float后原生CE；AMP模型loss另外保存，并与同AMP未约简CE均值比，绝对误差1e-4。新模型全部检查成功，没有复现阶段47的跨精度混比错误。EOS码本K=1时条件NLL=0是定义必然。完整logits未落盘，独立验收可核对路径/先验/分解/均值，但不冒充从全logits重算概率。

## 交付文件

- `history-comparison.csv`：128/512按全体、历史长度1/20分组的Jaccard、首位/有序列表变化、footrule及新增捐赠者历史项。
- `position-comparison.csv`：两个预算、五位置、全部/原pilot事件/原未抽事件/历史长度/目标标签曝光分组的损失、概率质量和频率参照。
- `history-paired-changes.csv`：同画像512−128的敏感性变化，不含公开用户ID。
- `summary.json`、`decision.json`：结果与保持暂缓训练的决定。
- ignored的 `data/stage50-health`：原始画像/前缀、双先验、128重评分、新512原生路径/祖先/位置损失及六份权重收据，仅本地。

## 在新的本地研究副本复跑

仅在阶段49完整封存输入存在，但没有stage50输出的新副本执行；不要删除或覆盖当前交付。

```powershell
$cpuPrior = '.\.cache\stage17\runtime\Scripts\python.exe'
$gpuPrior = '..\.venv\Scripts\python.exe'
& $cpuPrior -E -s -m unittest discover -s tests -p test_sid_prior_probe.py -v
& $cpuPrior -E -s -m scripts.prepare_sid_prior_probe
& $cpuPrior -E -s -m unittest discover -s tests -p test_sid_prior_probe.py -v 2>&1 | Out-File -Encoding utf8 reports/stage50/prior-tests.log
& $gpuPrior -E -s -u -m scripts.run_sid_prior_probe
& $cpuPrior -E -s -m scripts.validate_sid_prior_probe
& $cpuPrior -E -s -m scripts.report_sid_prior_probe
& $cpuPrior -E -s -m scripts.verify_sid_prior_probe
```

逐条核对退出码，失败立即停下并保留原输出；脚本拒绝覆盖已有协议/运行。首个CPU测试在协议前检查接口，ROOT建立后重复只是保存日志，不算16项不同CPU测试。GPU两项精度测试只用合成logits，不额外调用模型。使用既有CPU57/CUDA38包环境，无新依赖；不是另一台机器复现证明。

GPU reserved上限2.5GiB、进程上限6GiB、probe窗口上限1200秒；按每模型结束检查，非操作系统硬隔离。完整A+B参数指纹不变，磁盘checkpoint哈希相同，全部grad=None。时间不含初始化/测试/协议哈希，进程峰值是生命周期高水位，不能当生产性能。

旧模型、训练、tuning评价、网站与访客空间保持不变；源交互的CC BY-NC-ND4.0及既有元数据许可范围不变，不公开分发衍生样本/预测/模型。说明见本阶段THIRD_PARTY_NOTICES.md。
