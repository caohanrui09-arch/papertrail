# 状态约束 Agent：isolated-v2 研究入口

本地统一服务先运行 `unified-service.cmd start`，默认应用入口仍是 `unified-demo.cmd` 的固定流程。
在项目目录运行 `state-agent-isolated-demo.cmd`，可显式试用同一 Qwen2.5-1.5B 与原生 smolagents1.22.0 的状态约束版本。
可加 `--intent search --query "paper title"` 或 `--intent mixed --query "paper title"`。默认无训练历史用户推荐。
完整生成/失败/HTTP/状态轨迹存入忽略的 `data/stage21-isolated/demo-*/result.json`，成功 exit0，未完成 exit1，没有静默切换。

此入口保留研究用途，不自动改服务默认行为。真实服务共同使用原有万篇 v1、冻结历史、时间代理及内容推荐。
模型必须自己选择论文、读取并提交引用；控制器只根据显式意图和已发生的调用限制合法动作，不读取 gold 目标 ID。

## 原生复用及边界

实际复用 ToolCallingAgent、工具注册/参数校验、逐步回调与原预算模型；动态 schema 只是模型提示，未使用 token 级约束解码。
原生类型校验拒绝 k=null/bool；k 为必填整数1..3，项目状态检查另管范围、可读成员、引用数量/来源/quote_index。
重复检索与已读论文退出合法工具/ID集合；组合需求允许两种检索顺序，模型仍须自己生成 final_answer。
拒绝和重试全部留痕；本地拦截的已解析提案也扣等价应用额度，解析失败消耗 LLM 次数/token。
每请求最多6应用尝试、2检索、2读取、7框架步、8生成（含原生超步兜底）、30000输入/1280输出 token、每次160输出。
无参数补全、自动读取、代替模型选文或自动最终提交。

## 首批作废与修复

原 `FinalAnswerTool.inputs` 是共享类字典。首批适配器原地改变它，污染同进程后续原 LLM 组，因此
`reports/stage21/INVALIDATED_SCHEMA_CONTAMINATION.json` 声明首批全部比较作废，旧轨迹/冻结源码保留。
不要将 `state-agent-demo.cmd` 旧入口及首批数字作为有效结果。当前入口改用 isolated-v2，在每次更新前深拷贝各工具实例 schema；
所有48个对照请求都在前后断言原生默认 schema 不变，另有跨会话/跨策略回归。没有修改框架源码或共享环境。
v2沿用原任务、模型、提示词、预算、门槛，输出写独立路径；worker日志重定向私有文件，避免终端日志缓冲影响。

## 结果与复核

冻结计划和有效结果在 `reports/stage21-isolated/`，完整报告 `reports/阶段21_状态约束Agent可靠性与成本.md`。
4 tuning 后冻结，再跑原阶段19已用的12个任务；它们是显式意图的受控描述性任务，没有独立真人相关性标签。
引用验证只证明原v1摘录可追溯，不证明论文相关性或科学论断正确。工程规则带来的收益不能称为模型推理能力提升。
预算/来源逐步重放使用 `python -m scripts.replay_isolated_constraints`，已有结果拒绝覆盖；交付收据固定所有复核资产哈希。
单机单次端到端墙钟不是隔离GPU基准；不根据结果修改阈值。未过预设门槛则保留固定流程并结束本轮Agent优化。
