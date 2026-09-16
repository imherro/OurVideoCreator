# P2-PG-01 交付报告

## 1. 身份、状态与审核仓库

- 阶段：P2-PG-01 — PostgreSQL 唯一主库、空库迁移、Web/独立 Worker 运行闭环。
- 前置外部通过：P1-R3，`6358c76f238a680dc9bd27b44968d5fe82db29d0`。
- 被测试业务 SHA：`a6820b045123ed73953cbe5667821225f8ceafb5`。
- 分支：`master`。
- 唯一审核仓库：`https://github.com/imherro/OurVideoCreator`；不是单机版 `MyVideoCreator`。
- 开发侧状态：**READY_FOR_REVIEW**。没有自行宣称 P2 通过，没有开始 P3。

本阶段未导入 SQLite 数据、未双写、未复制旧 key、未调用真实付费 Provider，也未实施公网、多用户 ACL、凭证加密或多 Worker。

## 2. 实施结果

| 要求 | 实现与定位 |
|---|---|
| PostgreSQL 唯一运行时数据库 | `backend/database.py` 要求 `OVC_DATABASE_URL` 且只接受 PostgreSQL；缺失/SQLite 立即失败，无回退 |
| 独立可重复迁移 | Alembic `0001_postgresql_baseline` 创建全部保留表、约束、索引与 JSONB；空库升级及重复升级通过 |
| 启动不改 schema | `store.init()`/Web/Worker 只执行 readiness 与精确 head 检查；没有 `create_all`、启动 `ALTER/DROP` |
| 全业务 PostgreSQL 化 | 所有业务 SQL 使用 psycopg 参数、事务与 PostgreSQL 并发语义；SQLite runtime/migration 删除 |
| 并发保存 | 行锁加 revision 条件更新；同 revision 两个连接一成功、一 409；内容/history/event 同事务 |
| 批量原子性 | jobs、job_private、events 整批同事务；最后一项失败时全部回滚 |
| 单 Worker 数据库锁 | Worker 通过同库 session advisory lock 独占；不同 `MVC_DATA_DIR` 不能绕过；队列用 `FOR UPDATE SKIP LOCKED` |
| 媒体边界 | `StorageBackend`/`LocalStorageBackend` 统一新素材写入与读取，拒绝路径逃逸；媒体目录不是数据库身份 |
| 生命周期 | Start/Stop 保存并恢复 DB 环境；Stop 不连接数据库；PowerShell 5.1/7 都精确校验本地进程所有权 |
| P1 观察项 | 进程测试无论成败输出子进程日志、阶段、总耗时、最后请求耗时、安全 DB 状态和任务状态；不重试有副作用 POST |

完整 schema、JSONB、约束、事务和阶段边界见 `../../design/P2_STORAGE_CHANGELOG.md`。

## 3. DB-01 至 DB-06 证据映射

| 编号 | 证明内容 | 结果与原始证据 |
|---|---|---|
| DB-01 | 真实空 PostgreSQL、独立 Alembic、重复升级、精确 head | PostgreSQL 18.6；数据库 `ovc_test_p2_evidence_a6820b0`；schema `public`；head `0001_postgresql_baseline`；19 张 public table（18 业务 + Alembic）、21 JSONB、39 indexes；`01-db01-migration.log` |
| DB-02 | 缺 DSN/SQLite DSN 无回退；启动不迁移 | 两条负向启动均明确失败，空库必须显式 Alembic；`03-db01-db05.log` |
| DB-03 | 同 revision 并发 | 两个独立连接竞争相同 revision，精确一成功、一冲突；`tests/test_p2_postgresql.py` 与 `03-db01-db05.log` |
| DB-04 | 保存/历史/event 和批量任务事务原子性 | 保存注入失败回滚三类数据；批量最后项失败回滚 jobs/job_private/events；`03-db01-db05.log` |
| DB-05 | 持久化、readiness 重启、reset guard、单 Worker DB 锁 | 数据在 dispose/readiness 后仍在；用户库拒绝 reset；不同媒体目录第二 Worker 被拒绝；离线 Stop 与安全实例身份通过；`03-db01-db05.log`、`10-manual-lifecycle.log` |
| DB-06 | 全保留业务与 Provider/素材/事件实际经过 PostgreSQL | Python 全量 268 项；Provider 映射/Ark/RunningHub/幻场/语音 42 项；FFmpeg 5 项；前端 126 项；`02-pytest-full.log`、`05-ffmpeg.log`、`06-provider-db06.log`、`07-frontend.log` |

DB-06 覆盖作品与剧集、原著文档/章节/事件、剧本及修订、Film Bible 与 storyboard 所在项目 document、任务与私有 Provider 配置、素材登记与 Provider 远端映射、事件流、回收站、设置和 session。全量测试的会话数据库在 Alembic 后才收集测试，故这些路径没有 SQLite 旁路。

## 4. 最终证据运行

所有正式结果均在业务 SHA `a6820b045123ed73953cbe5667821225f8ceafb5` 上产生；旧 SHA `938b665` 的结果不作为通过证据，只保存在 `attempts/938b665/` 与 `ATTEMPT_HISTORY.md`。

| 验证 | 结果 |
|---|---:|
| 空库 `alembic upgrade head` + 重复执行 + metadata | exit 0；18.6 / public / exact head |
| `python -m pytest -q` | **268 passed**，249.32s，exit 0 |
| `tests/test_p2_postgresql.py -q -s` | **10 passed**，11.90s，exit 0 |
| P1 进程 + PowerShell 生命周期 | **10 passed**，92.92s，exit 0 |
| FFmpeg 导出 | **5 passed**，13.08s，exit 0 |
| Provider/映射定向回归 | **42 passed**，16.49s，exit 0 |
| `npm test` | **126 passed / 0 failed**，exit 0 |
| `npm run build` | 1825 modules，6.74s，exit 0；仅既有 chunk-size warning |
| Python compile + SQLite runtime scan | compile exit 0；runtime scan 0 match；tracked SQLite artifact 0 |
| 手工 Web + Worker 生命周期 | 健康、第二 Worker 拒绝、脚本停止两 PID、记录清除、端口释放 |

原始命令输出：`00-context.log` 至 `11-cleanup.log`。日志包含退出码；健康输出经检查不含 DSN/数据库用户名。两个本轮专用证据数据库在取证完成后按精确白名单删除，`11-cleanup.log` 显示剩余数量 0。

## 5. 手工生命周期实测

在端口 7879、独立外部媒体目录和真实 PostgreSQL 证据库上：

1. `Start-Studio.ps1 -Port 7879 -NoBrowser` 启动 Web PID 35224、Worker PID 20536。
2. `/api/health` 返回 `status=ok`、`role=web` 与 instance id，`health_contains_database_url=False`。
3. readiness 返回 PostgreSQL 18.6、目标 database、`public` 和 backend PID。
4. 改用另一个 `MVC_DATA_DIR` 执行 `-WorkerOnly`，仍因同一数据库已有 Worker 而被拒绝。
5. 原目录 `Stop-Studio.ps1` 正常输出两个 `stopped`；两 PID 均消失，两个 lifecycle record 均删除，7879 listener count 为 0。

这次手工复验还发现并修正了 PowerShell 7 JSON 日期自动转换导致的所有权精度问题；因此旧 SHA 的证据被废弃，新测试与全套证据均绑定修正后的业务 SHA。

## 6. P1 非阻塞观察项跟踪

`OVC-P1-R3-N01` 的原始一次本机 HTTP timeout 根因仍未知，未伪造“已解决”结论。本轮多次进程复验没有复现。P2 已按要求增强失败出口：记录 Web/Worker/fake-provider stdout/stderr、测试 phase、elapsed、最后请求 URL/method/耗时、安全 DB server/database/schema/backend PID 和任务状态；成功运行也输出同一结构以证明诊断链可用。没有给有副作用的 POST 添加自动重试。

## 7. 开发尝试与未隐藏失败

开发中的迁移失败、首轮测试失败、PostgreSQL 启动参数错误和 PowerShell 7 手工 Stop 缺陷都列在 `ATTEMPT_HISTORY.md`。有原始日志的旧 SHA 运行保存在 `attempts/938b665/`；早期没有重定向的终端输出仅按当时观察记录，明确标注“无原始日志”，没有补造。

## 8. 外部审核入口

- 审核仓库：`https://github.com/imherro/OurVideoCreator`
- 分支：`master`
- 被测试业务 SHA：`a6820b045123ed73953cbe5667821225f8ceafb5`
- evidence-only head：本报告提交后的 SHA；该提交只包含 docs/status/raw evidence。
- 推荐顺序：本报告 → `SUMMARY.md` → `../../design/P2_STORAGE_CHANGELOG.md` → `01-db01-migration.log` → `03-db01-db05.log` → `04-process-lifecycle.log` → `10-manual-lifecycle.log` → 实际代码 diff。
- 最小复跑：配置测试管理员 DSN 后执行 `python -m pytest -q`；另执行 `npm test && npm run build`。

请外部验收人读取协作版新仓库的实际提交与日志后决定通过/不通过。P2 外部通过前不进入 P3。
