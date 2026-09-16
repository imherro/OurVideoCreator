# P2-PG-01 证据汇总

- 状态：`READY_FOR_REVIEW`
- 审核仓库：`https://github.com/imherro/OurVideoCreator`
- 业务 SHA：`a6820b045123ed73953cbe5667821225f8ceafb5`
- PostgreSQL：18.6；Alembic head `0001_postgresql_baseline`
- Schema：18 张业务表 + `alembic_version`，21 个 JSONB 字段，39 个 index/constraint index
- 后端：268/268
- P2 PostgreSQL 定向：10/10
- 真实进程与生命周期：10/10
- FFmpeg：5/5
- Provider/映射：42/42
- 前端：126/126
- 生产构建：成功，1825 modules；仅既有大 chunk 警告
- 运行时 SQLite 扫描：0 命中；tracked SQLite artifact：0
- 手工生命周期：健康；同库第二 Worker 被拒绝；Stop 正常停止；记录清除；端口释放
- 真实付费 Provider：未调用
- P3：未开始、未授权

| 日志 | 内容 |
|---|---|
| `00-context.log` | SHA、remote、工具与依赖版本 |
| `01-db01-migration.log` | 空库建库、两次 Alembic、readiness、表/JSONB/index 清单 |
| `02-pytest-full.log` | Python 全量 268 passed |
| `03-db01-db05.log` | DB-01 至 DB-05、并发/回滚/持久化/锁/离线 Stop |
| `04-process-lifecycle.log` | Web/Worker/fake Provider、诊断 dump、PowerShell 5.1/7 生命周期 |
| `05-ffmpeg.log` | 真实 FFmpeg 导出与解码 |
| `06-provider-db06.log` | Provider、素材与远端映射回归 |
| `07-frontend.log` | 前端 126 passed |
| `08-build.log` | TypeScript/Vite 生产构建 |
| `09-static-scan.log` | compile、SQLite dialect/path 与 tracked artifact 扫描 |
| `10-manual-lifecycle.log` | 真实 Web+Worker 启停、健康、同库 Worker 锁、端口清理 |
| `11-cleanup.log` | 证据库精确白名单清理 |
| `attempts/938b665/` | 已废弃旧 SHA 的原始运行；不作为正式通过证据 |

外部结论尚未填写；本汇总只代表开发侧已完成并提交复核。
