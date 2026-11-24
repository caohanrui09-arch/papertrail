# 阶段81：A 方案——拒绝诊断文案（2026-11-22）

目标：在不改变任何判定与预算的前提下，让"为什么被拒"可读、可机读，并让预算耗尽的终止状态明确。**本阶段确实改变了模型看到的文本，因此先冻结新协议再改代码，历史数字不再与本轮直接可比。**

## 一、冻结

| 项目 | 内容 |
|---|---|
| 协议 | `stage81-a-messages-v1`，`reports/stage81/protocol.json`，sha256 `fe5a08db…a67f0` |
| 改动前模块副本 | `research81/frozen_state_constraints_v79.py`，sha256 `fbce46b1…1e92`（与提交前 `gsearch/state_constraints.py` 逐字节相同） |
| 冻结输入 | 状态机、约束 Agent、schema 隔离、unified agent、79 号 runner/clients、两份 prompt、4 条冻结任务（含 hash） |
| 不改 | 判定逻辑、预算、`legal/readable/final_count/can_finish`、工具集合、prompt 模板、评分 |

## 二、改了什么

| 旧文案 | 新文案（同样拒绝） |
|---|---|
| `State action unavailable: read_paper` | `reason=read_already_read / read_never_returned / read_wrong_branch / read_budget_exhausted` + 该 ID 来自哪个分支、仍需哪个分支、当前可读 ID |
| `ID is unavailable/already read` | 三种情况分开：从未返回 / 已读过 / 分支不符（阶段80 的核心歧义） |
| `Final citation count does not satisfy explicit task` | `reason=final_citation_count … expected exactly 0 citation(s) for intent=search with returned=0; got 2` |
| `Nonnullable integer k in1..3 required` | `reason=invalid_k … got None` |
| 无合法动作时仍要求"Generate a legal call" | `TERMINAL: no legal action remains (attempts used 6/6)…` |

每条拒绝末尾附 `attempts=…/6 retrieval=…/2 read=…/2 returned=… read_ids=… required=…`，审计脚本可直接按 `reason=` 归类。

## 三、判定不变（先证明，再跑模型）

- **差分测试**：冻结副本与新实现并排重放 6 组脚本场景 + 300 次随机提案，每一步的接受/拒绝、`charged/retrieval_charges/read_charges`、`readable()/legal()/can_finish()/final_count()` 全部逐项相同。
- **测试**：`tests/test_state_constraint_messages.py`（11 项，含差分与文案断言）+ `tests/test_state_constraints.py`（8 项旧回归）共 19 项通过；`tests/test_unified.py`、`tests/test_schema_isolation.py` 共 9 项也通过（分别运行）。
- 期间修正一处文案优先级：已读 ID 原会被通用门槛拦下，属"文案选择"而非判定变化，差分测试仍全绿。
- **已知测试问题（非本轮引入）**：把上述 4 个模块放进同一进程运行时，`test_schema_isolation` 会报 `Argument answer has type 'string' but should be 'object'`。原因是旧 `constrained_agent.run`（非隔离路径）会改写 smolagents `FinalAnswerTool.inputs` 的类级默认值，被同进程先前运行的原生循环测试污染；用冻结副本加载同一组合可复现（`research81/check_preexisting_isolation.py`）。生产路径走 `IsolatedActionState` 逐实例深拷贝，且 worker 每次运行后断言默认 schema 未变，本轮 4 次运行全部通过该断言。该问题只影响"同进程跑多个测试模块"的测试卫生，未修改测试或隐藏失败。

## 四、受控批次（4 冻结任务 × constrained × 1 次）

| 任务 | 完成 | 扣预算 | 拒绝 | 最长原样重复 | 模型调用 | 秒 |
|---|---|---|---|---|---|---|
| e73-search | 是 | 3 | 0 | 1 | 3 | 5.3 |
| e73-recommend | 是 | 3 | 0 | 1 | 5 | 11.9 |
| e73-mixed | 是 | 5 | 0 | 1 | 5 | 11.8 |
| e73-empty | **否** | 6 | 1 | 1 | 8 | 15.4 |

同任务单元与阶段73 对照（仅描述，不是对照实验）：

| 任务 | 阶段73（旧文案） | 阶段81（新文案） |
|---|---|---|
| e73-search | 完成 | 完成 |
| e73-recommend | 完成 | 完成 |
| e73-mixed | 完成 | 完成 |
| e73-empty | 失败，5 次拒绝、同一载荷原样重发 5 次 | 失败，1 次拒绝、**无原样重发** |

## 五、e73-empty 这次是怎么失败的

1. search 返回 0 篇，唯一合法动作是 `final_answer`。
2. 模型交了 2 条编造引用 → 被拒，文案明确：`expected exactly 0 citation(s) … returned=0; got 2`。
3. 模型没有改成 `{"citations":[]}`，而是连续尝试 `search_papers`、`recommend_papers`、甚至把工具名写成 `mixed`，并出现只含 `citations` 键的畸形输出；扣满 6 次后进入终止态。
4. 第 7 步的 system 指令中确实出现 `TERMINAL: no legal action remains (attempts used 6/6)`，说明终止提示送达了模型，但它仍未产生合法终局。

**结论：A 消除了"盲重发"（5→0），把失败从死循环变成了可解释的能力不足；但没有改变完成率。**

## 六、结论与边界

- A 达成设计目标：同样拒绝、原因明确、可机读、终止状态明确；不再把"分支不符"说成"already read"。
- A **没有**提高完成率：本批 3/4，加上阶段80 的历史运行合计 constrained 16/21（76.2%，与之前 13/17 的 76.5% 基本一致）。不能声称文案改进提升成功率。
- 失败率仍集中在弱模型不按反馈修正。若继续提升完成率，需要 B（拒绝不占同一预算）或换模型/改提示，且必须另立冻结协议与同预算对照。
- 4 次运行、单模型、每任务 1 次，不构成统计或质量结论；未重跑失败用例造成功；真人标签仍 0。

## 七、复跑

```powershell
# 判定不变
.cache\stage17\runtime\Scripts\python.exe -E -s -m unittest tests.test_state_constraint_messages tests.test_state_constraints
# 批次评分（只读，不加载模型）
.cache\stage17\runtime\Scripts\python.exe -E -s -m research81.compare_batch
```

证据：`reports/stage81/{protocol.json,protocol.sha256,batch-summary.json,validation.json}`、`data/stage81-batch/{spec.json,result.json,events.jsonl}`。
