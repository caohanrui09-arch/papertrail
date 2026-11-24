# 检索词改写 + 单任务对比 + guarded 进 UI（阶段97）

日期：2026-11-25。

## 1. 检索词改写循环

在 `query_mode=model` 下，第一次检索之后**再次出现检索动作**：模型可以换一个词重查（检索预算仍是 2 次）。

```
步 0：合法 {search_papers}                 → 模型写入 query "量子香蕉与冷冻电镜的交叉研究"
步 1：合法 {search_papers, final_answer}   → 模型选择提交空结果
步 2：终态
```

- 新增 5 项单测：model 模式允许二次检索、confirmed 模式不允许、两次后关闭、两种拒绝原因正确。
- 原有 26 项状态机相关测试全部通过（confirmed 行为未变）。
- 形态证据：`constraint_snapshots[1].legal_tools = ['search_papers','final_answer']`——**改写这条路是开着的**。
- 如实说：这次模型**没有用**改写，而是直接提交了空结果（对"量子香蕉"这种查询，提交空结果也合理）。改写能力存在，但本轮没有观察到模型使用它。

## 2. 单任务对比（约 2 分钟，之前 10 分钟）

`/lab/run` 的 compare 从"全部预设 × 3 策略"改成"当前任务 × 3 策略"：

| 任务 | 策略 | 完成 | 执行 | 被拒 | 调用 | Token | 耗时 |
|---|---|---|---|---|---|---|---|
| evaluation-001 | fixed | ✅ | 3 | 0 | 0 | 0 | 0.3s |
| evaluation-001 | **guarded** | **❌** | 1 | 0 | 8 | 14,297 | 111.6s |
| evaluation-001 | constrained | ✅ | 3 | 0 | 3 | 4,319 | 55.2s |

同一个任务：脚本 0.3 秒；自由生成 8 次调用仍失败；约束后 3 次调用完成。

## 3. guarded 进 UI

- 策略下拉框新增"状态约束 · 无解码约束（可看拒绝）"；
- 服务端 `policy` 允许 `guarded`；
- 修复：guarded 运行的结果原先被写死标成 `constrained`，现在标 `guarded`（对比表不再出现两行同名）。

## 4. 修掉的一个标签 bug

`research71.runner.observed_constrained` 把 `policy` 硬编码为 `constrained`，导致对比表里 guarded 行冒充 constrained。已在 research88.runner 里覆盖为 `guarded`。

## 边界

- 改写能力有测试与快照证据，但**没有观察到模型实际使用**；要演示"改写→更好结果"，需要构造第一次空、第二次有结果的查询对，并多跑几次。
- 单任务对比每次仍要拉起模型（guarded + constrained 各一次），约 2 分钟。
- guarded 行这次 0 次"被拒"，是 8 次调用后步数耗尽，不是状态机拒绝。

## 复跑

```powershell
# 单任务对比
POST /lab/run {"task_id":"evaluation-001","policy":"constrained","compare":true}
# 改写：自定义任务 agent_query=true，executed_query 留空
```
