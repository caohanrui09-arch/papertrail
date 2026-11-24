# 阅读清单 v55（2026-11-05）

本轮交付“找到 → 待读 → 阅读 → 回顾”。当前网页仍为162篇真实v1目录；9000篇仍仅为离线SID实验。

## 使用

1. 在搜索结果或阅读器固定操作栏点击“＋ 待读”。
2. 使用状态菜单切换“待读／在读／已读”，或“移出清单”。打开摘要不会自动标为在读或已读。
3. 侧栏“阅读清单”查看全部、待读、在读、已读；侧栏数字是清单总篇数。按最后一次实际状态修改时间倒序，同时间按ID确定次序。
4. 最近一次阅读状态修改可撤销；状态切换不改变收藏、推荐画像或不感兴趣标记。重置偏好同样保留阅读清单。
5. 刷新、切换工作模式或从证据页返回，恢复对应清单筛选、选中论文及面板位置；返回重新请求真实数据，失去筛选资格的论文不继续显示为选中。

## 备份与恢复

“清单与备份”或清单工具栏“备份清单”导出v2 JSON，包含偏好和显式阅读状态。不含访客Cookie、查询、滚动位置、原始摘要或阅读时间；导入后按导入时的状态更新时间排序。

先预览后确认，分别显示两类记录的新增、冲突和保留情况。默认保留当前冲突，也可选使用备份；不在文件中的当前记录始终保留。v1收藏备份继续可导入，经原校验支持旧42篇目录；v1不修改阅读状态。v2须匹配当前目录，所有论文ID/v1/标题/来源都须一致。

两类修改在一个SQLite事务内提交；任何非法项目都不部分写入。预览绑定访客、文件原文、策略、目录及两类修订号；任一类发生变化需要重新预览。单文件256KiB，偏好和阅读状态分别最多500项，现目录只有162篇。

## 保存与隐私

阅读状态保存在现有服务器访客空间，沿用随机HttpOnly Cookie、同源限制和请求预算；匿名空间不是账号。清除Cookie后应通过备份恢复。阅读位置另存本机浏览器；“清除阅读位置”不会清空阅读清单。当前继续仅本机运行，未新增公网分享或第二台机器验证。

新增 reading_status / reading_revisions 两表，不删除或重建旧表。独立修订让阅读状态操作不触发推荐重算；旧偏好API/v1路径仍保留。旧版本不知道新表，旧版偏好操作也不会级联删除阅读记录。

## 启动及复核

在资源管理器运行项目根目录 papertrail-workbench.cmd，或在PowerShell使用完整路径：

```powershell
& '<repo>\papertrail-workbench.cmd' start
```

网站：http://127.0.0.1:8791/ 。入口是当前版本指针，历史v54文件保持不变。

在项目根目录：

```powershell
.cache/stage39/runtime-secure/Scripts/python.exe -E -s -m scripts.validate_reading55_delivery
.cache/stage39/runtime-secure/Scripts/python.exe -E -s -m scripts.validate_reading55
node scripts/validate_reading55_memory.mjs
.cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.verify_reading55_delivery
```

测试使用临时数据库，浏览器验收在localhost:8795专用访客目录完成；不要把临时站作为日常入口。原生下载器本轮不重复自动化，导出API内容/响应头及网页下载链接已核验；粘贴导入在浏览器实测。1280×720桌面仍保留2篇完整候选、约586px阅读器；手机和嵌入窄栏布局继续留待后续。

## 交付证据

- reports/stage55/reading-validation.json：72项，升级/隔离/显式状态/并发修订/原子导入/旧42篇备份/限流。
- reports/stage55/api-validation.json：68项旧功能，24组原返回精确一致。
- reports/stage55/memory-validation.json：20项本机存储边界及清单筛选兼容。
- reports/stage55/browser-validation.json：状态流、撤销、备份、刷新与跨页面恢复、桌面布局。
- reports/stage55/preference-preservation.json：真实旧偏好和会话密钥合并指纹保持，仅增加空阅读表。
- reports/stage55/research.json、THIRD_PARTY_NOTICES.md：GitHub比较、实际复用与许可。
- reports/stage55/final-validation.json：当前交付文件SHA256及历史链复核。

没有训练、改搜索/推荐公式、改目录、添加依赖、真人评价或质量提升声明。
