# 工作台空间与紧凑卡片 v53
交付：2026-11-05。当前网页仍为162篇主题试用目录，9000篇SFT结论及默认算法沿用v52。

## 打开与启动
工作台：http://127.0.0.1:8791/ 。当前已启动，可刷新后使用。
最新工作台入口：双击项目根目录papertrail-workbench.cmd。PowerShell可从任意目录执行：

    & '<repo>\papertrail-workbench.cmd'
    & '<repo>\papertrail-workbench.cmd' status
    & '<repo>\papertrail-workbench.cmd' stop

papertrail.cmd继续保留为v52历史入口，与新版共用8791及真实偏好卷，不能并行启动。日常使用新入口即可；要回退，先停止新版，再启动旧入口。新入口是后续可更新的当前版本指针，历史启动快照保存于reports/stage53/launcher-snapshot.cmd。

## 本轮改变
- 顶部搜索、个人偏好和操作提示收紧；“已收藏/撤销”等提示移到标题栏，反馈后不额外压缩列表高度。
- 默认候选列表42%、阅读器58%。拖动中间手柄调整；聚焦手柄后左右键每次2个百分点，Shift加方向键5个百分点，Home/End到边界，Enter或双击恢复默认。
- 只记忆本地分栏比例，不新增查询/阅读历史存储。窗口变化重新按最小面板尺寸约束。
- 卡片标题最多两行、原摘要预览两行。完整标题可悬停查看，点击标题/读摘要会在右侧显示完整标题和原摘要。
- 收藏、不感兴趣、读摘要位于同一操作行；当前卡片有明确在读状态。保留原ID/v1，去掉卡片中重复出现的版本字符串。
- 阅读器上方固定上下篇及收藏操作；滚动摘要不会把它们带走。专注阅读收起候选列表并展开阅读器；退出后恢复原分栏。
- 修改过的入口、样式和模块使用v53.1资源标识，避免同地址升级后沿用旧浏览器模块。

## 同屏验收
1280×720，相同generative retrieval查询、相同10个候选与第一篇原摘要；主站仅只读，收藏操作在localhost:8793独立访客目录完成。

|指标|v52|v53|
|---|---:|---:|
|完整可见候选|1|2|
|首卡高度|约350px|约199px|
|候选滚动区高度|约389px|约451px|
|阅读器宽度|约524px|约586px|
|工作区起始位置|约256px|约200px|

这是固定窗口和查询的布局结果，不外推所有论文标题或窗口尺寸；没有搜索相关性或推荐质量提升的实验主张。
专注阅读实测宽1020px；分栏最小阅读区约361px时按钮可达、页面无横向溢出。实际鼠标拖动42→40键盘→37拖动、刷新后37、Enter恢复42；上下篇及原摘要滚动后的固定操作均验证。
截图与读DOM尺寸见reports/stage53/before.png、after.png、before-layout.json、after-layout.json。

## 回归与边界
- 复用68项隔离ASGI回归；24组原搜索/读取返回逐值相同，备份、版本、来源与证据下载保持。
- 真实收藏、会话和修订的聚合指纹切换前后核对；不输出用户明细或密钥。
- 没有改动排序、训练、目录、实验报告或用户反馈语义；手机布局、跨页面恢复阅读、侧栏重组不在本轮。
- 验收模块scripts.run_workbench_acceptance使用http://localhost:8793和.cache/stage53/ui-visitors；与127.0.0.1主站区分Cookie主机名。临时验收服务结束后停止。
- 新增本地vendored Split.js1.6.5（MIT），不新增Python包、不安装React或构建工具。源文件及许可见web/vendor/split.mjs、SPLIT_LICENSE，选型见reports/stage53/research.json及THIRD_PARTY_NOTICES.md。

复核（项目根目录）：

    .cache/stage39/runtime-secure/Scripts/python.exe -E -s -m scripts.validate_workbench_delivery
    .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.verify_workbench_delivery

第一条只写临时验收目录；第二条验证冻结历史与本阶段源码/证据。实际站点是本机服务，没有公开分享链接或线上负载验证。
