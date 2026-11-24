# 个人兴趣版 v35

前端直接复用v34的Preact 11.1.0 MIT、HTM 3.1.1 Apache-2.0、Anime.js 4.5.0 MIT与全部原许可，vendor逐字节一致；不安装新组件。

后端实际调用既有gsearch.visitor_profile.Preferences/PreferenceConflict/PersonalModel与原SearchV2，使用已有scikit-learn TF-IDF、normalize、linear_kernel（BSD-3-Clause）及SQLite，不重写排序或存储事务引擎。新版V2Catalog只提供42篇目录与既有文本矩阵接口，现有万篇数据和模型不改。

新调研比较scikit-learn与implicit（MIT），读取公开许可、维护状态和相关文档/核心代码。未安装或复制implicit；不把GitHub可读等同所有候选仓库已获复用授权。详细来源和许可blob见reports/stage35/open-source-reuse.json。原根THIRD_PARTY_NOTICES仍保持封存。

新适配包含目录/版本/修订校验、浏览器偏好空间、可撤销单项操作、重置确认和计算结果呈现。词项/收藏贡献由原PersonalModel计算，不声称原创推荐算法、真实相关性提升或独立真人评价。

## 阶段36：备份入口与本机协议适配
沿用阶段35原样vendor及许可。没有新增第三方代码、包或执行外部书签服务。
GitHub调研仅参考Linkwarden AGPL-3.0迁移入口及Linkding MIT导入/导出实现；不复制其源码，不宣称原创导入框架。来源与固定源码blob记录reports/stage36/open-source-reuse.json。
实际复用Python json/sqlite3/hmac/hashlib、已安装FastAPI/Pydantic，以及项目原Preferences连接和snapshot。新增协议/预览/事务合并为本项目适配代码。

## 阶段37：主题探索视觉重构
React Bits SpotlightCard Copyright (c) 2026 David Haz，MIT + Commons Clause（并非不受限制的MIT）。本应用实际复用其指针／键盘焦点光效、缓动及清理逻辑，原JSX/CSS快照位于reference/，按Git blob核验；应用适配为dist/spotlight.mjs和spotlight.css。完整许可随dist/vendor/REACT_BITS_LICENSE.md提供。修改：React→已有Preact/HTM，CSS单独加载，新增disabled及清理归零，grain=0时不放入data URL。组件随论文应用使用，不作为独立组件、移植组件包或模板商品分发。
既有Anime.js 4.5.0 MIT、Preact 11.1.0 MIT及HTM 3.1.1 Apache2.0保持原样。
Aceternity UI注册表仅用于研究主次网格和布局，不复制Pro资产或不明授权组件；MotionSites官方预览仅供本地研究，不加入应用；Uiverse MIT卡片源码仅参考分层与边缘处理，没有复制持续循环blob动效。
主题SVG插画和卡片布局由本项目制作，是装饰示意，不代表真实论文关系、曝光数据或算法收益。来源见reports/stage37/design-study.json。
