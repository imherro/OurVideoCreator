# P2-R1 交付报告

## 1. 身份与状态

- 任务：只修复 P2 外部复验提出的五个并发/事务阻塞项。
- 被测试业务 SHA：`246db511bd950e649f59600a5f6cd2ed183be71e`。
- 分支：`master`。
- 唯一审核仓库：`https://github.com/imherro/OurVideoCreator`（协作版新仓库），不是 `MyVideoCreator`。
- 开发侧状态：**READY_FOR_REVIEW**。没有自行宣称 P2 通过，没有开始 P3。

本轮没有新增 schema 或 Alembic revision，没有引入 SQLite、Redis、Celery、S3 或多 Worker 调度，也没有调用真实付费 Provider。

## 2. 五项阻塞修复

| 外部编号 | 实施结果 | 关键位置 |
|---|---|---|
| OVC-P2-01 | Worker 保存锁连接的精确 PostgreSQL backend PID，并按 advisory key 的 `classid/objid` 检查所有权；独立监控线程和领取路径共享 ownership gate。锁连接死亡或 Worker DB 异常会设置 fatal 状态、停止新领取，CLI 返回 3；不会静默重取锁。只有显式启动第二 Worker 才能重新取得锁并领取。 | `backend/database.py`、`backend/worker.py`、`backend/worker_cli.py` |
| OVC-P2-02 | prompt library 首次写先 `INSERT ... ON CONFLICT DO NOTHING` 建立可锁空行，再 `FOR UPDATE` 校验 revision；并发 revision 0 精确一成功、一 409。Episode 的 `MAX+1` 先锁 Production，Chapter 的 `MAX+1` 先锁 source document。 | `backend/app.py` |
| OVC-P2-03 | resume 使用 `SELECT ... FOR UPDATE` 和 `WHERE status='interrupted' RETURNING`；状态更新和 event 同事务。cancel 继续通过 `job_update` 行锁串行，因此 cancel-first 拒绝 resume，resume-first 后续 cancel 最终获胜；重复 resume 不重置 running/succeeded。 | `backend/app.py`、`backend/store.py` |
| OVC-P2-04 | job update/provider handle/cancel phase、改编保存与状态转换、逐集剧本保存与状态转换、生成结果写回、章节修改/删除/恢复/过期标记、批量任务和素材通知均使用外层业务连接写 event。event 失败会回滚内容、history 和状态。任务节流改为查询同一事务可见的 PostgreSQL event，不再提前污染进程内缓存。 | `backend/store.py`、`backend/app.py`、`backend/adaptation.py`、`backend/source_library.py`、`backend/worker.py` |
| OVC-P2-05 | 每次 event 分配 identity 前取得固定 PostgreSQL transaction advisory lock，并持有到提交/回滚；后来的 event 无法在较早事务提交前取得更大 ID，从根源消除“小 ID 晚提交”。回滚序列空洞由 `id > cursor` 自然跨过；保留策略按最新已提交行数而不是 `id-retention`，不会因 sequence 空洞过删。 | `backend/store.py` |

`docs/multiuser-rollout/design/P2_STORAGE_CHANGELOG.md` 同时修正阶段边界：P5 为对象级协作 API，P6 为多 Worker 调度/lease/fencing/quota。

## 3. 真实 PostgreSQL 并发轨迹

正式专项测试每次会话创建、迁移并销毁唯一 `ovc_test_*` 数据库。`01-p2-r1-targeted.log` 的结构化输出证明：

- Worker 锁丢失：只终止测试 CLI 自报的 backend PID `33492`；CLI 返回 3；待领取任务保持 `queued`；显式启动替代 Worker（锁 backend PID `30692`）后任务才变为 `succeeded`。PID 是本次瞬时证据，不是固定配置。
- 首次写与序号：prompt 两个 revision 0 竞争者得到 `success/1` 与 `conflict/409`；两个 Episode 编号为 1/2；两个 Chapter 编号为 1/2。
- resume/cancel：cancel-first 后 resume 为 409；resume-first 两者按行锁完成且最终 cancelled；running 任务的重复 resume 保留 progress 37。
- 事务失败注入：job 保持 interrupted；adaptation 内容和 revision 不变；script revision/body/history 均不变。
- SSE：先提交事件 ID 7/8；回滚消耗 ID 9 后，下一个已提交事件为 10；从 cursor 8 重连精确得到 revision 4；保留窗口最终为 revisions 2/4/5。测试通过查询 `pg_stat_activity.wait_event='advisory'` 建立同步屏障，不靠固定 sleep 猜并发时序。

## 4. 验证结果

所有正式日志都在业务 SHA `246db511bd950e649f59600a5f6cd2ed183be71e` 上产生。

| 验证 | 结果 | 原始日志 |
|---|---:|---|
| P2-R1 + event/cursor 定向测试 | **10 passed**，9.45s，exit 0 | `01-p2-r1-targeted.log` |
| Python 全量 | **273 passed**，240.80s，exit 0 | `02-pytest-full.log` |
| 前端全量 | **126 passed / 0 failed**，exit 0 | `03-frontend.log` |
| TypeScript + Vite build | 1825 modules，7.22s，exit 0；仅既有 chunk-size warning | `04-build.log` |
| 原 P2 PostgreSQL/Worker/P1 进程回归 | **13 passed**，19.49s，exit 0 | `05-p2-regression.log` |
| compile/static/scope | compile exit 0；SQLite runtime forbidden 0；替换字符 0 | `06-static-scope.log` |

完整 Python 回归包含空库显式 Alembic、重复 upgrade、缺失/SQLite DSN 负向测试、Provider/素材/FFmpeg、API、生命周期和本轮并发测试。pytest 的非 loopback 阻断仍启用，没有真实付费出站。

## 5. 开发中失败与范围说明

开发首轮全量为 272 passed / 1 failed：旧测试 `test_worker_marks_recoverable_provider_error_interrupted` 直接调用 Worker 内循环但未先取得新要求的数据库所有权锁。修复方式是让该单元测试显式 acquire/release，同一业务安全约束未放宽；随后专项 6/6、开发全量 273/273 和正式全量 273/273 均通过。首次运行未重定向到文件，故只在 `ATTEMPT_HISTORY.md` 如实记录，没有补造原始日志。

静态 scope 搜索的两个 `P3/P4/P5/P6/P7` 命中只来自 `P2_STORAGE_CHANGELOG.md` 的阶段编号纠正，没有对应功能实现。P1-R3-N01 的历史本机 HTTP timeout 根因仍未知，本轮未宣称解决。

## 6. 外部审核入口

- 审核仓库：`https://github.com/imherro/OurVideoCreator`
- 分支：`master`
- 被测试业务 SHA：`246db511bd950e649f59600a5f6cd2ed183be71e`
- evidence-only head：本报告提交后的 SHA；该提交只包含 `docs/multiuser-rollout/evidence/P2-R1/` 和 gate 状态。
- 推荐顺序：本报告 → `SUMMARY.md` → `01-p2-r1-targeted.log` → `02-pytest-full.log` → 业务 diff。
- 最小复跑：设置测试管理员 PostgreSQL DSN 后执行 `python -m pytest -q tests/test_p2_r1.py tests/test_event_retention.py tests/test_events.py`，再执行 `python -m pytest -q && npm test && npm run build`。

请外部验收人基于协作版新仓库的实际提交与日志决定 P2 通过/不通过。P2 外部通过前不进入 P3。
