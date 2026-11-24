# 演示与分层复现说明

## 当前已验证的环境

所有命令在项目根目录 `generative-search-agent` 执行。当前解释器为 `.cache/stage6-env/Scripts/python.exe`，通过原有隔离设置只读使用父目录CUDA环境；不要把本机绝对路径当成通用安装方案。

Python3.12.3；Torch2.6.0+cu124、Transformers4.57.1、smolagents1.22.0；NumPy2.5.4、SciPy1.18.1、pandas3.1.0；隔离sklearn1.9.1、threadpoolctl3.7.0。实际包版本和资产状态可用下方预检命令确认。无新依赖或系统配置修改。

## 1. 一键演示：不训练、不下载

```powershell
.\demo.cmd
```

等价Python入口：

```powershell
.cache/stage6-env/Scripts/python.exe -m gsearch.showcase
```

模型只装载/拟合一次，原生工具依次展示content、原alpha0.5 RRF、tuning冻结alpha0.25 cold_aware；每路返回Top3，并重新解析第一篇的官方v1原始响应。演示用户只由训练画像用户集合的固定hash选择，不按未来点赞或展示效果挑人。默认时间为日志窗口末的2025-02-23T13:28:26.401006+08:00。

输出保存在新建且不覆盖的 `data/showcase/run-*/`：`DEMO.md`用于本地阅读，`demo.json`含完整工具轨迹与来源。它们含用户派生结果，只留本地；单次演示既不替代正式评测，也不是延迟基准。原摘要中的Markdown控制符作为字面原文展示。

可选参数只通过Python入口传入：

```powershell
.cache/stage6-env/Scripts/python.exe -m gsearch.showcase --user USER_ID --k 3 --output-dir data/showcase/my-new-run
```

输出目录必须是忽略的data/下新子目录。未知用户按原规则回退流行度；不能把它的结果称为个性化推荐。历史/目录发生更新后，需要重建模型与seen索引。

## 2. 快速预检：检查当前运行条件

```powershell
.cache/stage6-env/Scripts/python.exe -m gsearch.showcase --check-only
.cache/stage6-env/Scripts/python.exe -m scripts.verify_delivery
```

检查必需本地资产、阶段15代码/聚合结果/报告hash、冻结选型引用、语料hash和现有包版本。缺资产会明确失败，不自动下载、不生成替代数据。预检不是完整原始预测重计分。

## 3. 完整只读复核：核验现有冻结结果

```powershell
.cache/stage6-env/Scripts/python.exe -m scripts.verify_delivery --full
.cache/stage6-env/Scripts/python.exe -m unittest discover -s tests -q
```

完整复核读取阶段3—15冻结资产、重新解析全部10,000篇官方v1，独立重算阶段15的12份预测及冷热分组/成本，并采样复演原生排名。会重新装载原模型用于复核，但不会训练、调参或覆盖旧结果。这是**对现有资产的复核**，不同于从空目录重新获取数据并完整重跑研究。

## 4. 从零重跑实验：当前边界

**本机链路已验证；新机器全量安装和从零获取全部历史资产尚未验证。** 仅复制Git源码不足以运行演示：data/、.cache/、模型权重和来源响应均被忽略。以下是依赖关系，不是已经在新机器验收通过的一键安装承诺。

| 资产 | 用途与来源 |
|---|---|
| Scholar Inbox固定评分源及stage9 train/tuning/dev | 原论文推荐日志，需自行接受原数据许可证后按已有下载/准备脚本获取；用户派生数据不随源码分发 |
| stage13明确v1文档与本地原始响应 | 演示与读取核验必需；必须保持ID、版本、领域、日期、hash及原限速/冷却规则，不能以最新摘要替换 |
| stage13资源收据与stage15冻结协议/选型/输出 | 复核评分器签名、同分母比较及参数选择顺序 |
| 原Recommenders/arxiv.py源码与许可证 | 已保留在third_party；按原固定commit复用 |
| stage6现有运行时与stage11隔离依赖 | 由已有setup_stage6_runtime.py、requirements-stage6文件及stage11/runtime-lock.json记录；本机继承路径不能原样移植 |
| SciFact与早期T5/Qwen权重 | 仅早期生成式检索/LLM Agent实验需要；当前推荐演示不加载这些权重 |

原阶段15从空的独立实验目录启动时，顺序为 `python -m gsearch.benchmark_cold_fusion --phase plan`、`tuning`、`lock`、`dev`，再封存报告。模块内ROOT/DATA目前固定，完成资产会拒绝覆盖。重跑应在单独项目副本/新阶段输出目录适配后执行；不要删除或原地重写当前冻结实验来模拟复现。本轮未创建第二套完整实验副本。

## 常见检查

| 现象 | 检查方向 |
|---|---|
| 缺少.cache/stage6-env解释器 | 当前本机运行时未就绪；不要随意替换共享Torch，先读运行时设置和版本锁 |
| 缺data/stage13或原始响应 | 源码之外的本地资产未准备；不要用生成摘要或最新版本冒充v1 |
| hash/选型漂移 | 检查被指出的文件；保留旧收据，恢复原资产或创建独立新实验 |
| 重复输出目录报错 | 选择新的data/子目录；默认入口会自动创建新目录 |
| 推荐质量指标很小 | 主指标保留范围外/未入库未来点赞；查看完整分母和eligible诊断，不能只换分母美化结果 |

原始反馈CC BY-NC-ND4.0的限制、元数据与PDF授权区别及全部第三方许可见 [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)。
