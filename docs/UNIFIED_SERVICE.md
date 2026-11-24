# 万篇论文搜索、推荐与带来源回答

统一入口使用同一10000篇明确arXiv v1、固定用户历史与可用时间规则。可搜索论文，也可从训练期兴趣画像推荐，再读取原v1摘要并输出带ID、版本、标题和链接的摘录。当前日期仍是历史回放参数；不会加入今天的新论文或新反馈。

在项目根目录启动或管理服务：

```powershell
.\unified-service.cmd start
.\unified-service.cmd status
.\unified-service.cmd stop
```

健康接口：http://127.0.0.1:8766/health 。原阶段18服务仍使用8765和service.cmd，两者独立。

运行固定流程或真实本地Qwen调度：

```powershell
.\unified-demo.cmd fixed
.\unified-demo.cmd llm_agent
```

查询主题或指定搜索与推荐组合：

```powershell
.cache/stage6-env/Scripts/python.exe -m gsearch.unified_agent --policy fixed --intent search --query "retrieval augmented generation"
.cache/stage6-env/Scripts/python.exe -m gsearch.unified_agent --policy llm_agent --intent mixed --query "graph neural networks"
```

CLI默认绑定一个固定训练用户与历史评价末时点；显式用户和时点通过API创建会话。新输出自动进入忽略的data/stage19-unified/demo-*，包含回答、原工具轨迹、实际耗时和LLM用量。结果不会覆盖旧演示或上传。

API顺序：POST /sessions（可给user_id、带时区at及content/rrf/cold_aware）→ POST /sessions/{id}/tools（name和arguments）→ GET /sessions/{id}查看轨迹 → DELETE /sessions/{id}。工具名search_papers、recommend_papers、read_paper；finalize负责来源验证和回答输出。

```json
{"name":"search_papers","arguments":{"query":"graph neural networks","k":3}}
```

先读取检索或推荐返回的ID，再提交引用：

```json
{"name":"finalize","arguments":{"citations":[{"doc_id":"实际已读取的ID","quote_index":0}]}}
```

每会话最多6次工具尝试（含finalize）、2次检索、2次读取；到达服务的失败也计工具额度，模型解析失败计LLM调用和token额度。容量64会话、15分钟TTL。回答只从成功读取的原摘要摘录，不声称全文理解、自由总结或语义正确性。空检索可拒答；检索返回了论文却没有读完时，不能用空引用绕过验证。服务只监听回环地址，适用于当前电脑。

LLM模式是显式开启的实验入口，调试中出现重复检索、非法参数与无法完成最终提交。即使若干案例能走通，也不能预期其稳定完成任务；失败返回非零退出码并保存原轨迹，不静默切换固定流程。受控对照给定显式intent，不评价自由文本意图识别。

服务使用阶段17独立CPU运行时；Qwen推理只读使用既有stage6 CUDA环境及已缓存的1.5B权重，没有升级共享环境。smolagents执行工具循环，项目适配器只处理Qwen消息格式和工具/引用协议。

复核任务：scripts.prepare_stage19_tasks构造4个tuning和12个正式受控任务；scripts.benchmark_unified依次执行tuning、lock、evaluation；scripts.score_unified独立重计分。正式任务检验标题定位、路由与原文引用，不能代替真实用户相关性、新独立评分时段或线上AB评价。默认保留固定流程，LLM模式显式选择。
