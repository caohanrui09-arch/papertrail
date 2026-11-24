# 阶段84：把失败原因接进实验台时间线（2026-11-22）

背景：阶段80–83 的结论是"框架可用、预算非瓶颈、能力主导"，但页面上的失败仍是一段原始错误文本。本阶段只做展示层：把 `reason=` 代码变成可读标签、在时间线顶部给出本次失败原因汇总，并让顶部诊断在未展开时也能看到原因。**不改服务端、不改 Agent 行为、不改评分。**

## 一、改了什么

| 位置 | 变化 |
|---|---|
| `research76/lab.js` | 新增 `REASON_TEXT`（29 个原因码：24 个状态机原因 + 5 个框架层兜底 → 中文标签与解释）、`reasonCode()`（解析 `reason=`，并兜底识别 `Unknown tool`/`Reached max steps`/schema 错误/确认词不匹配）、`reasonsOf()`（按本次运行统计）、`decorateReasons()`（在时间线顶部插入"失败原因"汇总条，并给每个失败步骤加徽标） |
| `research76/lab.js` `renderRun` | 渲染后调用 `decorateReasons(row)` |
| `research76/lab.js` `diagnose` | 顶部诊断文案前加 `【标签】`，不展开时间线也能看到原因 |
| `research76/workspace.css` | `.reason-summary`、`.reason-chip`、`.reason-count`、`.reason-total` 样式（琥珀色，沿用现有配色语义） |

原因码来源仍是 `gsearch/state_constraints.py` 的 `_reject()`；展示层不推断、不补造任何失败。

## 二、验证

| 检查 | 结果 |
|---|---|
| `node --check research76/lab.js` | 通过 |
| `tests/test_reason_map.py` | 3 项通过：状态机发射的每个原因码都有中文标签；时间线确实调用 `decorateReasons`；汇总条确实被 `prepend` 且 CSS 存在 |
| `research84/check_reason_ui.cjs` | 用真实 `stage81/82/83` 结果回放 20 次运行：产出的原因码全部有标签，统计数与「有错误的提案数」逐条相符，0 处异常 |
| HTTP | `8802/lab.js`、`8802/workspace76.css` 均 200 且含新标记（服务端每次请求读文件，无需重启） |

回放中出现的原因码：`final_citation_count`（6）、`tool_not_registered`（22）、`schema_type`（2）、`invalid_k`（14）。

## 三、渲染证据

由于本沙箱无法启动 headless Edge（mojo 通道被拒绝），没有做浏览器截图。替代证据是一个**用真实函数渲染的静态预览**：
`research84/render_reason_fixture.cjs` 从 `lab.js` 抽取 `decorateReasons()`，用最小 DOM 桩在真实的 `e73-empty` 失败轨迹上执行，输出 `reports/stage84/reason-summary-preview.html`（链接同一份 `workspace.css`）。

预览里能看到：汇总条显示「引用数量不符 ×3」「工具已被移除 ×3」「共 6 条被拒提案」，两个失败步骤各自带徽标，鼠标悬停显示原始错误。

## 四、边界

- 纯展示：没有改 `research77/server.py`、没有改判定、没有新增接口、没有新模型运行。
- 浏览器视觉仍未实测；DOM 结构与类名由桩渲染核对，样式由真实 CSS 文件提供，不声称"已截图验收"。
- 汇总统计的是「提案记录里带错误的条目」，与状态机的 `rejected` 计数含义不完全相同（前者含未知工具等框架层失败），页面上写的是"被拒提案"而不是"拒绝次数"。

## 五、复跑

```powershell
node --check research76/lab.js
node research84/check_reason_ui.cjs
node research84/render_reason_fixture.cjs
.cache\stage17\runtime\Scripts\python.exe -E -s -m unittest tests.test_reason_map
```
