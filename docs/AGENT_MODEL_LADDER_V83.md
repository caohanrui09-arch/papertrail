# 阶段83：模型能力梯度（0.5B vs 1.5B，2026-11-22）

问题：阶段80–82 把失败归因到"模型能力"，但一直只有 1.5B 一个点。本轮在同一框架、同一批任务上加入本机已有的 Qwen2.5-0.5B，检验能力是否是主导因素。

## 一、设计（先冻结后运行）

| 项 | 内容 |
|---|---|
| 协议 | `stage83-model-ladder-v1`，sha256 `4172d946…3f77f` |
| 变量 | 只有模型：0.5B（新）对 1.5B（阶段82 正式批次，已保留） |
| 不变 | 4 条冻结任务 × 2 次、constrained、同一 worker/runner/约束状态机/prompt、6 次动作/7 步/2 检索/2 读取/30000–1280 token、greedy 解码 |
| 权重 | 0.5B 本地复制，revision `7ae5576…`，8 个文件逐一哈希与 `source.json` 一致；Apache-2.0 |
| 3B 尝试 | 已中止：hf 与镜像均约 **0.8 MB/s**，6.2GB 需约 2 小时；已传约 1.96GB 后删除，未运行 |

## 二、结果

| 模型 | 完成 | 终止原因 | 解析失败步数 | 状态机拒绝 | 扣减动作 |
|---|---|---|---|---|---|
| Qwen2.5-1.5B | **6/8** | 完成 6、max_steps 2 | 4 | 5 | search 3、recommend 3、mixed 5、empty 1 |
| Qwen2.5-0.5B | **0/8** | max_steps 8 | **24** | 14 | search 1、recommend 0、mixed 2、empty 0 |

逐任务：

| 任务 | 1.5B | 0.5B |
|---|---|---|
| e73-search | 2/2 | 0/2 |
| e73-recommend | 2/2 | 0/2 |
| e73-mixed | 2/2 | 0/2 |
| e73-empty | 0/2 | 0/2 |

两臂内部两次运行完全一致（greedy 解码 + 相同上下文），不是抽样波动。

## 三、0.5B 是怎么坏的

- **e73-search**：检索拿到论文后不调用 `read_paper`，而是直接写一段 BibTeX `@article{...}` 或自然语言总结，连续 6 步解析失败。
- **e73-recommend**：把 `k` 依次写成 4、5、6、7、8、9（越界一次就换下一个更大的数），6 次全部被 `invalid_k` 拒绝，一次检索都没发出。
- **e73-mixed**：开始正常（2 次动作），随后重复调用已不可用的 `recommend_papers`，5 次未知工具。
- **e73-empty**：把 `k` 写成 73，然后连续输出无 JSON 的自然语言。

同一套 `reason=…` 文案对 1.5B 至少能读到"期望 0 条引用"，对 0.5B 基本无效——它连工具调用格式都维持不住。

## 四、结论

1. **框架是通的**：同一 harness 下 1.5B 能 6/8 完成，说明约束、工具、读取、引用链本身没有坏。
2. **能力是主导因素**：参数量减到三分之一，完成率 6/8→0/8，解析失败 4→24，且 0.5B 的失败几乎全是格式崩溃而非协议误判。
3. **e73-empty 在两个尺寸都失败**：该单元更可能是能力门槛问题，但**本轮不能证明更大的模型会修好**——只有一个下探点，没有上探点。3B 上探因带宽放弃，未运行。
4. 这与阶段82 的结论一致：预算不是瓶颈，提示文案只能改善"能读懂提示的模型"的失败形态，无法弥补格式与终止能力。

## 五、边界

- 每臂 8 次运行、4 条任务、单次/任务；不作统计或质量结论。
- 单一下探点不能确定能力阈值，也不能外推 3B/更大模型的表现。
- 未训练、未扩目录、未改评价协议；真人相关性仍 0。
- 3B 权重未获得，也没有把未完成的下载算作任何结果。

## 六、复跑

```powershell
.cache\stage6-env\Scripts\python.exe -E -s -u -m research83.worker --input data\stage83-batch\spec.json `
  --output data\stage83-batch\result.json --events data\stage83-batch\events.jsonl `
  --model .cache/models/Qwen2.5-0.5B-Instruct
.cache\stage17\runtime\Scripts\python.exe -E -s -m research83.score_ladder
```

证据：`reports/stage83/{protocol.json,protocol.sha256,ladder-summary.json,validation.json}`、`data/stage83-batch/`。
