# 阶段82：B 方案——被拒提案不占同一预算（2026-11-22）

假设（来自阶段80/81）：约束 Agent 的失败不是"合法动作做不完"，而是**一次被拒后，后续重试继续扣同一个 6 次预算**，直到预算烧完、工具表清空。B 把"到达服务器的提案"与"被拒的提案"分开记账，检验预算到底是不是瓶颈。

## 一、协议与两次修订（都先于对应运行）

| 版本 | 内容 | 结果 |
|---|---|---|
| v1 `stage82-b-rejection-allowance-v1` | 拒绝单独记账 + `MAX_REJECTIONS=2` 上限 | 未运行；冻结前撤销 |
| v2 `stage82-b-free-rejections-v2` | 拒绝单独记账，**不加新上限**（`max_steps=7` 已天然限制提案数） | 正式协议 |
| amendment 1 | 修正 v2 的一个副作用：去掉快照里两个新增字段 | 见第四节消融 |

撤销 v1 的理由：上限是一个诊断里不存在的新失败门槛，会让"为什么不完成"混入第二个变量。

## 二、改了什么

| 项 | 变化 |
|---|---|
| 记账 | `charge()` 只把**到达服务器**的提案计入 `charged`；被状态机或原生 schema 拒绝的提案计入独立的 `rejected`，不占 6 次动作预算、不占检索/读取配额 |
| 终止 | 仍然只有两条：6 次已服务动作，或 7 个 Agent 步；**没有新增拒绝上限** |
| prompt | 两份 prompt 各改一句：被拒提案不消耗 6 次动作，但 7 步仍限制运行 |
| 状态串 | 原计划在快照里加 `rejected_proposals` 两个字段，消融后**已移除**（见第四节） |

`validate()` 的判定与 `reason=` 文案与阶段81 完全一致；差分测试对冻结的 v81 模块逐项比对通过。

## 三、判定不变与测试

| 测试 | 结果 |
|---|---|
| `tests/test_rejection_allowance.py` | 7 项通过（拒绝不计费、6 次已服务动作仍然封顶、finalize 算已服务动作、v81 对照仍计费、端到端"先被拒后完成"） |
| `tests/test_state_constraint_messages.py` | 11 项通过 |
| `tests/test_state_constraints.py` | 8 项通过（两项断言按 B 的新记账更新，旧语义由 v81 对照测试保留） |
| `tests/test_unified.py`、`tests/test_schema_isolation.py` | 9 项通过 |

## 四、消融：两个状态字段把模型带偏了

第一轮 8 单元批次（代码里带了 `rejected_proposals` 两个字段）只有 4/8，且 `e73-recommend` 从阶段81 的 2/2 掉到 0/2：模型在第一次推荐后连续输出裸 `citation` 数组，6 步解析失败。

保持记账与 prompt 不变、只删掉两个字段后，同任务 2 次运行 **2/2 完成**（`reports/stage82/protocol-amendment-1.json`，模块与 prompt 哈希与最终代码一致）。

结论：记账改动不是回归原因，**在系统状态串里多加两个 JSON 字段就足以让这个 1.5B 模型格式崩坏**。因此字段被永久移除，记账信息只保留在事件与审计里。第一轮批次与消融记录全部保留，未删除。

## 五、正式批次（最终代码，4 任务 × 2 次）

| # | 任务 | 完成 | 已服务动作 | 被拒 | 步数 | 调用 | 秒 |
|---|---|---|---|---|---|---|---|
| 0 | e73-search | ✅ | 3 | 0 | 4 | 3 | 6.1 |
| 1 | e73-recommend | ✅ | 3 | 0 | 6 | 5 | 8.1 |
| 2 | e73-mixed | ✅ | 5 | 0 | 6 | 5 | 11.0 |
| 3 | e73-empty | ❌ | 1 | 3 | 9 | 8 | 17.2 |
| 4 | e73-search | ✅ | 3 | 0 | 4 | 3 | 6.4 |
| 5 | e73-recommend | ✅ | 3 | 0 | 6 | 5 | 9.3 |
| 6 | e73-mixed | ✅ | 5 | 0 | 6 | 5 | 12.1 |
| 7 | e73-empty | ❌ | 1 | 2 | 9 | 8 | 23.8 |

合计 **6/8 完成**，70,266 输入 token / 1,644 输出 token；**没有任何一次因预算耗尽而终止**。

## 六、停止规则：触发

预声明的规则是：如果 `e73-empty` 仍然失败、且终止原因是 `max_steps` 而不是预算耗尽，就说明 6 次动作预算不是瓶颈，停止预算调优。

实际两次都是 `charged=1/6`、`rejected=3/2`、`max_steps`——模型在 search 返回 0 篇后，反复提交带 `QZX_PAPER_1`、`QZX_PAPER_2` 两个**不存在 ID** 的 final_answer，被拒后继续换工具名（`mixed`、`recommend_papers`），直到步数用尽。预算从头到尾只用了 1 次。

**判定：预算不是瓶颈，B 的假设被证伪。** 继续在预算语义上做文章没有意义。

## 七、结论

- B 没有提升完成率（6/8 对阶段81 的 3/4，比例相同），唯一失败单元不变。
- 但失败机制被彻底换了：从"一次拒绝→预算烧完"变成"拒绝不花预算，卡在步数与模型能力"。这正是 B 想要的诊断价值。
- 负面结论同样重要：**瓶颈是该 1.5B 模型在零上下文提示下的格式遵循与终止判断**，不是预算设计。下一步应做模型能力对照（同协议换更大模型），而不是继续调预算。
- 附带发现：模型对系统提示文本极敏感——两个信息性 JSON 字段就能让一个原本 2/2 的任务变成 0/2，且两次运行完全一致。以后任何提示/状态文案改动都必须重跑，不能假定"只是加点信息"。

## 八、边界

- 8 次运行、单模型、每任务 2 次；不构成统计或质量结论。
- 与阶段73/81 只作同任务单元的描述性对照，协议语义已不同。
- 未重跑失败用例造成功；第一轮带字段批次与消融结果全部保留。
- 未训练、未扩目录、未改评价协议；真人相关性仍为 0。

## 九、复跑

```powershell
.cache\stage17\runtime\Scripts\python.exe -E -s -m unittest tests.test_rejection_allowance tests.test_state_constraint_messages tests.test_state_constraints
.cache\stage17\runtime\Scripts\python.exe -E -s -m research82.score_batch
```

证据：`reports/stage82/{protocol.json,protocol-amendment-1.json,batch-summary.json,batch-summary-state-fields.json,validation.json}`、`data/stage82-batch/`、`data/stage82-ablation/`。
