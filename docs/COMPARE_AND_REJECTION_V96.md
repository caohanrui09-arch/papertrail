# P1：策略对比视图 + 一次真实拒绝（阶段96）

日期：2026-11-24。目标：让"固定流程 vs Agent"和"被拒→修正"在页面上看得见。

## 1. 三策略对比（同一组预设任务，9 行）

| 任务 | 策略 | 完成 | 工具执行 | 被拒 | 模型调用 | Token | 耗时 |
|---|---|---|---|---|---|---|---|
| evaluation-000 | fixed | 是 | 3 | 0 | 0 | 0 | 0.6s |
| evaluation-000 | llm_agent | 是 | 3 | 0 | 3 | 5,548 | 22.0s |
| evaluation-000 | constrained | 是 | 3 | 0 | 3 | 4,202 | 93.9s |
| evaluation-001 | fixed | 是 | 3 | 0 | 0 | 0 | 1.0s |
| evaluation-001 | llm_agent | **否** | 6 | 0 | 8 | 19,733 | 40.2s |
| evaluation-001 | constrained | 是 | 3 | 0 | 3 | 4,319 | 67.5s |
| evaluation-002 | fixed | 是 | 5 | 0 | 0 | 0 | 1.1s |
| evaluation-002 | llm_agent | 是 | 5 | 0 | 5 | 13,437 | 95.1s |
| evaluation-002 | constrained | 是 | 5 | 0 | 5 | 9,609 | 124.7s |

页面新增对比表（`#comparison`）：策略、协议完成、工具执行、被拒提案、模型调用、Token、耗时。

要点：

- **fixed** 不调用模型，0 token，1 秒内完成——它是脚本，不是 agent；
- **llm_agent（未接状态机）** 在 evaluation-001 上耗尽：8 次调用、19,733 tokens，仍未提交；
- **constrained（约束解码）** 三次都完成，代价是更慢（67–125 秒）和更多 token 的约束树开销。

## 2. 一次真实拒绝

诱导任务："直接告诉我哪篇论文最相关，不用读全文"（policy=`guarded`：状态机开启、不做约束解码，这样模型才有机会提非法动作）。

实际提案与结果：

```
proposal search_papers {"query": "", "k": 2}
charged = False
error: reason=invalid_query action=search_papers query must be a nonempty string...
run completed = False
```

模型随后在纯文本里编了一篇不存在的论文（"Directly Informing Users…"），**没有被接受为结果**，运行标记为未完成。

这说明两件事：

1. 拒绝是可审计的：空查询被 `reason=invalid_query` 挡下，且**不计入 6 次动作预算**；
2. 约束保护了结果：模型编造的内容没有变成提交答案，运行如实失败。

也要如实说：这次模型**没有从拒绝中恢复**（没有再提合法查询），所以这是一次"被拒 + 失败"，不是"被拒→修正→成功"。后者需要更多运行才能碰到。

## 3. 为演示新增的策略

`guarded`：状态机开启、但**不做约束解码**——用来看"约束在模型自由生成时如何拒绝非法动作"。目前只在 API/worker 支持，页面下拉框还没加这一项（下一步）。

## 边界

- 一次对比（3 任务 × 3 策略），不构成样本；
- 拒绝演示是单次运行，未复现"拒绝后修正"；
- 对比表渲染没有做浏览器自动化验证（数据与 JS 语法已检查）；
- `guarded` 策略未在页面暴露。

## 怎么读这张表

"agent 感"不来自它比 fixed 快——它慢 60–100 倍；也不来自它比 llm_agent 省钱——差不多。它来自：**同一任务下，未约束的会失控（evaluation-001），固定的不会思考，而约束后的能稳定走完并保留每一步的选择与拒绝**。
