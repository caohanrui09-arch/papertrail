# Papertrail 最终演示版
交付2026-11-05。只在本机运行，默认不调用LLM。本轮没有新训练或公网发布。

## 一键启动
在资源管理器双击项目根目录的papertrail.cmd，或从任意PowerShell目录执行：

    & '<repo>\papertrail.cmd'

自动切到项目目录并打开 http://127.0.0.1:8791/ 。
实验页：http://127.0.0.1:8791/evidence.html 。

状态和停止：

    & '<repo>\papertrail.cmd' status
    & '<repo>\papertrail.cmd' stop

仅输入 .\papertrail.cmd 的前提是当前目录就是项目根目录，不能在<home>下依赖相对路径找到它。

## 当前电脑环境
- Python3.12.16；复用CPU控制环境.cache/stage17/runtime与Web环境.cache/stage39/runtime-secure。
- Web环境沿用26个已安装包，FastAPI0.162.0、Starlette1.10.0；无新组件，无需GPU、API密钥或远程CDN。
- 网站源码deploy/stage52；服务模块scripts.run_demo_delivery_local。
- 单实例、单worker，监听127.0.0.1:8791，不开放局域网。既有保护值：最多200访客、90API/分钟/访客、30重请求、20写请求、12应用并发；不是压测容量或生产QPS。
- 真实偏好继续使用data/stage39-visitors；不要删除session.key或SQLite。不能与旧站同时占用该私有卷。
- 状态.cache/stage52/service.json，日志.cache/stage52/logs；不随展示材料分发。
- papertrail-sid.cmd等旧入口保留作历史版本，本轮统一使用papertrail.cmd。
说明覆盖当前电脑现有环境，不宣称新机器零准备安装或第二台机器复现。

## 约3分钟演示脚本
以下为讲解安排，非录像计时结果。

|时间|操作|应看到的证据|
|---|---|---|
|0:00–0:25|首页说明定位，输入generative retrieval，点击开始检索|162篇试用目录、真实候选ID/v1、默认BM25|
|0:25–0:55|收藏Generative Retrieval as Multi-Vector Dense Retrieval|收藏计数增加；可撤销，不重置已有真实偏好|
|0:55–1:30|点击我的推荐，展开与你的收藏有何关联|实际收藏锚点及词项，已反馈论文排除|
|1:30–1:55|阅读推荐论文原摘要，切换调用轨迹|完整v1摘要、版本ID与来源URL；实际推荐和读取步骤|
|1:55–2:40|点击实验与证据，查看范围、训练对照、诊断|162网页/162结构/9000离线分开；完整分母质量、0/6诊断及收尾|
|2:40–3:00|来源与复核，下载聚合表或统一简历|文件和SHA可核对，解释实用默认与研究取舍|

无有效收藏时推荐页明确等待收藏。搜索无结果可换目录内英文术语；中文检索质量未经过真人评价，不伪造相关性。
演示可能更改你自己的真实收藏，请先备份，结束可撤销。本轮自动及浏览器验收均使用隔离空间。

## 范围与复核
网页162篇；9000是离线SFT规模。训练对照为重复使用tuning的描述性结果，未更改冻结选择；真人相关性尚未补齐。前缀先验是32训练前缀的损失参照，非已评价Top10推荐器。
架构、统一简历、关键结果及失败案例见RESUME_FINAL_V52.md。API报告reports/stage52/api-validation.json，浏览器报告browser-validation.json。

在项目根目录复跑：

    .cache/stage39/runtime-secure/Scripts/python.exe -E -s -m scripts.validate_demo_delivery --baseline
    .cache/stage39/runtime-secure/Scripts/python.exe -E -s -m scripts.validate_demo_delivery
    .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.verify_demo_delivery

前两条只写临时隔离目录；最后一条核验冻结收据。浏览器验收模块scripts.run_delivery_acceptance使用8792及.cache/stage52/ui-visitors，不触碰真实偏好。

## 分享边界
本地地址仅当前电脑可访问。本轮无公网HTTPS、真实多人负载或在线托管验证，未提供公网链接。聚合材料按原数据及组件条款评估展示，不打包data、.cache、模型及逐用户衍生。组件说明见reports/stage52/THIRD_PARTY_NOTICES.md和站内开源说明。
