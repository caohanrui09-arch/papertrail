# 能不能上 GitHub · 发布就绪审计（阶段86）

日期：2026-11-24。只读审计，未改动任何文件。

## 结论

**代码可以发，但现在这棵树不能整棵 push。** 有 3 个硬阻塞、2 个建议；修完大约 1–2 小时可以开一个干净的公开仓库。

## 审计数字（排除 data/、.cache/、runs/ 之后的"可发布树"）

| 项 | 值 |
|---|---|
| 文件数 / 体积 | 2,593 个 / 87.5 MB |
| 其中 `reports/` | 70.6 MB（占 81%）→ 主要是原始预测 JSON 与截图 |
| 代码本身 | `.py` 5.7 MB、`.js/.mjs` 3.0 MB、`.css` 0.7 MB |
| 密钥/证书/数据库文件 | **0 个**（无 `.key`/`.db`/`.pem`，无 HF/OpenAI/AWS token） |
| `<home>` 绝对路径 | 84 行，分布在约 30 份文档 |
| LICENSE | **没有**（只有 `THIRD_PARTY_NOTICES.md`） |
| `.git` | 不存在（全新初始化，不会带出旧历史） |
| `.gitignore` 现状 | 只有 `.cache/ data/ runs/ __pycache__/ *.pyc .venv/` |

## 硬阻塞

### B1 私有派生数据会一起被推上去

- `reports/**/raw_predictions.json`（共 7 份、27.0 MB）与 `reports/stage7/full-index.json` 是**逐事件预测/索引**，属于用户级衍生数据。
- `data/`（1.2 GB）含训练画像、访客库、`session.key`；`.cache/`（8.0 GB）含模型权重。
- 许可约束：万篇目录与训练画像来自 Scholar Inbox，**CC BY-NC-ND 4.0，不可再分发**；用户级预测属衍生数据。
- 处理：`reports/` 只保留聚合收据与少量截图；`raw_predictions`、`data/`、`.cache/`、`runs/` 全部排除。

### B2 没有 LICENSE，README 已过期

- README 仍写 8767 端口，并用 `<home>\...` 绝对路径启动。
- 需要：选一个许可（个人项目建议 **MIT**，想显式专利授权就 **Apache-2.0**），并重写 README。

### B3 绝对路径泄露本机目录

- 84 行 `<home>\...`，集中在 docs 与 `.cmd`。
- 泄露用户名、且 clone 后完全跑不通；需要统一改成"从项目根目录运行"或相对路径。

## 建议

- **S1 个人文档不要进公开仓库**：`RESUME*.md`、`INTERVIEW*.md`、`RESUME_TRACK_*.md`、`GLOSSARY_V85.md` 共 9 份，是你自己的求职材料。
- **S2 截图瘦身**：`reports/` 下 94 张 PNG 共 9.4 MB；建议只留 `docs/screenshots/` 下 5–8 张（首页、时间线、失败原因、证据页），其余不进仓库。

## 可发布的最小集

保留：`research63`–`research77`、`deploy/stage66`（自带 `catalog/` 1.29 MB + `supplement/`）、`gsearch`、`scripts`、`tests`、`third_party`、`web`、`handoff`、`docs`（去个人文档）、`*.cmd`、`requirements*`、`THIRD_PARTY_NOTICES.md`、`LICENSE`、`README.md`。

实测体积：**12.9 MB / 1,316 个文件**（去掉 reports 与个人文档后）；若再保留少量聚合收据与截图，约 15 MB。

## clone 之后能跑什么、不能跑什么

| 能力 | 能否从公开仓库直接跑 | 说明 |
|---|---|---|
| 167 篇论文阅读站（搜索/收藏/推荐/原摘要/备份） | ✅ 能 | `deploy/stage66/catalog` 自带，按 `requirements.lock` 装依赖即可 |
| 万篇真实 Agent 实验台（8802） | ❌ 不能 | 需要 `data/`（CC BY-NC-ND）与 Qwen 权重（不发布）；README 必须写清 |

这一点很关键：**公开仓库要诚实写"研究模式需要自备资产"**，否则别人 clone 下来跑不起来会开 issue。

## 发布步骤清单

1. 新建 `.gitignore`（建议内容见下）。
2. 加 `LICENSE`（MIT 或 Apache-2.0），保留 `THIRD_PARTY_NOTICES.md`。
3. 重写 `README.md`：一句话定位 → 截图 → 30 秒跑起来（8791）→ 研究模式说明（需自备资产）→ 目录结构 → 许可与免责声明。
4. 清洗 84 处绝对路径：`grep -rn "C:\\\\Users" docs *.cmd` 后逐条改。
5. 预检：`git add -A --dry-run` 输出里**不得出现** `data/`、`.cache/`、`reports/**/raw_predictions*`、`*.sqlite3`、`session.key`、`RESUME*`。
6. `git init && git add -A && git commit -m "Papertrail: paper reading site + auditable agent lab"`。
7. Windows 演示包（77 MB zip）走 **GitHub Release**，不进 git 历史。
8. 仓库描述写清："local demo, not a hosted service"。

建议的 `.gitignore` 追加项：

```gitignore
# data and research assets (licence + privacy)
.cache/
data/
runs/
visitor-data/
*.sqlite3
*.db
session.key

# raw derived research artefacts (not redistributable)
reports/**/raw_predictions*.json
reports/**/full-index.json
reports/stage73-evaluation/agent-runs/
reports/stage7*/
reports/verifier-*/

# personal career material
docs/RESUME*.md
docs/INTERVIEW*.md
docs/GLOSSARY_V85.md

# local noise
*.log
__pycache__/
*.pyc
.venv/
.DS_Store
```

## 许可核对清单（发布前逐项确认）

| 资产 | 许可 | 能否随仓库发布 |
|---|---|---|
| 167 篇目录元数据与原摘要（arXiv） | arXiv 元数据/摘要属 CC0 元数据 | 可以，保留来源与 `THIRD_PARTY_NOTICES` |
| 万篇目录、训练画像、历史交互 | Scholar Inbox，CC BY-NC-ND 4.0 | **不可以** |
| Qwen2.5-0.5B / 1.5B 权重 | Apache-2.0 | 理论上可以，但体积大；建议不发布、只写下载方式 |
| Qwen2.5-3B 权重 | Qwen Research License（仅研究） | **不可以** |
| 用户级预测/轨迹/访客库 | 衍生数据 + 隐私 | **不可以** |
| `deploy/stage66/api-vendor`、`third_party` | 各自许可 | 可以，必须保留 notices |

## 一句话

发"**能跑的最小可信集合**"（17 MB 代码 + 公开目录 + 文档），不发"全部研究资产"。
