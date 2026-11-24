# 搜索v2入口：复用与许可

原样复制先前核验的Preact11.1.0（MIT）preact.mjs/hooks.mjs和HTM3.1.1（Apache-2.0）htm.mjs及全文PREACT_LICENSE/HTM_LICENSE，文件在dist/vendor。没有npm脚本、安装或改写上游渲染器。查询与文章文本由原生Preact作为文本节点转义；不使用dangerouslySetInnerHTML。

GitHub比较preactjs/preact与gradio-app/gradio：两者当前未归档，读取README，并核对Preact MIT、render核心。Gradio许可证请求传输失败，因此本轮不声称已核查Gradio许可，不安装或复制该项目。复用现有组件适配成本较低，无新增运行时。源码与失败记录见reports/stage30/upstream-audit.json。当前仓库状态不代表漏洞审计，也不把上游当前源码版本冒充已固定11.1.0。

服务沿用现成FastAPI/uvicorn、SQLite FTS5、sklearn TFIDF/normalize/linear_kernel，许可证与原资产说明沿用已封存记录。本项目只新增只读目录/审查字段、固定候选内排序适配、桌面前端及启动器。使用摘要版本核验组件而不下载PDF。无生成式模型调用、无自动真人标签、无公网部署或外部会话上传。
