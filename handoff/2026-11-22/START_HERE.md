# Papertrail 朋友交接包

更新：2026-11-22；当前开发基线：阶段77。

## 给朋友发送什么

1. `Papertrail-Windows-Preview.zip`：可运行的论文网站，含 Windows x64 Python 和已装依赖；无需先装 Python、Node 或 GPU。
2. `Papertrail-Source-Handoff.zip`：项目源码、开发说明、第三方许可及公开网站资产；包含真实 Agent 和算法代码。
3. 本说明及 `NEXT_AGENT_PROMPT.md`：继续开发时交给朋友的 Codex。

两个包用途不同。演示包可以搜索当前167篇目录、读取原v1摘要、收藏、不感兴趣、内容推荐、阅读笔记及备份；它没有原万篇实验画像与本地Qwen权重，不执行真实LLM Agent。Agent相关入口明确进入资产恢复说明，不会冒充模型已执行。源码包保留完整Agent实现，但不等于完整运行资产。

## Windows 打开网站

解压 `Papertrail-Windows-Preview.zip` 到普通可写文件夹，例如 `D:\Papertrail-Preview`。不要在ZIP预览窗口内运行。双击 `START-PAPERTRAIL.cmd`，保持启动窗口打开，浏览器访问 <http://127.0.0.1:8791/>。停止时在启动窗口按 Ctrl+C。

启动后先搜索 `retrieval`，打开一篇论文检查摘要和版本链接，再试收藏与推荐。收藏保存在解压目录下新建的 `visitor-data` 中；发给下一位朋友时不要复制这个目录。各浏览器使用独立凭据；备份可用站内导出/导入。

若8791端口已被占用，先关闭原有 Papertrail 服务，再重试。不要为了占端口结束不认识的进程。日志直接显示在启动窗口。此包是本地演示，不是公网服务器；在线搜索需联网及上游接口可用，本轮未重新验收在线接口。

## 继续开发

把源码包另解压到 `D:\Papertrail-Source`，用编辑器或 Codex 打开这个文件夹，先发送 `NEXT_AGENT_PROMPT.md` 中的提示词。当前入口是 `research77`，根README还含早期8767端口说明，当前版本以本交接说明及 `docs/FIRST_VIEW_V77.md` 为准。

代码导航：

| 路径 | 职责 |
|---|---|
| research77/web + research77/first-view.* | 当前首页与首屏表现层 |
| scripts/run_research77_workbench.py | 当前论文网站入口，复用76/75/73与deploy/stage66 |
| deploy/stage66/trialsite | 论文搜索、真实摘要、内容推荐、访客空间和备份 |
| research77/server.py | 万篇算法与Agent服务8802，依赖原研究资产 |
| research71/worker.py、runner.py | 真实模型及参数/状态约束；复用70事件流 |
| research76 | 需求交接、同池画像对照、任务导出、试用页面 |
| research73–75 | 冻结评价、可视化、色彩覆盖层 |
| gsearch、third_party | 原算法适配与固定开源实现 |

推荐先改独立新阶段并保持旧阶段源码不动。所有新功能先读 AGENTS.md、task_plan.md、notes.md 和最新交付文档；新增主要方案先调研GitHub及许可。新实验和旧数据/结果分开保存。

## 完整 Agent 的恢复范围

原完整研究工作区约25GiB，不能靠这两个小包直接恢复。详见 `FULL_AGENT_ASSETS.md` 与 `native-asset-inventory.json`：需要自行取得原许可数据、重建隔离运行环境、恢复明确版本文本与Qwen权重，并通过原生校验。网站演示的访客收藏不接入冻结Agent画像。

源码包没有 `.cache/`、`data/`、`runs/`、访客数据库、密钥、模型权重或用户派生预测/轨迹。`.gitignore` 本来就排除了这些；只做Git克隆也不能恢复完整Agent。历史manifest中的哈希是原作者机器的证据，源包有意缺失原研究资产，不能直接把缺文件当作篡改或用伪数据补齐。

## 实验结论与边界

网站演示搜索与内容推荐可用；生成式SID实验没有足够证据支持继续加量，未进入RL。阶段73同条件4任务对照的协议完成是固定流程4/4、原LLM0/4、约束LLM3/4，包含全部失败；这些不是语义正确率。真人相关性标注为0，NDCG/MRR质量结论暂不可计算。没有生产QPS、CTR、真人质量提升或第二台机器成功记录。

本轮包在当前电脑的不同路径解压验收，结果见 `handoff-validation.json`。朋友电脑上的实测仍需朋友执行；当前电脑关机不影响朋友本地运行演示包。
