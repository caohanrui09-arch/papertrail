# 专题卡局部彩色与交互反馈

保留 v66 黑白灰背景、卡片尺寸、左大右小布局与阅读入口。仅给三张专题卡的 SVG 增加局部颜色：检索的蓝色文档标识与 ID；冷启动的橙色书签、兴趣符号；评价的蓝紫色柱体。插画继续明确标注为主题示意，不代表实验数值。

沿用现有 Preact/HTM 与已复用的 React Bits SpotlightCard，使用 CSS 图层位移、悬停/按下反馈和键盘焦点；不新增依赖。页面动效开关与系统减少动态效果均取消新增位移，保留可辨认的颜色与焦点。设计借鉴依据见 VISUAL_REFERENCE_REVIEW_2026_11_14.md。

当前入口仍为 http://127.0.0.1:8791/ 。index.html 加载 main-topic-accent.mjs、topics-accent.mjs、topic-accents.css，版本 67.1；旧 main.mjs、topics.mjs、topics.css 和 monochrome.css 保留。后端、访客偏好、目录与算法未修改。reports/stage67/index-before.html 可用于撤回本轮入口引用。

真实桌面验收：独立临时配置的 headless Microsoft Edge，1600×1100，8 项检查通过：页面和三卡背景仍中性、三个专题悬停反馈、键盘焦点、页面动效关闭、系统减少动态效果、实际点击冷启动进入对应三篇阅读路径。截图 topics-rest.png、topics-hover.png 已人工查看。浏览器验收脚本两次因重新连接后视口恢复默认而未命中顶部动效按钮，补充固定桌面视口后通过；不是产品按钮修复。临时浏览器已关闭，工作台服务保留。

验收来源：reports/stage67/browser-validation.json、source-validation.json。未重跑算法实验、未测试手机布局。
