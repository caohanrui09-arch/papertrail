# 实际复用与适配边界

2026-11-11：复读比较成熟框架的原生工具循环和推荐评分实现，复用本项目已固定组件，不重新实现算法/Agent循环。

- [smolagents v1.22.0](https://github.com/huggingface/smolagents/blob/v1.22.0/src/smolagents/agents.py)：Apache-2.0；复读blob `0b1adaffd6e61aafa04c7515a3dedc793934de76` 的原生模型生成与工具处理。实际调用已安装1.22.0的ToolCallingAgent、原项目模型预算和状态/schema隔离。
- [Recommenders SAR](https://github.com/recommenders-team/recommenders/blob/main/recommenders/models/sar/sar_singlenode.py)：MIT；复读blob `968cfeb19cc9d9050bd6bdfb82ecb59263c758f2` 的相似度选择及评分。实际调用原项目固定SAR组件，未复制或升级最新分支源码。
- 原项目 `gsearch.unified_session`、`unified_agent`、`constrained_agent_isolated`、`cold_fusion`、`unified_search`、`scripts.score_unified` 原样保留。新增层只组织服务/任务、提供算法解释和依赖注入，不修改旧模型/数据/冻结结果。
- 算法由原生SQLite FTS5 BM25、sklearn TF-IDF/余弦、SAR及原项目门控实现计算；最近历史论文依据真实文档余弦，不由LLM编造。

此轮没有安装新依赖。模型为已在本机的Qwen2.5-1.5B-Instruct，不下载新权重、不训练、不调用收费API。模型/交互数据沿用原许可和私有数据边界，不将原始轨迹放到公共报告。
