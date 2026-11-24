# 9000篇SID与受控SFT：本地运行说明

本轮完成独立的离线研究链路，不修改网站。它使用阶段44冻结的9000篇明确v1目录和真实反馈，复用MiniOneRec官方CPU量化、ZeroGR树和Hugging Face原生训练/解码；基础模型为既有T5-small，文本表示为TF-IDF+SVD128。因此属于本项目的轻量适配，不是官方Qwen模型、辅助文本任务或RL复现。

## 固定输入与映射

目录只包含训练截止前按现有可用时间代理可用的论文。标题与原始v1摘要→12000维TF-IDF→SVD128/L2→官方PRQ（64×64×64，10次迭代，seed42）。全部9000篇均参与无监督文本量化；无训练点赞论文也有SID。

原始SID有1197次超额碰撞、2046篇处于碰撞组；官方身份后缀消除歧义，最终9000个唯一ID。四个SID原子token加EOS共5个token；新增203个词元。身份后缀只承担身份区分，不是第四层语义。两臂保留相同token集合、完整SID集合、树结构及每篇长度；2046篇碰撞组保持原映射，6954篇单例在训练频率桶内打乱。频率桶匹配不是逐token精确频率匹配。

映射与完整token监督位于Git忽略的 `data/stage45-sft/`。`content.tokens.json`、`shuffled.tokens.json` 存含EOS的完整token IDs；两个 `*.train.tokens.jsonl` 各98887条，共494435个监督token。全量独立核验它们与原始历史/目标一致。模型输入只含固定任务前缀及最近20篇历史的SID，没有qid、用户身份、事件时间或评价答案。

## 精确小规模预算

`reports/stage45/design.json` 先于量化拟合冻结；`run-lock.json` 在正式模型训练前封存。模型原始权重、扩展tokenizer、两组映射、数据顺序、代码、画像、基线和预检文件均有哈希。

- 基础模型：google-t5/t5-small `df1b051c49625cf57a3d0d8d3863ed4d13564fe4`，本地safetensors。
- 两臂：内容SID / 训练频率分层打乱SID；种子42、2024、3407，共六个运行。
- 每跑：128次优化更新，batch8，固定排列前1024条真实样本，5120个目标监督token。
- 相同样本顺序：seed271828排列全部98887条后取前1024；HF有限IterableDataset不再二次打乱，实际消费顺序核验。
- 全参数SFT；BF16自动混合精度、FP32主权重；AdamW lr5e-4、betas0.9/0.999、eps1e-8、weight_decay0.01；恒定学习率、无warmup、梯度裁剪1。
- 输入固定padding96，实际最长84；encoder-decoder结构不将encoder prompt当作decoder监督，标签直接使用token IDs。无需重分词文本别名；标签等长且无pad标签。
- 只保存预定第128步；没有根据损失曲线改变预算或追加checkpoint。

两臂每个相同种子的新增词嵌入初始化哈希一致。原始基础权重也完全一致。训练只使用约1.04%的监督池，因此本轮质量只代表这个小预算；不代表完整训练性能上限。

## 预检与评价

预检每臂4个dry forward/backward batch，不执行optimizer.step，不保存拟合权重；随后丢弃模型，从同一基础权重启动正式训练。测试beam10、EOS、9000篇可逆映射、已读正/负反馈屏蔽、十篇唯一、重复输入和额外遮挡。资源估计明确区分干跑推算与正式训练实测。

生成使用HF原生beam10、length_penalty0、无采样。ZeroGR原树的后代集合用于在beam扩展前屏蔽已反馈论文，保留完整原始token轨迹。空历史统一使用阶段44冻结训练流行度，不让神经模型与基线获得不同兜底。

三条基线使用相同9000目录、同一最近20篇正反馈历史及全部训练正/负已读屏蔽：训练流行度、TF-IDF内容、官方Jaccard SAR。SAR的协同矩阵由全部可用训练正反馈拟合，请求兴趣向量使用同一last20历史；无合规交互论文分数为零。适配乘法与官方pseudo-history接口核对。内容向量由同一冻结目录拟合；没有额外调参。基线使用完整训练反馈，SFT只用1024条监督，二者并非相同训练曝光量；本轮主要受控结论来自两组相同预算的SID，基线只作实用参考。

全部预测生成后才由独立CPU进程读取tuning标签。计分直接调用阶段44封存脚本，完整保留46352条正反馈、3571名用户；主指标user-macro NDCG@10，另报Recall/MRR、冷热组、有效/重复槽位和成本。目录外目标不从分母消失。本轮只跑tuning，未读dev标签、未选dev checkpoint、未启动RL。

延迟日志为batch16的离线实测及每名有历史用户的摊销时间，复用固定画像预测；不等同于单请求p95或线上吞吐。

## 核验已有交付

先进入实际项目目录，避免在用户主目录直接执行相对入口：

```powershell
Set-Location '<repo>'
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.validate_sft_delivery
```

再次执行仅核验已封存文件，不重新拟合或覆盖模型。详细结果见 `reports/阶段45_SID与受控SFT试验.md`、`reports/stage45/tuning-results.json`；六跑模型和原始预测在 `runs/stage45/`，不公开分发。

## 从无阶段45产物的研究副本复跑

在保留阶段44及更早全部输入、原CPU环境、共享CUDA环境位置和缓存权重的独立本地研究副本中，依次执行；不要覆盖本项目已封存结果：

```powershell
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.prepare_sid_sft
& ../.venv/Scripts/python.exe -E -s -m scripts.run_sid_sft tokenize
& ../.venv/Scripts/python.exe -E -s -m unittest discover -s tests -p test_sid_sft.py -v
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.validate_sid_sft
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.freeze_sft_baselines
& ../.venv/Scripts/python.exe -E -s -m scripts.run_sid_sft preflight
& ../.venv/Scripts/python.exe -E -s -m scripts.run_sid_sft freeze
& ../.venv/Scripts/python.exe -E -s -m scripts.run_sid_sft train
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.baseline_sid_sft
& ../.venv/Scripts/python.exe -E -s -m scripts.run_sid_sft predict
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.score_sid_sft_fast
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.validate_sid_scoring
```

计分的操作加速另见scoring-addendum.json与scoring-lock.json：原函数对同一空画像的每条事件重复排序，当前入口先确认所有同用户预测一致，再用原evaluate逐独立画像检查共同兜底，完整46352事件仍交给原score_rows计分。10个对抗案例和九组各512个固定索引真实事件与原evaluate逐字段比较；指标、分母、位置、分组和选择规则不变，原函数及运行锁没有修改。原score_sid_sft入口仍保留。

预检或验证失败时保留日志，不能直接将门槛字段改为true。涉及代码/数据/预算修改时必须另建版本及运行锁；共享CUDA环境未增加依赖，不能把CPU环境的pandas依赖直接写入共享环境。

当前目录可排序目标只占tuning正反馈13.90%；用户平均可排序比例10.84%是宽松oracle上限，不是模型实际Recall。无训练点赞目标仅14条，冷论文质量证据很少。量化seed42和打乱seed2024各一套，三种子只覆盖训练随机性。旧tuning/dev已参与先前研究，不是全新独立测试。原数据范围、v1文本可用时间代理与交互许可限制继续有效。
