# 阶段76：五项顺序交付

## 第一项：页面减负（已交付）
候选列表优先；本次实际读取的原摘要/最终回答双视图；流转图彩色计数预览及details展开；任务完成收起设置；过程、参数、原始响应按需展开。点击流转调用仍自动展开原时间线；无结果失败保留，未读论文不会补读。黑白灰底色与75局部配色保持。

11项浏览器检查通过，模型调用0。记录reports/stage76/step1-validation.json，截图step1-paper-first.png。入口http://127.0.0.1:8802/。第二至五项继续按顺序实施；本页为逐项交付记录，最终以final-validation.json为准。

## 第二项：需求交接（已交付）
工作台新增“交给Agent”入口，URL片段带入原问题/查询并在接收后移除；严格v76接口核对来源字段，画像与目标时点仍来自原服务，不自动生成方案或执行。来源主题/年份如有，明确附加到执行草稿，原问题在交接原字段中完整保留；不自动应用目录过滤。修改查询后重新确认画像不会丢查询；接收侧必须重确认条件。

中英文、连续交接、修改查询/画像、限定保留、非法版本/字段/null/年份/控制字符拒绝等11项检查通过。模型执行0。记录step2-validation.json，截图step2-handoff.png。

## 第三项：双画像同池排序（已交付）
先运行原独立诊断，再选两种服务端冻结画像。按两者原生eligible交集剔除任一已读/不可用论文，冻结共同池、原查询、文本/词表/IDF、时点、历史IDs与哈希和RRF参数，然后调用原生rank_indices，展示两侧实际排名、内容余弦及最近历史论文；冷画像保持查询顺序，不注入流行度。源召回画像可能不同，本对照只展示池内名次，不评估召回/相关性提升。新v76严格接口额外字段拒绝，结果另存data/stage76-profile-comparisons。

17项API/边界核对（包含与独立旧诊断原生排序/锚点逐值一致、真实已读排除及空池）及6项浏览器检查通过。模型调用0，当前示例共同池15篇。记录step3-api-validation.json、step3-browser-validation.json和原始对照JSON，截图step3-two-profiles.png。

## 第四项：完整任务报告（已交付）
终局实际候选与同任务/同运行序号记录对齐后，可预览并下载Markdown+JSON。包含原需求/确认范围、实际候选/读取/引用、执行参数/返回/失败、公开模型提案与约束、记录到的Token和耗时。未知成本留空，固定流程Token0明确标注。私有模型输入/输出不导出；引用不通过本次来源链时不作为已核验答案导出，实际失败调用仍保留。JSON内容SHA256校验可回读，Markdown展示转义不改JSON原始文本。输入/任务变化撤销旧Blob链接，进行中不能当完整报告。

14项数据/反例与7项浏览器检查通过，两种文件已真正下载回读；样例step4-export-sample.json/md，下载副本reports/stage76/downloads。模型调用0。

## 第五项：真人试用准备（按用户选择已交付）
提供trial.html五张任务卡、开始前本地保存同意、匿名代号、单任务墙钟计时、JSONEditor反馈表、失败/跳过/多次尝试保留、草稿和活动任务恢复、JSON/Markdown导出。记录只在本浏览器，不自动上传、不记录浏览行为；试用页不会运行模型。

用户明确选择“先交付页面与任务卡，稍后试用”。因此真人试用尚未开展，已交付准备工作。自动验收使用?verification=1、固定automation_test来源和独立存储键，普通来源为参与者自述human_self_report，不是身份认证；与相关性标注完全分开。10项浏览器检查通过，失败/跳过样本只属自动验收，真人记录与相关性标签新增均0。沿用既有JSONEditor原生disable_theme_rules加外部CSS适配CSP，没有放宽安全头。

试用入口：http://127.0.0.1:8791/trial.html。每位朋友建议独立隐私窗口、关闭前导出。组织与任务说明见docs/USABILITY_TRIAL_V76.md。

## 启动、入口与复核

在任意PowerShell目录执行完整路径：

```powershell
& '<repo>\papertrail-workbench.cmd' start --no-open
& '<repo>\project-agent.cmd' start
```

论文工作台为 http://127.0.0.1:8791/ ，Agent实验台为 http://127.0.0.1:8802/ ，试用准备为 http://127.0.0.1:8791/trial.html 。旧标签页Ctrl+F5刷新。首次启动需装载冻结目录，用project-agent.cmd status检查就绪；已有模型作业运行时，不重启服务。新方案、诊断、对照、作业使用stage76目录，原历史记录仍可只读载入。

第一至五项分别保留step1至step5的验证JSON与截图。顺序交付和最终跨步骤回归共165项检查：本轮功能/边界76项，既有接口/算法/资产89项。没有新模型运行、重训、目录扩容或真人相关性标签；原阶段73的53次调用与4/0/3协议完成不变。本轮没有新增真实模型断线实验，继续使用已验收的原SSE、恢复、网关及预算。新接口只处理严格交接与独立CPU诊断，不注册为模型工具。

GitHub调研比较Radix Collapsible、FileSaver.js及SurveyJS，维护/许可证/固定commit见reports/stage76/opensource-research.json。实际复用原生details、现有Preact/JSONEditor、Blob导出模式、sklearn和原RRF/Agent组件；没有添加框架、重写索引、排名算法或Agent循环。JSONEditor用原生disable_theme_rules适配工作台CSP，不改上游库或放宽style-src。FileSaver仓库元数据未识别许可证，已实际读LICENSE.md确认MIT，未引入它的浏览器兼容分支。

实现验收中修复了同标签hash切换不重新接收交接的问题；表单首次因内联主题被原CSP拒绝，改用现成禁用内联主题选项；一次截图命令转义错误改为独立脚本。初次浏览器访问先于服务就绪，健康就绪后重做。保留这些适配发现，不把它们记成模型成功/失败，也没有删除旧业务失败。

可在项目根目录复核（全部不会启动模型）：

```powershell
node research76/check_step1.cjs
node research76/check_step2.cjs
.cache\stage17\runtime\Scripts\python.exe -E -s -m research76.check_step3
.cache\stage17\runtime\Scripts\python.exe -E -s -m research76.check_step3_boundaries
node research76/check_step3.cjs
node research76/check_step4_data.cjs
node research76/check_step4.cjs
node research76/check_step5.cjs
.cache\stage17\runtime\Scripts\python.exe -E -s -m research76.http_regression
```

浏览器脚本依赖本轮专用Edge调试实例9327、独立.cache/stage76/edge-profile和截图目录，不使用用户浏览器资料。脚本可生成新的CPU诊断/方案、自动试用记录与本地下载，不冒充真人。普通试用页不要用自动脚本点击同意或开始；自动检查固定使用?verification=1。预算仍为原每服务64次诊断、32次双画像对照；避免无意义重复复跑。验收结束关闭专用实例，保留8791/8802用户服务。

最终文件哈希和交付状态见reports/stage76/final-validation.json。没有手机、公网部署、第二台机器或真人质量验证的新增声明。
