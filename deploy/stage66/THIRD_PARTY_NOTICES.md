# Papertrail 阶段39试用版来源与许可

本包为完整论文发现终端应用，保留阶段38首页/工作台、真实摘要、收藏、内容推荐和备份功能。组件不作为独立库、移植组件包或模板商品分发。

## 前端

Preact 11.1.0（MIT）、HTM 3.1.1（Apache-2.0）、Anime.js 4.5.0（MIT）、highlight-words-core 2.0.0（MIT）均原样保留。React Bits Spotlight 派生组件沿用原阶段37的 Pre​​act/HTM 适配，Copyright 2026 David Haz，许可为 MIT + Commons Clause，不能简写成无附加限制的 MIT。完整原文在 web/vendor/；所有运行依赖的版权和许可原文合并提供于 web/open-source.txt。没有复制 Aceternity Pro、Motion Sites 预览图或 Uiverse 组件代码。

highlight-words-core 发布 gitHead 86979e99cb6588b1cecdaaf332ae091dcad3e726；Spotlight 原 JSX/CSS Git blob ae052fce900c0f1062db866a2997a0429b744a21 / a4c9b873b8d474aa671b74cde70384bc7ce93070。阶段39只修改入口的目录/访客/数据说明和旧备份迁移提示，其他前端运行组件保持原字节。

## 后端与实际复用

运行依赖固定在 requirements.lock（26 个包及分发文件 SHA256），保留安装包本身全部许可证；生成的 web/open-source.txt 包含 44 份许可/版权文件。FastAPI、Starlette、Uvicorn、limits、Pydantic 等依各自许可使用，scikit-learn/SciPy/NumPy 及其二进制分发的附带许可完整保留。具体包版本、来源和文件 SHA 记录在项目 reports/stage39/dependency-audit.json。

限流直接调用 alisaifee/limits 5.8.0（MIT），使用 async MemoryStorage + FixedWindowRateLimiter + parse。核心策略与过期/原子计数由上游提供；本项目仅适配路由、会话标识、上限及错误响应。策略 Git blob b6c5023223e217a4fd4c7d2ad398336441c7e06e；许可 blob 2261d327ad9be9232d7d08158db2ccae582b98e6。内存计数只支持单进程，单实例文件锁和固定一 worker 防止误扩容；如需多实例必须先迁移到共享限流和独立数据库。

比较了 laurentS/slowapi（MIT、未归档，middleware blob 76cdeeca4d3e134fb68a9e2be95653ccfc2b12ae）：它同样依赖 limits，但框架路由装饰器/中间件包装不是本轮所需，未复制代码。比较了官方 render-examples/fastapi：未发现仓库许可且最后推送2023，未复制模板源码；render.yaml 根据 Render 官方部署和 Blueprint 文档独立配置。

reuse-receipt.json 记录从项目冻结实现中提取的 Preferences/PersonalModel、SQLite FTS5 BM25、Pydantic 模式和备份解析/合并函数。被选择的方法 AST 不变；只裁去不用的方法并提供精简 import，避免打包训练、CUDA、历史实验和私有数据。检索仍使用 SQLite 原生 BM25，内容向量、归一化和余弦来自 scikit-learn/SciPy；本项目不宣称原创这些算法。

## 数据获取与展示

获取直接复用已固定 lukasschwab/arxiv.py MIT commit 09d1b8bc3c85c6334d480fa94c310c3b729b1d01 的解析和分页/客户端组件，以及本项目已有限速/缓存/原响应收据适配。每次至少间隔3.1秒、单连接、遇429停止；只获取官方 API 的描述性元数据，没有下载 PDF。获取组件不进入线上运行依赖。

数据范围为 162 篇明确 v1 元数据，标题/摘要/提交时间逐项对照原响应。arXiv 官方条款明确允许按 CC0 1.0 储存、转换、共享描述性元数据，且脚注明确包含 abstract：
https://info.arxiv.org/help/api/tou.html

这不是转载 PDF 全文的许可。本项目不托管 PDF 或文章源文件，不代表 arXiv 背书。主题筛选为非独立模型/规则初审，不是人工相关性标签。



## 阶段40：初学者阅读工作台

沿用上述全部组件、26包与许可原文。三个专题的九篇论文均从既有162篇明确v1目录选择，路径顺序、中文提示与问题为本项目编辑整理；每项导读附有经精确包含校验的原摘要片段。不称为自动难度评分、独立真人标签或经验证的学习效果。

GitHub结构参考：huggingface/course（Apache-2.0，章节blob 9294f9af1060cde6f4e018cab34f6ba7bc9054df；许可blob 261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64），recommenders-team/recommenders（MIT，examples/README.md blob c6bb4e123cd42e4fc987a0c25b55055f49f7e2f1；许可blob e74b0d177a471724e4c0c48cae0f4ba9c05df64b）。只借鉴目标、先修、快速开始与深入分层的组织方式，没有复制其课程文字、代码或图片，不新增依赖。

实际复用：原Catalog/BM25/TF-IDF/PersonalModel、偏好与备份、Preact/HTM、主题SVG、Spotlight、高亮、ReadingControls与滚动会话。新增只读路径端点及原生details导读；前端首页入口、文案、布局顺序和模式切换为本项目适配。复制的app.py仅将main入口改为可传factory，以承载新只读路径；路径不参与搜索/推荐排名。相同目录、Cookie与私有卷保留既有偏好。

本版不带付费Blueprint，不代表已经实现免费公网托管。继续优先0元小范围试用，持久存储适配与实际公网验证另行完成。

## 阶段41：MiniOneRec 项目导读

官方仓库 AkaliKong/MiniOneRec，Apache-2.0；固定 commit 526306229326013a7ca46f5b2d8f55ea669aa159（2026-10-19），未归档。本版只阅读源码、链接固定版本并独立整理中文导读；没有把上游训练实现导入、执行或作为本站推荐后端。8份原字节源码/许可研究快照及Git blob在项目 reports/stage41/upstream/MiniOneRec 和 sources.json；保留完整上游LICENSE。不分发其训练权重、Amazon数据或原论文PDF。

比较 sober-clever/ReRe：论文和README作为方法出处，根LICENSE请求404，未假定仓库整体授权，不复制其源码。MiniOneRec已有端到端结构，适合教学导读；现有CPU网页环境不适配其GPU训练依赖，未安装。

TIGER arXiv:2305.05065v1、MiniOneRec arXiv:2510.24431v1、ReRe arXiv:2510.12211v1 的标题/作者/原摘要/公开时间来自官方arXiv API，沿用已核验arxiv.py组件。原始Atom响应随包保存；元数据包括摘要按arXiv API条款CC0使用（https://info.arxiv.org/help/api/tou.html）。仅链接全文，不托管PDF。中文问题、解释、链路图为本项目编辑内容，非作者原文、真人评价或实验结果。专题独立于2025-02历史目录。

实际前端仍复用原Preact/HTM及原生button/details，后端复用FastAPI、现有会话/限流/实例锁；未增加运行依赖。首页/侧栏新增入口，独立专题支持阶段切换和三篇原摘要阅读。

## 阶段43：官方CPU SID诊断

直接复用 AkaliKong/MiniOneRec commit 526306229326013a7ca46f5b2d8f55ea669aa159 的 PRQKMeans、build_indexes/index_statistics，原样源码在项目 third_party/minionerec_sid_cpu，完整Apache-2.0许可证在该目录及web/vendor/LICENSE-minionerec.txt。上游测试test_prq_regressions.py原样执行4项。文件Git blob、路径与使用位置见reports/stage43/upstream.json和test-source.json；不是本项目原创量化算法。

既有scikit-learn TF-IDF/NumPy直接调用，无新增运行依赖。162篇目录/原v1元数据沿用已核验CC0来源；中文诊断说明和实验适配为本项目编写。标题/摘要TF-IDF是教学输入，不是Qwen嵌入复现。打乱算法仅适配严格映射对照，借鉴continuejpg研究的受控设计，不复制其代码。未复制第三方奖励、执行SFT/RL、分发模型权重或训练CSV。访客库/密钥和用户ID不进入网站公开包。


# 阶段55：阅读清单的来源、许可与适配

- 实际复用 Pydantic 2.14.1（MIT）的严格模型、字段及 Literal 校验；现有运行环境和完整许可证保持。复用 sqlite3 原生事务、TrialStore.connect 的容量/超时限制，以及既有 merge_plan 和 v1 备份校验。没有复制或升级上游源码。
- 实际复用现有 Preact 11.1.0（MIT）、HTM 3.1.1（Apache-2.0）、limits 5.8.0（MIT）和原生 select/details/Web Storage。已有 Anime.js、Split.js、React Bits 派生素材及附加条件继续适用，许可原文保留。
- 参考 internetarchive/openlibrary（AGPL-3.0）的 reading_state.py 与 bookshelves.py，把阅读状态和偏好分开。仅学习概念，未复制、移植或安装任何 AGPL 代码，也未引入其服务器依赖。
- 本地新增代码承担访客阅读状态、独立修订、前端控件及 v2 备份适配，不声称原创通用存储、合并算法或校验框架。
- GitHub 来源文件、精确 blob、维护观察、成本和风险比较详见 research.json；原始 arXiv v1 元数据及 CC0 条款不变。


# 阶段56：搜索反馈、对比与笔记复用说明

实际复用现有 SQLite FTS5 MATCH、porter unicode61 索引与 scikit-learn TF-IDF analyzer/稀疏矩阵，显示真实匹配，不重写检索算法或改变排名。复用 Pydantic 2.14.1 MIT 严格校验、现有 merge_plan/v1/v2 解析、sqlite3 原子事务、limits 5.8.0 和访客边界。

前端复用现有 Preact 11.1.0（MIT）、HTM 3.1.1（Apache-2.0）、highlight-words-core 2.0.0（MIT）以及原生 checkbox/dialog/textarea/details。既有 Anime.js、Split.js 和 React Bits 派生组件许可条件不变，原文保留。没有安装新依赖或复制第三方源码。

TanStack/table 的受控行选择示例（MIT）仅作概念参考；三篇上限不引入完整表格框架。Zotero note-editor（COPYING明确AGPLv3）仅研究未保存状态和编辑生命周期，未复制/安装富文本编辑器或其他AGPL源码。SQLite词汇表源码仅用于理解索引/分词语义，不表示本项目调用了fts5vocab。现有Python/sqlite3发行许可证保持。

精确源文件blob、维护观察、适配成本与风险边界见 research.json。arXiv v1 元数据和来源链接保持，网页仍162篇，9000篇仅离线实验。个人笔记由访客输入，不作为原文或模型结论。


STAGE57 RESEARCH LOOP / CURATED SUPPLEMENT
Native Python re and sqlite3 FTS5 trigram/instr, existing sparse TF-IDF transform, Pydantic, Preact/HTM and native dialog/Blob/Web Storage reused. No new runtime dependency, translation model or LLM. jieba (MIT), pyahocorasick (BSD-3-Clause), Argos Translate (MIT) and CommonMark spec (CC-BY-SA4; tools BSD-style) reviewed only, no upstream code/spec text copied. Metadata acquisition reuses pinned arxiv.py (MIT) and official arXiv API; five explicit v1 metadata records, original response retained, metadata CC0 per API terms. See reports/stage57/research.json and topic-review.json for exact sources, exclusions and scope.


STAGE58 CLEAN READING / SCOPED FILTERS / SOURCE COMPARISON
Direct reuse: pylatexenc2.10 (MIT), unmodified source distribution SHA2563dd8fd84eb46dc30bee1e23eaab8d8fb5a7f507347b23e5f38ad9675c84f40d3, private third-party directory. Display adapter preserves unsupported input and math, disables TeX input-file access; never runs TeX or inserts parsed HTML. Native SQLite FTS5 and existing frozen sparse vectors reused; metadata predicates run before LIMIT10 using the same index and original IDF. LaTeX.js MIT and TanStack table MIT reviewed only, no source copied. Five comparison cards quote exact official v1 abstracts under the existing metadata policy, no unverified training requirements filled.

PYLATEXENC LICENSE
The MIT License (MIT)

Copyright (c) 2015-2019 Philippe Faist

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.


v60 (2026-11-08): Restored stage58 original Papertrail visual assets and existing pinned controls. Reused the Scholar/OpenLibrary/OpenAlex information hierarchy research recorded in reports/stage59/research.json only; no external source copying or new dependency. See docs/ORIGINAL_STYLE_V60.md.


v61 online metadata search (2026-11-08): arxiv.py MIT commit09d1b8bc3c85c6334d480fa94c310c3b729b1d01 native Search/Atom parser copied unchanged from previously audited project source; license api-vendor/ARXIV-LICENSE.txt. pyalex MIT invert_abstract copied unchanged from api.py blob7f8e8d4d5524698c2fa8ff4e25ff189aebc046f0; license api-vendor/PYALEX-LICENSE.txt. Requests2.34.2 Apache-2.0, lxml6.1.3 BSD and included bundled-library licenses, certifi2026.10.23 MPL-2.0, charset-normalizer3.5.2 MIT, idna3.20 BSD-3-Clause, urllib3 2.8.0 MIT: distributions with notices in api-vendor, versions/hashes in api-requirements.lock. No Google Scholar source/data copied. Metadata availability does not grant fulltext redistribution. Details: docs/ONLINE_SEARCH_V61.md and reports/stage61/research.json.
