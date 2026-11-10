# G3 P2-2 灰度冒烟状态（2026-11-10）——已完成

## 执行实况（与计划的偏差与自然补全）

- 计划：开 trace → ①②⑤轮询+辨识流各真实触发一轮（每链≤5）→ 端点验证 → 关开关
- 实况一：探测时 ① 待处理仅 1 条（reczz28XnHqm4q1L）、②⑤ 待处理 0；
  **dev 服务自身轮询（SAFETY_HAZARD_AI_POLL_ENABLED DB=true）在 09:37:20 已用
  热重载后的 P2-3 新代码处理掉该条**（早于 09:43 手动开 trace），手动轮次取数 0。
- 实况二（自然补全）：① 写回后该记录进入 ② 初审判据——**② 轮询于 09:47:24
  真实写回（AI初审结果/AI初审说明两列），P2-2 trace 钩子真实落库**，
  watcher 自动捕获两端点证据并关开关。
- ⑤：DB 无 SCORING_POLL 开关行且 registry 默认关 → dev 环境评分轮询本就不跑；
  ③ 督办轮询虽开，但其留痕走 superagent bridge（P2-2 之前形态）非本次 writeback_trace
  范畴——③⑤与辨识流以 P2-2 既有 19 个单测为代码级证据（用户拍板口径）。

## 验证矩阵

| 链 | 验证方式 | 证据 |
|---|---|---|
| ① 识别 | 真机（服务自身轮询，P2-3 新代码） | round 20261110093720-545a success；token-realtime.md |
| ② 初审 | **真机 trace 留痕 + REST 端点** | triggers-curl-raw.json / history-curl-raw.json（http 200） |
| ③ 督办 | 代码级（bridge 形态在 P2-2 前已有） | superagent_bridge 冒烟②既有验证 |
| ⑤ 评分 | 代码级（dev 默认关） | test_hazard_thread_trace.py 19 测试 |
| 辨识流 | 代码级 | P2-2 C3 orchestrator executor 测试 |

## trace 留痕真机证据（②写者）

- trigger 行：id=24dfc094-…，source=safety.hazard.writeback_trace，
  external_id=writeback:review:reczz28XnHqm4q1L:aad742bff74c（幂等键），
  thread_key=bitable:hazard:reczz28XnHqm4q1L，writer=review，
  fields=[AI初审结果, AI初审说明]，disposition=[{step: stored}]
- GET /api/v1/platform/superagent/triggers?thread_key=… → 200（724B）
- GET /api/v1/platform/superagent/threads/{key}/history → 200（787B，
  thread.last_trigger_at 聚合正确）
- 开关已由 watcher 自动关闭（值守结束，常开与否待用户拍板）

## watcher 事故记录（过程透明）

- 首版 shell watcher 有 HIT 变量污染 bug（uv env 输出行→URL 破损 http=000 +
  trace 被误关一次），10 分钟内发现，修复为单进程 Python 版重布防，期间无写回
  发生（零业务影响）；修复版 12 分钟后捕获上述②留痕。
