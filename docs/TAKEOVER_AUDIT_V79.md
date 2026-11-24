# Papertrail 接手审计 · 阶段79

日期：2026-11-22。

> 说明：本项目由站主本人长期开发。本文的"接手"指**在新的工作目录迁移并验收同一份项目**，阶段78 的交接包是为分享给朋友准备的快照，不是他人代码。文件名沿用当时的记录名。

本轮只做三件事：核对实际收到的资产、真实运行 Windows 演示站、把真实 Agent 运行时恢复到新的开发根目录并实测。新增模型运行 2 次（1 成功 1 失败，均保留），未训练、未扩目录、未改算法或默认推荐。

## 一、交接包核对

| 项目 | 交接记录 | 本机实测 | 结论 |
|---|---|---|---|
| Papertrail-Windows-Preview.zip | 77,867,318 字节 / 6,201 文件 / sha256 `21ec205e…6207` | 字节数、文件数、sha256 全部相同 | 一致 |
| Papertrail-Source-Handoff.zip | 4,889,853 字节 / 1,351 文件 / sha256 `1f19ebd6…cb69` | 字节数、文件数、sha256 全部相同 | 一致 |
| 解压结果 | 记录未给解压路径 | 演示包 6,202 项 / 221.4 MiB；源码包 1,352 文件 / 13.6 MiB | 可用 |
| 私有资产排除声明 | 不含 data/、.cache/、runs/、访客库、密钥、权重 | 解压后确认不含上述目录 | 一致 |

解压根目录：本机 `…\default-workspace\papertrail\`，演示包在 `preview\`，源码在 `source\`（也是本轮起的开发根目录）。

## 二、本机资源

| 资源 | 实测值 | 对项目的影响 |
|---|---|---|
| CPU | Intel 32 逻辑处理器 | 足够，CPU 拟合约 50 秒 |
| 内存 | 可用约 15.6 GB | 足够（模型峰值约 4–5 GB） |
| GPU | NVIDIA RTX 4060 Laptop，8188 MiB，驱动 560.94 | Qwen2.5-1.5B 可运行，实测 CUDA 12.4 可用 |
| 磁盘 | C: 75.2 GB 空闲 / D: 312 GB 空闲 | 研究运行时约 6.3 GB，充足 |
| Python | 系统 3.12.3（D:\miniconda3）、3.13.0；演示包自带独立 3.12 | 研究运行时用项目自带托管 CPython 3.12.3 |

## 三、现有文件与验收

| 资产 | 路径 | 体量 | 验收情况 |
|---|---|---|---|
| 可运行演示站 | `preview\`（自带 runtime/python + runtime/deps） | 221.4 MiB | **通过 15/15**：首页与全部首屏资源 200、167 篇目录、BM25 检索返回论文、明确 v1 原摘要、收藏、内容推荐已排除已读、导出备份含收藏、空查询 422、不存在论文 422、跨域写入 403、第二访客隔离、Agent 入口如实说明未执行模型 |
| 演示站访客数据 | `preview\visitor-data\`（运行时新建） | 运行时生成 | 与源码包分离；不含发送方访客库或密钥 |
| 源码包 | `source\` | 1,352 文件 / 13.6 MiB | 代码、文档、许可齐全；含 research77 展示层与 research63–76 算法/Agent |
| 冻结研究副本 | `source\.cache\stage17\replica\` | 1,935 文件 / 143 MiB | **bundle-manifest 481 个文件逐一校验通过（8.07 秒）** |
| 万篇目录模型 | 同上（replica/data） | — | **加载成功：10,000 篇**，模型签名与冻结记录一致（49.63 秒） |
| 本地模型权重 | `source\.cache\models\Qwen2.5-1.5B-Instruct\` | 8 文件 / 2.96 GiB | 可加载，`local_files_only` |
| CPU 研究环境 | `source\.cache\stage17\runtime\` + `python\` | 36,000+ 文件 / 1.63 GiB | 复制后重写 `pyvenv.cfg` 并 `venv --upgrade`，base 指向新副本，sklearn 1.9.1 / numpy 2.5.4 可用 |
| GPU Agent 环境 | `source\.cache\stage6-env\` | 11,765 文件 / 0.29 GiB | 借共享 CUDA 环境（见缺失表），torch 2.6.0+cu124、cuda True |
| 任务与保留样例 | `source\data\stage19-unified`、`stage64-http` | 62 + 7 文件 / 2.4 MiB | `/lab/presets` 3 个任务、`/lab/examples` 可读 |
| 历史报告 | `source\reports\` | 1,245 文件 | `/lab/quality` 读取 stage15 dev JSON 正常 |

## 四、缺失资产与恢复方法

| 缺失项 | 为什么缺 | 恢复方法（本轮已实际执行 / 待办） | 预计资源 |
|---|---|---|---|
| 冻结研究副本 | 交接规则不分发 data/ | 已从本机原工作区复制并校验 481 文件 | 143 MiB / 8 秒 |
| Qwen2.5-1.5B-Instruct | 权重不随包分发 | 已复制 2.96 GiB 权重目录 | 2.96 GiB |
| CPU 隔离环境 | venv 含发送方绝对路径 | 已复制托管 CPython 3.12.3 + runtime，重写 pyvenv 并用 `-m venv --upgrade` 重建启动器；全新机器应按 `reports/stage17/requirements-win-cpu.lock` 重建 | 1.63 GiB / 重建需联网 |
| GPU Agent 环境 | 与共享 CUDA 环境耦合 | 已复制 stage6-env；其 `shared_workspace_runtime.pth` 指向父目录共享 `.venv`（4.7 GiB）。本轮依赖该共享环境，属外部依赖，必须记录 | 0.29 GiB + 4.7 GiB 共享 |
| 训练画像与历史交互 | CC BY-NC-ND 4.0，不随源码分发 | 本机原工作区已有，仅本地非商业使用；新机器须从原合法来源独立获取重建 | data 约 1.2 GiB |
| runs/ 旧训练检查点 | 网站与 Agent 均不需要 | 未复制；继续旧训练研究时另核对上游许可 | 12.55 GiB（不需要） |
| 访客库与 session.key | 隐私，交接有意排除 | 不复制；演示站在 `preview\visitor-data` 新建独立空间 | — |
| 第二台机器 / 公网 | 从未验证 | 本轮仍未做；不声称第二台机器成功 | — |

## 五、真实 Agent 实测（8802，新开发根目录）

启动：`source` 下 `research77.server`，`/health` 返回 `status=ready`、`candidates=10000`、工具 `search_papers/recommend_papers/read_paper`、`retrieval=sqlite_fts5_bm25`、`default_recommendation=content`、`llm_in_service=false`（模型只在 worker 子进程加载）。

| 检查 | 结果 |
|---|---|
| `/lab/presets` | 3 个任务 evaluation-000/001/002，catalog 10000 |
| `/lab/algorithms`（evaluation-002） | 5 方法 popular/sar/content/hybrid/cold_aware 均返回原生 Top10 |
| `/lab/quality` | 历史 dev 描述性指标可读（明确标注不是本轮质量） |
| 固定流程作业（evaluation-002, fixed） | 4.5 秒完成，`complete=true`，0 模型调用 |
| 约束 Agent（evaluation-000, constrained） | **协议完成**：6.1 秒、3 次模型调用、4,910/112 token、1 条引用含逐字原摘要与版本链接 |
| 约束 Agent（evaluation-002, constrained） | **协议未完成**：60.3 秒、8 次模型调用、20,388/421 token，预算耗尽后工具被移除，`AgentMaxStepsError`，无答案。全部轨迹保留 |

两条约束运行合计 11 次模型调用、约 25,300 输入 token。第一条失败是状态约束按设计生效的结果（检索/读取预算用尽后不再注册工具），不是环境故障；第二条成功引用 `arxiv:2112.07945v1` 的原文摘录，`source_verified=true`、`retrieved_by=search_papers`。

## 六、边界与未完成

- 桌面浏览器截图/点击未在本环境完成：headless Edge 无法创建 mojo 通道（沙箱拒绝），本轮以真实 HTTP 端到端为准，不冒充视觉验收。演示站与实验台的 `/` 页面均返回 200 且资源齐全。
- 真实 Agent 恢复只在本机同一台机器、新路径下验证，不构成第二台机器复现。
- 未训练、未扩目录、未改推荐默认、未写发送方访客偏好；阶段73「固定4/4、原LLM0/4、约束3/4」与真人相关性 0 的原记录不变。
- 本轮新增模型运行 2 次（1 成功 1 失败），已单独记录，不与历史 53 次调用混合统计。

证据：`reports/stage79/validation.json`、`reports/stage79/preview-acceptance.json`、`reports/stage79/agent-runs.json`。
