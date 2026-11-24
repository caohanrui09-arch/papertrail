# Papertrail v58：清洁阅读与论文整理

交付日期：2026-11-08（香港时间）。当前入口仍为 http://127.0.0.1:8791/ 。

## 四项改进

**清洁阅读。** 原摘要的排版指令如`\textbf{FAST}`和转义百分号整理为普通文本，默认阅读更流畅。右侧“原始文本”可切回精确原文；显示模式、所选论文和查询可恢复。公式保留TeX文本，未知指令或解析失败时整段回退原文并提示。清洁内容不是翻译或模型摘要，不修改原始API响应、检索索引、版本、来源或笔记。

**专题与年份检索。** 首页及侧栏“多模态快慢思考”入口现在只搜该专题5篇。展开“范围与年份”选择收录主题和arXiv首次提交年份；例如2026年返回2篇。范围说明提供“扩大到全部目录”，会同时清除年份限制。条件在取前十之前生效，不是在原前十里删结果。BM25继续使用同一FTS5索引、porter分词、0/2/1字段权重和原IDF；TF-IDF继续使用原词表和矩阵。候选内合成上下文排序也不能把范围外论文带回。

范围包括：全部167、历史核心162、多模态快慢思考5、生成式检索52、推荐冷启动75、曝光与评价29、未分组6。收录主题来自既有`discovery_topics`与已审查专题ID，允许重叠；这些数量不能相加当作目录总量，也不是独立人工相关性标签。原请求不传新条件时仍默认历史核心，20个旧只读响应保持一致；另4处为目录元数据和导读key的已有更新。

**带原文依据的比较。** 选择2–3篇后打开对比，每篇可展开“研究方法对比·摘要依据”，查看“控制什么、如何选择快慢、是否需要训练”。阅读器中也提供相同入口。每项已填内容都有对应v1摘要的精确原句和版本链接。5篇均完成结构化摘要整理；FAST、FOCUS、L2T的训练要求留空，因为目前来源不足以明确确认。DualMindVLM摘要明确写用GRPO训练，TempoMoE明确写training-free。没有用“未核实”推断“不需要”，也没有把作者实验结果当作本站复现结果。

**收藏整理。** “我的收藏”可按收录主题、年份、阅读状态组合筛选，并显示已展示/总收藏数。无结果时提示“当前条件没有匹配的收藏”；清除筛选恢复完整清单，不移除收藏、不改变偏好画像或推荐算法。状态仍由你手动标记。筛选条件在刷新后恢复，旧浏览器阅读位置缺少新字段时使用兼容默认值。

## 来源和复用

实际复用pylatexenc2.10（MIT）纯Python源码，发行包SHA256：

`3dd8fd84eb46dc30bee1e23eaab8d8fb5a7f507347b23e5f38ad9675c84f40d3`

18个原始源码/许可文件隔离保存在新版本`third-party`，未执行setup、未修改上游源码、未改共享Python环境。项目适配器只限制输入/文件读取并组织显示；不执行TeX或解释HTML。2.10是固定稳定版本，未宣传成最新主分支。已交叉阅读LaTeX.js和TanStack筛选示例；前者整页HTML渲染成本过大，后者数据表框架不适合现有论文卡片，均未安装或复制。SQL评分和稀疏向量沿用成熟已有组件，新增代码只添加范围谓词与状态适配。详情见`reports/stage58/research.json`、`vendor.json`及许可清单。

比较材料仅使用已有官方v1摘要，无新抓取、无训练或RL；精确原句在启动时核对。摘要证据有限，不能等同于完整论文评审。保持167篇目录、原9000篇离线实验与所有冻结结果。新页面没有真人相关性标签，不宣称检索质量、CTR或生产吞吐提升。

## 启动与验收

从任意目录在PowerShell运行：

```powershell
& '<repo>\papertrail-workbench.cmd' start
```

启动器进入项目目录，当前指向`research58_control`。`status`查看、`stop`停止自己拥有的本机服务。旧v57资产原样保留；v58与v57使用相同目录标识和现有访客数据库，未新增存储命名空间或重置凭据。

在项目根目录执行：

```powershell
.\.cache\stage39\runtime-secure\Scripts\python.exe -E -s -m scripts.validate_research58_features
.\.cache\stage39\runtime-secure\Scripts\python.exe -E -s -m scripts.validate_research58_delivery
.\.cache\stage39\runtime-secure\Scripts\python.exe -E -s -m scripts.validate_research58
.\.cache\stage39\runtime-secure\Scripts\python.exe -E -s -m scripts.validate_research58_tools
.\.cache\stage39\runtime-secure\Scripts\python.exe -E -s -m scripts.validate_research58_loop
.\.cache\stage39\runtime-secure\Scripts\python.exe -E -s -m scripts.validate_research58_migration
node scripts/validate_research58_memory.mjs
.\.cache\stage17\runtime\Scripts\python.exe -E -s -m scripts.verify_research58_delivery
```

隔离接口检查覆盖转换/回退/来源哈希、过滤先于截断、原排序参照、空范围、非法年份、合成排序范围保持、需求诊断与报告条件。原有收藏、阅读、笔记、CAS和v3备份回归保留。浏览器使用localhost:8798及隔离访客文件进行收藏/状态写入；正式8791只验证读取与本机位置更新。切换时对2个实际数据库全部已有表和session.key核对指纹，保持原值。真实用户的Cookie不导出到报告。

桌面1280×720仍可见2篇完整候选，阅读器585.59px；三栏摘要分别约211.35/203.76/211.35px，来源与返回按钮固定可达。浏览器实测筛选交集、空状态、清除后收藏保留、刷新恢复、原文模式恢复与规范来源。截图和收据在`reports/stage58`。

这轮未验证手机/窄栏、公网TLS、多机复现、多人负载或原生下载事件。已有JSON备份和Markdown报告继续可用，不把清洁摘要覆盖进原始材料。
