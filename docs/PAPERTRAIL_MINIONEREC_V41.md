# MiniOneRec 生成式推荐专题

本地入口：[MiniOneRec 导读](http://127.0.0.1:8787/minionerec.html)。首页与侧栏都有入口。

从任何目录启动均可：

```powershell
& '<repo>\papertrail-minionerec.cmd'
```

状态与停止：在项目目录执行 `./papertrail-minionerec.cmd status` 或 `./papertrail-minionerec.cmd stop`。复用已隔离的 Python3.12.16 / 26包环境，不必安装上游 GPU 依赖。沿用 `data/stage39-visitors` 的私有数据和 Cookie；旧 v40 已停止以遵守共享卷单实例锁。不要同时启动旧试用服务。

## 读什么、怎么用

1. 选择 SID、SFT 或 RL 卡片，查看该阶段的输入、输出、解释和固定版本源码。
2. 展开自检问题：SID 碰撞、哪些参数被训练、CC 的扫描边界。
3. 在三篇论文间切换：TIGER → MiniOneRec → ReRe；中文问题为编辑导读，英文为完整原摘要。选择阶段也会切换到对应论文，可以再独立选文。
4. 打开明确 v1 的 arXiv 页面或全文链接。本站不托管 PDF，也不把摘要中的作者实验结论写成本站结果。
5. 通过“返回阅读空间”继续原有 162 篇目录的搜索、收藏、内容推荐和备份。

## 内容与时间边界

这次加入的是学习内容。没有训练、加载或在线运行 MiniOneRec；当前推荐依然是实际收藏驱动的内容推荐。专题三篇独立资料不参与搜索排名、推荐、收藏、备份或既有评测。

主目录截止于2025-02-23；MiniOneRec与ReRe首次公开于2025年10月，因此不能直接并入旧实验目录。专题整理日期2026-11-02、官方源码固定于2026-10-19的 commit `526306229326013a7ca46f5b2d8f55ea669aa159`。论文使用明确v1，而源码为更晚的固定快照，两者不能视作同一个历史版本。

## 来源和复核

- [MiniOneRec 官方仓库固定版本](https://github.com/AkaliKong/MiniOneRec/tree/526306229326013a7ca46f5b2d8f55ea669aa159)：Apache-2.0，源码只作研究与链接，不作为本网站训练后端。
- [TIGER v1](https://arxiv.org/abs/2305.05065v1)、[MiniOneRec v1](https://arxiv.org/abs/2510.24431v1)、[ReRe v1](https://arxiv.org/abs/2510.12211v1)：官方API的原摘要、标题、作者、公开日期，按arXiv CC0元数据条款使用；原始响应及哈希保留。
- 比较了ReRe官方仓库，根LICENSE请求404，不假定整体代码授权，不复制其源码。
- 实际复用既有 arxiv.py、FastAPI、Preact/HTM、会话和限流、搜索与内容推荐；无新增运行依赖。

`reports/stage41/sources.json` 记录8份官方文件的Git blob；`papers.json` 保存获取凭据；`deploy/stage41/project-original.atom` 是对应原始API响应。启动时精确核验原摘要、标题、v1身份与时间及导读片段。

隔离接口检查：

```powershell
./.cache/stage39/runtime-secure/Scripts/python.exe -E -s -m scripts.validate_minionerec --baseline
./.cache/stage39/runtime-secure/Scripts/python.exe -E -s -m scripts.validate_minionerec
```

这些命令仅写项目临时空间；受限Windows沙箱的临时目录ACL可能需要宿主允许执行。57项检查、24组旧响应比对与真实浏览器记录见 `reports/stage41`。专题浏览器测试没有修改访客偏好。尚未进行移动端验收、MiniOneRec训练、真人学习效果评价或公网免费部署。
