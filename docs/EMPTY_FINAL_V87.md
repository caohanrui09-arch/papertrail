# P0 实测：空结果修复（阶段87，负结果）

日期：2026-11-24。协议 `stage87-empty-final-object-v1`（冻结于改动前）。

## 假设

`e73-empty` 一直失败，是因为模型必须自己构造 `{"citations":[]}`。把空结果的 final answer 载荷简化成一个空对象 `{}`，应该能让 1.5B 做出来。

## 做法

| 改动 | 内容 |
|---|---|
| 状态机 | 检索返回 0 篇时，`final_answer.answer` 的 schema 变成"无属性对象"（`{}`） |
| 客户端 | `GuardedClient.finalize` 把 `{}` 归一化成 `{"citations":[]}`，再走原有校验 |
| prompt | 两份 prompt 各加一句：零结果是正常情况，提交 `{}`，永不编造 ID |

## 结果：失败，且带回退

| 单元 | 阶段82 基线 | 阶段87 |
|---|---|---|
| e73-search | 2/2 | 2/2 |
| e73-recommend | 2/2 | **0/2（回归）** |
| e73-mixed | 2/2 | 2/2 |
| e73-empty | 0/2 | **0/2（未修复）** |
| 合计 | 6/8 | **4/8** |

## 关键证据：不是载荷问题

日志里模型输出的是：

```
{"citations": [...]}        ← 没有 name / arguments 外层
{"answer": {...}}           ← 同上
```

解析器报 `Tool call needs to have a key 'name'`。也就是说，模型**根本没走到"提交什么载荷"这一步**——它连工具调用的外层 JSON 都没写出来。schema 和文案改得再简单，也影响不到这一层。

`e73-recommend` 的回归同样是这个模式：它检索到论文后，直接吐 `{"answer": ...}`，没有包成 `{"name":"final_answer","arguments":{...}}`。

## 停止规则触发

协议预声明：**若空结果仍是 0/2，就说明不是载荷格式问题，停止 schema 微调，转提示/解码或更大模型。**

实际：0/2，且模型在别的单元也开始破外层。规则触发。

## 已回滚

7 个文件的 SHA256 与协议记录的改动前哈希**逐项一致**：

```
gsearch/state_constraints.py  True
gsearch/constrained_agent.py  True
gsearch/unified_agent.py      True
research71/prompts/custom.txt True
gsearch/prompts/unified.txt   True
tests/test_state_constraints.py True
```

回归测试 36 项通过，8802 服务正常。阶段87 的 5 个临时测试已删除（它们断言的是被回滚的行为）。

## 这轮真正学到什么

1. **1.5B 的失败在解码层，不在协议层。** 它会漏掉 `{"name": ..., "arguments": ...}` 外层，尤其是在"检索为空"这种上下文里。
2. **改 prompt 是双刃剑**：一句关于空结果的提示，让推荐单元从 2/2 掉到 0/2（与阶段82 加两个 JSON 字段的回归同一性质）。
3. **要修这个单元，需要解码级约束**：语法约束解码（如 vLLM + outlines / xgrammar 的 JSON schema 引导），或换更大的模型。继续改 schema/prompt 的期望收益已接近零。

## 下一步建议

| 方向 | 说明 | 成本 |
|---|---|---|
| 语法约束解码 | 用 vLLM guided decoding 强制 `{"name": <enum>, "arguments": <schema>}` 结构 | 需要换服务栈（HF generate → vLLM），1–2 天 |
| 更大模型 | 3B 上探（带宽 2 小时） | 已评估，未完成 |
| 换任务形态 | 把"空结果"改成显式的"无结果确认"交互，而不是让模型生成 | 0.5 天，但改的是产品而非模型能力 |

## 保留的失败材料

- `reports/stage87/protocol.json`（冻结协议与改动前哈希）
- `reports/stage87/batch-summary.json`（8 次运行逐条结果）
- `data/stage87-batch/`（原始 result 与事件流，含全部解析失败）
- 本文件
