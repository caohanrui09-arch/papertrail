# 主题探索新版

打开 <http://127.0.0.1:8779/>，向下阅读“换一条线索，发现新方向”。项目内双击 `papertrail-gallery.cmd`，或从任意PowerShell目录运行：

```powershell
& '<repo>\papertrail-gallery.cmd' start
```

支持`status`、`stop`、`start --no-open`。只监听本机，8778旧版继续可用。新版沿用原搜索、原摘要、收藏、不感兴趣、推荐和备份API及可变偏好库；同一浏览器、同一主机名下已有偏好继续可见。

主题区改为一主两副的网格：生成式检索为深色大卡，右侧为推荐冷启动与曝光评价。三张卡都是可聚焦按钮，Tab切换、Enter进入对应真实搜索；图形仅作主题示意，不代表真实论文关系或实验指标。深浅配色、字号、图形体积和行动入口分出主次。

卡片光效直接适配React Bits SpotlightCard，保留许可与来源。页面右上“关闭页面动效”同时停用新光效；静态布局仍完整。系统减少动效规则保留，不提供自动循环的背景动画。手机布局仍沿用已有规则，本轮未重新设计或验收。

前后实机截图见data/stage37-ui，研究取舍见reports/stage37/design-study.json。外部演示页控制超时，已查看可获取的官方预览图和源码；不声称播放验证五个网站全部动效。没有使用付费模板、外部字体或远程图片作为网站运行依赖。

复核已封存交付：

```powershell
.\.cache\stage17\runtime\Scripts\python.exe -E -s -m scripts.verify_gallery_delivery
```
