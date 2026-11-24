# 本地推荐工具服务

只监听 `127.0.0.1:8765`，使用新安装的项目内CPython3.12.3、CPU依赖和迁移副本；不依赖旧父目录CUDA包。不对公网开放，不产生云费用。当前是**冻结历史快照上的推荐/原摘要工具服务**，不是统一T5搜索或LLM自主策略服务。

## 启动、状态与关闭

在项目根目录执行：

```powershell
.\service.cmd start
.\service.cmd status
.\service.cmd stop
```

后台进程无新窗口，日志和PID/实例记录只在忽略的 `.cache/stage18/`。关闭前检查进程创建时间、模块参数及解释器路径，拒绝因PID复用而关闭其他程序。每次进程重启会清空内存会话。启动时端口被占用会失败；不要停止不属于本项目的进程。

等价入口为 `.cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.local_service_control start|status|stop`；Python入口可用`--port`指定其他本地非特权端口。主机地址不能从API/CLI改成公网地址。

## 调用示例

```powershell
$base = 'http://127.0.0.1:8765'
Invoke-RestMethod "$base/health"

$session = Invoke-RestMethod -Method Post -Uri "$base/sessions" -ContentType 'application/json' -Body '{}'
$ranked = Invoke-RestMethod -Method Post -Uri "$base/sessions/$($session.session_id)/recommend" -ContentType 'application/json' -Body '{"k":3}'
$ranked.papers

$body = @{doc_id=$ranked.papers[0].doc_id} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/sessions/$($session.session_id)/read" -ContentType 'application/json' -Body $body
Invoke-RestMethod -Method Delete -Uri "$base/sessions/$($session.session_id)"
```

创建会话可提供 `method`（content、rrf、cold_aware）、`user_id`、带时区的`at`。缺省用户按训练画像用户的固定hash选取，缺省方法为content，缺省时间为2025-02-23T13:28:26.401006+08:00历史演示时点。未知用户按原规则回退流行度；不回写新用户偏好或更新训练。rrf和cold_aware权重分别固定0.5和tuning选定的0.25，不开放调参字段。

## 端点与约束

| 端点 | 作用 |
|---|---|
| GET / | 本地JSON说明，无外部网页资产 |
| GET /health | 万篇模型就绪、实例、历史截止与时间代理 |
| GET /openapi.json | FastAPI原生请求schema，无外部CDN文档页面 |
| POST /sessions | 创建固定用户/时点/方法的内存会话 |
| POST /sessions/{id}/recommend | k为严格整数1—10，调用原生recommend_papers |
| POST /sessions/{id}/read | 仅允许读取本会话已推荐的论文，原生read_paper重新核对原始v1 |
| DELETE /sessions/{id} | 清理本会话，其他会话不受影响 |

最多64个会话，创建后15分钟过期，成功工具调用预算4次；到期在后续操作中清理。不存在/过期会话404，输入schema错误422，违反读取约束400，预算耗尽429，容量已满503。访问日志关闭，不把个人结果写进公开报告。所有模型调用串行锁保护，单进程/单worker，未做并发QPS或生产鉴权验收。

## 实际验证范围

真实HTTP验证了三方法与冻结演示的排名/原v1一致、读取前置条件、预算、参数/时间边界、容量及只绑定回环；原生框架的TTL用可控时钟测试，不等待15分钟。启动/停止/重启另有验收记录，详见阶段18报告。单次API示例不是质量或延迟基准。

独立运行时和新路径回放已完成，仍在同一台Windows机器；没有真实第二台机器验收。新独立评分时段尚缺：原公开评分源未更新，服务目前不采集或伪造点击/反馈，也没有CTR、线上AB、万篇T5检索或统一LLM策略的效果结论。
