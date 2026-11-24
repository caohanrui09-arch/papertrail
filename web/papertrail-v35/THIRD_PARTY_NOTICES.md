# 个人兴趣版 v35

前端直接复用v34的Preact 11.1.0 MIT、HTM 3.1.1 Apache-2.0、Anime.js 4.5.0 MIT与全部原许可，vendor逐字节一致；不安装新组件。

后端实际调用既有gsearch.visitor_profile.Preferences/PreferenceConflict/PersonalModel与原SearchV2，使用已有scikit-learn TF-IDF、normalize、linear_kernel（BSD-3-Clause）及SQLite，不重写排序或存储事务引擎。新版V2Catalog只提供42篇目录与既有文本矩阵接口，现有万篇数据和模型不改。

新调研比较scikit-learn与implicit（MIT），读取公开许可、维护状态和相关文档/核心代码。未安装或复制implicit；不把GitHub可读等同所有候选仓库已获复用授权。详细来源和许可blob见reports/stage35/open-source-reuse.json。原根THIRD_PARTY_NOTICES仍保持封存。

新适配包含目录/版本/修订校验、浏览器偏好空间、可撤销单项操作、重置确认和计算结果呈现。词项/收藏贡献由原PersonalModel计算，不声称原创推荐算法、真实相关性提升或独立真人评价。
