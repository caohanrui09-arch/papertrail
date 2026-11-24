# 语法约束解码（阶段88）

日期：2026-11-24。目标：修掉"模型写不出 `{"name","arguments"}` 外层"这个解码层失败（阶段87 已证明改载荷/提示无效）。

## 做法

用 **lm-format-enforcer 0.11.3（MIT）** 在 HF `generate` 上做前缀约束：

| 组件 | 作用 |
|---|---|
| `ConstrainedActionState` | 每次 `refresh()` 把"当前合法工具集"编译成 JSON schema 发布出去 |
| `ConstrainedToolModel` | 在 `_prepare_completion_args` 注入 `prefix_allowed_tokens_fn`，按 schema 掩码 logits |
| schema 形状 | 单工具时用精确参数 schema；多工具时用 `anyOf`；无合法动作时不约束 |
| 依赖 | 全部本地化在 `.cache/decoder-deps`（lm-format-enforcer、interegular、pydantic、pydantic-core），不改系统环境 |

状态机、工具集、预算、prompt、校验逻辑**都没有改**；模型仍然要自己发出调用，只是非法 token 被屏蔽。

## 结果（同一批 4 任务 × 2 次）

| 版本 | 完成 | 解析失败 | 空结果 |
|---|---|---|---|
| 阶段82 基线（无约束） | 6/8 | 4 | 0/2 |
| **v1 只约束信封** | 6/8 | **0** | 0/2 |
| **v2 信封 + 空对象载荷** | **8/8** | **0** | **2/2** |

v1 的失败方式变了但没修好：模型现在能写出合法信封 `{"name":"final_answer","arguments":{"answer":{"citations":[…1 条…]}}}`，但 **lm-format-enforcer 不强制 `maxItems: 0`**，所以它仍然塞了一条编造引用，然后连续重试 6 次直到步数耗尽。

v2 把零结果时的 answer 改成空对象 `{}`，由约束强制成 `{"name":"final_answer","arguments":{"answer":{}}}`，客户端再归一化成 `{"citations":[]}`。两次空结果运行都只用 2 次调用、约 3–6 秒完成。

## 必须说清的边界

1. **空结果的通过是"结构性"的**：那一步只有 `final_answer` 一个合法动作，schema 又把参数定死成 `{}`，所以约束解码必然产出它。这**不代表模型理解了"没有结果"**，只代表"唯一合法动作被强制"。
2. **格式修复是真的**：全批 8 次运行解析失败 0（基线 4），且非空 6 个单元全部保持通过、无回归。
3. **成本**：约束解码逐 token 走 FSM，明显变慢。同批总耗时约 173 秒（基线约 93 秒），单次最高 99 秒。这是可预期的代价，不是异常。
4. 协议已变（载荷形状 + 解码策略），**不能把 8/8 与阶段82 的 6/8 当成同一协议下的提升**；能说的是"在新协议下 8 次运行全部完成"。

## 改动文件

| 文件 | 改动 |
|---|---|
| `gsearch/state_constraints.py` | 零结果时 `final_answer.answer` schema 变空对象 |
| `gsearch/constrained_agent.py` | `GuardedClient.finalize` 把 `{}` 归一化为 `{"citations":[]}` |
| `research88/constrained.py` | schema 构建、约束模型、schema 发布 |
| `research88/runner.py` | 与 research71 相同的循环，只换状态类与模型类 |
| `tests/test_constrained_schema.py` | schema 与合法集一致性（4 项） |
| `tests/test_empty_final.py` | 空对象归一化与拒绝编造（5 项） |

## 复跑

```powershell
.cache\stage6-env\Scripts\python.exe -E -s -u -m research88.runner `
  --input data\stage88-batch\spec.json --output data\stage88-batch\result.json `
  --events data\stage88-batch\events.jsonl
.cache\stage17\runtime\Scripts\python.exe -E -s -m research88.score_batch
```

## 下一步

- 想验证"模型是否真的懂空结果"，需要**去掉单一合法动作的强制**：例如同时提供"提交空结果"和"继续检索"两个动作，看模型选哪个。那才是语义测试，本轮没做。
- 约束解码可以推广到 `read_paper` 的 `doc_id` 枚举（当前是自由字符串），进一步减少无效读取；代价是 FSM 更大、更慢。
