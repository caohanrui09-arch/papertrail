# 完整研究 Agent 资产恢复清单

此清单交接真实依赖，不承诺源码单独解压即可运行研究77/server.py。Windows演示包是公开阅读服务，不含这些原研究数据。

| 依赖 | 原路径或入口 | 接收方处理 |
|---|---|---|
| 当前源码 | research77及所复用的63–76、gsearch、third_party | 源码包已含；以当前解压根目录为准 |
| 独立CPU环境 | .cache/stage17/runtime + python + bootstrap | 原venv配置含发送方绝对路径，必须在接收方重建，不直接拷贝venv |
| CPU环境锁 | reports/stage17/requirements-win-cpu.lock、sklearn-target.lock；scripts/manage_stage17_env.py | 已含锁与现有适配代码；复核管理器中的Python版本路径，旧阶段脚本有历史版本硬编码，先审计后在新副本适配 |
| 研究副本 | .cache/stage17/replica | 内含冻结数据/报告/原算法源码与bundle-manifest；其依赖清单见native-asset-inventory.json，数据未分发 |
| 训练画像和历史交互 | data/stage9-recommendation、replica/data | 原Scholar Inbox数据源在THIRD_PARTY_NOTICES.md有固定commit与CC BY-NC-ND4.0说明；接收方独立获取并按原协议本地生成，变换后的用户级数据不随源码分发 |
| 万篇明确v1文本及原响应 | data/stage13-expansion、replica/.cache及data | 独立取得原版本文本与来源收据；不能拿最新版或合成摘要替代历史v1 |
| 自定义任务/历史及评价输入 | data/stage19-unified、stage64-http、stage71-custom、stage73-evaluation等 | 含用户派生上下文和轨迹，未打包；缺失就明确关闭对应入口，使用新合法数据建立独立新批次，不冒充旧评价 |
| 本地模型 | .cache/models/Qwen2.5-1.5B-Instruct | 约2.88GiB权重，按已有模型来源记录独立获取；当前加载local_files_only，不会自动补下载 |
| 当前阅读网站 | deploy/stage66 + research75–77展示层 | 已包含在演示包和源码包；167篇元数据及可分享聚合证据，不含访客存储 |
| 旧训练检查点 | runs/，约11.68GiB | 网站及Agent演示不需要；继续旧训练研究时另核对上游许可与资产来源，不为展示转移所有optimizer状态 |

`research77/server.py`先切换到`.cache/stage17/replica`并加载原生模型，原数据签名验证通过后才提供8802接口。`gsearch/local_service.py:load_model`依赖原bundle校验、stage13文档与stage9训练CSV；缺数据时应失败，不应用空表或任意替代值绕过。

推荐接收顺序：先体验可运行阅读包 → 审计源码/依赖 → 接收方独立准备有许可的研究资产 → 新目录重建CPU环境 → 只读校验目录与数据签名 → 搜索/推荐/原文工具 → 固定流程 → 小批真实模型及预算/SSE恢复。不能从旧53次调用或142项本机验收推断新机器已通过。

当前完整工作区目录大小（不等于传输包大小）：.cache约11.90GiB，runs约11.68GiB，data约1.13GiB。数据清单只含路径、字节与hash，不含用户级记录。所有许可及来源原文保留在源码包，若未来准备公开仓库、部署或商业用途须重新核对分发范围。
