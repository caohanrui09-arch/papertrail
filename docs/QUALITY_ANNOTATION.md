# 主题检索与个性化组合：人工标注准备

本轮已准备24条需求草稿和423个去重的需求—论文候选对。用户确认目前无人标注，因此**真人原创需求0、人工相关性标签0、人工质量分数未计算**。所有单条需求都保留assistant_draft来源；将来人工确认后仍是“人工确认的模型草稿”，不能改称真实用户原创问题。

## 当前材料

所有含历史兴趣、候选和标签的材料都在本机忽略的data/stage20-quality/，不上传或公开。

| 文件 | 用途 |
|---|---|
| inputs/queries.json | 24条草拟英文检索需求，主题/推荐/组合各8；主题组整体划分tuning9/evaluation15 |
| work/query-review.csv | 将来人工逐条确认需求适用性；保留原文及来源，confirmed填yes/no、reviewer_id、带时区reviewed_at |
| work/annotations.csv | 可编辑的盲标注表；只填写grade、annotator_id、judgment_origin、judged_at、rationale |
| blind/candidates.csv | 冻结的盲标注表模板；无方法名称、名次、分数或预填标签 |
| blind/label-studio-tasks.json | Label Studio原生data-only导入材料，无predictions或预标注 |
| blind/label-config.xml | Label Studio Choices配置；只显示需求、同一五篇历史上下文、原v1标题摘要和来源 |
| work/real-query-intake.csv | 真实人类需求的可编辑空收集表；templates/内保留不可变空模板，当前尚无实收记录 |
| evaluator/ | 评分方的ID、方法来源、原文核验和历史映射；标注时不要查看 |

标注者只能获得blind/和work/，不查看evaluator/、runs/及成本报告。数据按需求分组，组内候选按与方法无关的hash排序。这个文件分离约定提供实验盲法，不是防止电脑所有者访问文件的权限系统。

推荐/组合任务均为带明确主题的需求；个性化部分来自五篇真实训练点赞论文构造的匿名场景，而非真实用户对此问题的自述。三方法共享同一场景、目录、日期和全部训练正负seen过滤。个性化向量只使用标注者看到的这五篇原文上下文。目录仍是历史快照，可用时间沿用v1提交日结束+24h代理，不能称已证实的历史入库；需求在本轮草拟，模拟在该快照上提问。该试验不能据此声称真实用户满意度收益。

## 将来如何标注

先在work/query-review.csv确认需求是否清楚、领域是否适合。若需要修改文本，建立新查询及候选池版本；不要直接改字后沿用旧排名。无法确认的需求填no并说明原因，不能据算法表现删题。

grade定义：0不符合明确需求；1部分符合，或关键约束在摘要中没有依据；2直接覆盖核心问题及适用约束。显式主题优先，历史只作上下文。阅读摘要后仍有无法判断之处时保留说明，不把未知默认为0。judgment_origin必须显式填human，annotator_id可用化名，judged_at使用带时区时间如2026-10-28T15:00:00+08:00，rationale简述依据。没有判断的行保持五个标注字段全空。

CSV的文字单元格已对公式前缀作显示转义，原始文献JSON未改。不要修改标注表中的需求、上下文、标题、摘要或来源列。它们在导入时与冻结模板逐项核对。候选摘要来自原生解析器重新核验的官方v1，不是生成摘要。

可选Label Studio：在后续独立的本地标注环境创建项目，使用blind/label-config.xml并导入blind/label-studio-tasks.json，格式依据官方[Choices](https://labelstud.io/tags/choices)和[导入说明](https://labelstud.io/guide/tasks.html)。当前仅准备并校验了JSON/XML格式，**没有安装、启动或声称验收Label Studio前端**。标注完导出JSON；取消、多次冲突、缺失判断和模型predictions都不能自动变成真人标签。导入需操作者明确声明human来源；这只是来源声明校验，不是身份认证。

```powershell
.cache/stage17/runtime/Scripts/python.exe -E -s -m gsearch.human_quality import-label-studio --input data/my-local-label-export.json --output data/stage20-quality/work/imported-human.csv --annotator-id REVIEWER_ALIAS --attest-human
```

多人不一致时先人工仲裁并保留记录，不自动多数投票或用模型裁判替代。初期可让另一名人员复核部分候选；目前没有第二标注者，因此一致性指标也未计算。

## 查看状态和未来评分

```powershell
.\annotation-status.cmd
```

当前预期返回awaiting_human_query_confirmation_and_judgments，人工判断0/423，NDCG/MRR为null。评分要求目标split全部需求经人工确认、全部池内候选都有明确真人来源的0/1/2标签。空白或部分标注会阻止评分，不偷偷当作不相关。

全部标完后依序执行；若使用导入文件，在score及freeze时都追加--input data/stage20-quality/work/imported-human.csv：

```powershell
.cache/stage17/runtime/Scripts/python.exe -E -s -m gsearch.human_quality score --split tuning
.cache/stage17/runtime/Scripts/python.exe -E -s -m gsearch.human_quality freeze
.cache/stage17/runtime/Scripts/python.exe -E -s -m gsearch.human_quality score --split evaluation
```

三种方法和0.7查询/0.3上下文权重目前预先固定，没有根据标签选型。tuning评分后再封存才允许evaluation；改方法或权重需要新的版本和锁，不能覆盖现有结果。输出放在human-results/，属于将来结果，不会覆盖准备阶段收据。人工工作表和未来结果未纳入准备阶段不可变文件清单。

## 指标与成本边界

池内NDCG@10复用sklearn1.9.1原生ndcg_score，等级增益为2^grade-1，理想排序只取已完整标注的候选池；短结果用零增益空位表示，不把未返回的相关文档补进Top10。MRR@10直接调用固定BEIR原版mrr，grade>=1算相关，上游四舍五入到5位。无已判相关论文的需求仍计入分母并单列。池外是否存在相关论文未知，**不计算完整目录Recall**。新增方法若返回池外论文，必须先扩展候选池、补标并重新冻结。

同时报告候选池标注覆盖、各方法已返回结果的标注覆盖及Top10返回槽位比例。未标注也不能先比较NDCG高低。

成本已在相同CPU进程用24需求×3方法×3轮测量，轮换方法顺序，无查询分数或排名缓存；BM25首次建快照、一次模型装载/拟合单列。纯查询稀疏向量与个性化稠密向量调用不同的原生kernel路径，当前耗时差异不能单独归因于算法复杂度或推广为生产QPS。质量仍待人工标注，不能按延迟就宣布哪种推荐方法更好。

## Agent失败归因

阶段19的12个正式LLM任务保留5成功/7失败：3个重复检索循环、3个非法参数导致有效检索未启动、1个读取/路由后未提交。共31次重复工具尝试、6次非法参数拒绝、26次预算拒绝；分类可重叠，不能相加当作任务数。遗漏k时原生工具使用默认3，合法调用通过；模型显式生成null/布尔值时保持拒绝，没有把错误参数悄悄修成成功。已运行接口对照测试，未发现可复现的合法请求被后端错误拒绝，因此本轮没有改旧接口或增加LLM调参。

论文语义选错数量留空，不能从工具协议错误推断相关性。没有被接受的最终回答也不全是“答案内容错误”，须结合前面的参数、路由和预算事件判断。
