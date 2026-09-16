# P2-R2 交付报告

## 1. 身份与状态

- 单一任务：修复 `OVC-P2-R1-01`（S2），不再用 PostgreSQL Identity 数值差代替 SSE 实际积压行数。
- 被测试业务 SHA：`fc8feee3d9c3bfaffb39c55ab10d41e0fff7050f`。
- 分支：`master`。
- 唯一审核仓库：`https://github.com/imherro/OurVideoCreator`。
- 开发侧状态：**READY_FOR_REVIEW**。没有自行宣称 P2 通过，没有开始 P3。

外部 P2-R1 已关闭 `OVC-P2-01` 至 `OVC-P2-04`；本轮没有重新修改这些实现。`backend/store.py::_event` 的事务发布锁、业务/event 原子性、按行保留和数据库节流均保持不变。

## 2. 修复实现

`backend/app.py` 将连接初始化拆成两个明确步骤：

1. `_requested_event_id()` 只解析 `after` 和 `Last-Event-ID`，两者同时存在时沿用较大值；无有效游标表示第一次连接。
2. 有重连游标时，`events()` 在一条 PostgreSQL SQL 语句的同一快照中读取：`MAX(id)`、`MIN(id)`、请求游标是否仍被保留、以及 `id > requested` 的实际可见行数（最多扫描 `backlog_limit + 1` 条）。

`_event_cursor()` 仅根据这些可见记录决定：

- 无游标或游标已到/超过 head：从 head 开始，保持第一次连接约定；
- 游标低于最旧保留行且本身不再存在：视为真正窗口外，从 head 开始；
- 实际可见积压超过 500：沿用既有 head-only 策略；
- 其余情况从请求游标重放，即使 ID 数值差因回滚空洞远超 500。

初始化事务在该单条统计查询后立即结束；长连接循环不持有该事务或发布锁。后续提交的事件仍会被 `id > cursor` 的下一轮查询看到。

## 3. 修复前失败与修复后真实 PostgreSQL 轨迹

`00-prefix-large-gap-failure.log` 绑定上轮 evidence head `1ae1544...`，使用新增测试在隔离 `ovc_test_*` 数据库构造：

- 先提交 ID 1；
- 一个真实事务调用现有 `s._event()` 500 次并 rollback，不用 `setval` 或人工改 ID；
- 再提交 ID 502；
- 数据库只保留 `[1, 502]`，实际积压为 1；
- 旧代码的 `Last-Event-ID=1` 和 `after=1` 实际流首块均为 heartbeat，记录为 `[null, null]`，测试按预期失败（exit 1）。

`02-p2-r2-targeted.log` 在新业务 SHA 上重复同一真实轨迹：两个实际 `events()` body iterator 均收到 ID 502，记录为 `[502, 502]`。测试仅替代 request/disconnect 外壳；数据库、事件 helper、游标初始化、SQL 和 StreamingResponse body iterator 都是真实路径，并有 3 秒 deadline 与 `aclose()` 清理。

同一日志还覆盖：

- 第一次无游标连接保持 head-only；
- 无空洞和一个 rollback 小空洞正常重放；
- 实际可见积压 501 时保持 head-only；
- retention=3 时，请求已删除且低于最旧保留行的真实窗口外游标保持 head-only。

## 4. 验证结果

除明确标记的修复前失败外，所有正式成功日志均绑定业务 SHA `fc8feee3d9c3bfaffb39c55ab10d41e0fff7050f`。

| 验证 | 结果 | 原始日志 |
|---|---:|---|
| 修复前大空洞实际流复现 | **1 failed（预期）**，保留 `[1,502]`、收到 `[null,null]`，exit 1 | `00-prefix-large-gap-failure.log` |
| P2-R2 + cursor/retention 定向 | **8 passed**，3.66s，exit 0 | `02-p2-r2-targeted.log` |
| Python 全量 | **276 passed**，264.75s，exit 0 | `03-pytest-full.log` |
| P2-R1/P2-R2/原 PG/Worker/P1 进程回归 | **20 passed**，36.42s，exit 0 | `04-p2-regression.log` |
| 前端全量 | **126 passed / 0 failed**，exit 0 | `05-frontend.log` |
| TypeScript + Vite build | 1825 modules，8.25s，exit 0；仅既有 chunk-size warning | `06-build.log` |
| compile/static/scope | compile exit 0；SQLite forbidden 0；范围命中 0；migration 变更 0；替换字符 0 | `07-static-scope.log` |

完整 Python 回归继续包含真实空 PostgreSQL/Alembic、P2-R1 五类测试、Provider/素材/FFmpeg、API 和生命周期。没有真实付费出站。

## 5. 开发观察与范围

开发组合回归中，更新前的 P2-R1 纯 helper 断言因未提供新的可见行统计而失败，已按真实保留行参数适配；业务 endpoint 没有降级回旧算术。同一组合还出现一次独立 PostgreSQL connect 5 秒 timeout，出现在普通 project GET；该单项随 SSE 测试立即复跑 2/2 通过，随后专项 25/25、开发全量 276/276、正式全量 276/276。该超时与历史 `OVC-P1-R3-N01` 一样根因未知，本轮不宣称解决，也没有给有副作用请求加重试。

业务 diff 只有 `backend/app.py` 和三处测试文件；没有 schema、迁移、依赖、P3/P4/P5/P6/P7 功能变化，没有 Redis/Celery/S3。

## 6. 外部审核入口

- 审核仓库：`https://github.com/imherro/OurVideoCreator`
- 分支：`master`
- 被测试业务 SHA：`fc8feee3d9c3bfaffb39c55ab10d41e0fff7050f`
- evidence-only head：本报告提交后的 SHA。
- 推荐顺序：本报告 → `00-prefix-large-gap-failure.log` → `02-p2-r2-targeted.log` → `03-pytest-full.log` → 业务 diff。
- 最小复跑：设置测试管理员 PostgreSQL DSN 后运行 `python -m pytest -q -s tests/test_p2_r2.py tests/test_events.py tests/test_event_retention.py`，再运行 `python -m pytest -q && npm test && npm run build`。

请外部验收人只复核 `OVC-P2-R1-01` 及必要回归，并决定 P2 通过/不通过。外部通过前不进入 P3。
