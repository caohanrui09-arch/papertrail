# P0：让 Agent 自己决定检索词 + 决策卡（阶段95）

日期：2026-11-24。目标：让"这是 Agent"在页面上可见——有得选、选了什么、被拒过什么。

## 1. 检索词交给模型

自定义任务新增 `agent_query` 选项（计划里的 `query_mode`）：

- `confirmed`（默认）：沿用旧行为，模型必须原样使用用户确认的检索词，不一致直接拒；
- `model`：用户不再预先确认检索词，只给一个**提示**；模型根据原始需求自己写，状态机只校验非空、长度、控制字符。

计划接口 `POST /lab/custom/plan` 增加 `agent_query: bool`；页面"核对本次执行方案"里多一个勾选框"让 Agent 自己决定检索词（只给提示，不预先确认）"。勾选后检索词输入框变灰，并提示"已交给 Agent"。

## 2. 决策卡

时间线上方新增"决策记录"：每一步显示**当时可用的动作**（来自状态机快照 `legal_tools`）、**模型实际选择的动作**、以及被拒时的 `reason=` 代码。

数据本来就有（`constraint_snapshots` + `proposal_events`），这次只是把它渲染出来，没有改状态机。

## 3. 演示运行（自定义任务，intent=search）

```
计划：query_mode=model，提示检索词=d（桥接器对中文的劣质输出）
模型自己写：{"query":"多视角一致的 3D 图像生成","k":3}
-> search_papers 返回结果
-> read_paper 2409.18125
-> final_answer 1 条引用
完成：True，59.9 秒，约束解码
```

决策快照（就是决策卡的数据）：

| 步 | 当时可用 | 模型选择 |
|---|---|---|
| 0 | search_papers | search_papers（query 由模型写） |
| 1 | read_paper | read_paper 2409.18125 |
| 2 | read_paper / final_answer | final_answer |
| 3 | （终态） | — |

这比之前的"三步流水线"多了一个关键事实：**检索词是模型写的，而且它没有用提示里的 "d"**。

## 4. 附带的一处改动

实验台的 constrained 策略原先调用 `research71.worker`（没有约束解码），在自定义任务上会重演"读论文那步格式失败"。现改为 `research88.runner`，与阶段88 的约束解码保持一致。影响：实验台上所有 constrained 运行现在都走约束解码，与历史阶段82 的结果不再同协议。

## 边界

- 1 次运行，不能说明检索词质量；只证明"模型能自己写并被记录"。
- 决策卡的点击/渲染没有做浏览器自动化（沙箱禁止），验证的是：数据完整、JS 语法、资源已由服务端提供。
- `confirmed` 模式行为不变（有单测）；`model` 模式仍保留字符串校验。

## 复跑

```powershell
$plan = Invoke-RestMethod "http://127.0.0.1:8802/lab/custom/plan" -Method Post -Body $bytes -ContentType 'application/json; charset=utf-8'
# body: {"original_need":"...","intent":"search","profile_id":"cold","scope_id":"snapshot-2025-02-23","agent_query":true}
# 然后 /lab/custom/run，executed_query 留空
```
