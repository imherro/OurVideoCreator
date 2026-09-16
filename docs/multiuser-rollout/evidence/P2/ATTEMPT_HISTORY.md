# P2-PG-01 开发尝试记录

本文件保留失败与修正，不用后续成功覆盖早期事实。

## A1 — PostgreSQL 安装器路径失败

- 现象：首次 `initdb` 退出 `-1073741515`。
- 原因：安装器/不完整运行库路径不可用。
- 处理：改用 PostgreSQL 官方 portable ZIP，实际目录为用户本机 AppData 下的隔离工具目录；没有把数据库二进制提交进仓库。
- 原始日志：当时终端未重定向，无仓库内原始日志；这里只记录已观察事实，不补造输出。

## A2 — 首次服务启动参数错误

- 现象：`pg_ctl` 因 `listen_addresses` 引号形式错误拒绝启动。
- 处理：修正为 loopback-only 的合法参数后启动 PostgreSQL 18.6，端口 55432。
- 原始日志：当时终端未重定向，无仓库内原始日志。

## A3 — 初次全量迁移回归失败

- 第一次：75 failed、179 passed。主要为测试仍使用 SQLite `?` placeholder 和已退役 SQLite schema/migration 假设。
- 第二次：4 failed、244 passed。剩余为遗留 migration 测试、`PRAGMA`、`INSERT OR REPLACE` 与缺失 `executemany` 适配。
- 处理：把业务和测试 fixture 全部切到 psycopg/PostgreSQL，删除 SQLite 启动迁移测试，补足 cursor 批量接口与 PostgreSQL schema 断言。
- 原始日志：两轮发生在建立正式证据目录前，终端未重定向；计数不作为通过证据。

## A4 — 旧业务 SHA 的正式候选运行

- 业务 SHA：`938b665e133ab014f1820991720da973082592a0`。
- 已通过：后端 267、P2 定向 10、生命周期 9、FFmpeg 5、Provider 42、前端 126、build。
- 手工生命周期首次尝试：使用 AppData 目录时，Codex packaged runtime 的 Windows known-folder 重定向令 PowerShell 与 Python 看到不同规范路径，身份保护按设计拒绝启动。
- 手工生命周期第二次尝试：Web/Worker/健康/第二 Worker 拒绝成功，但 PowerShell 7 的 Stop 把 JSON ISO 日期自动变为 `DateTime` 后再转文化字符串，丢失小数秒，合法进程被判 creation-time mismatch。
- 处理：安全核验本轮明确 PID 的完整 command line 后清理；没有触碰用户的 7868/PID 22820 服务。所有原始日志保存在 `attempts/938b665/`。
- 结论：这是实际代码缺陷，不以“测试已通过”掩盖。该 SHA 的全部结果废弃，不作为 P2 通过证据。

## A5 — PowerShell 7 所有权修复

- 修正：`Studio-Process.ps1` 将记录时间按 RoundtripKind/UTC 解析，与 CIM creation time 以 ticks 精确比较；畸形时间继续拒绝，不放宽 executable/command line/root/data-dir 校验。
- 回归：新增 `test_pwsh_stop_keeps_json_datetime_precision`，真实调用 PowerShell 7 Start/Stop；专项 1 passed。
- 新业务 SHA：`a6820b045123ed73953cbe5667821225f8ceafb5`。

## A6 — 新业务 SHA 正式取证

- 新建全新证据库 `ovc_test_p2_evidence_a6820b0`，两次 Alembic 通过。
- 后端 268、P2 定向 10、生命周期 10、FFmpeg 5、Provider 42、前端 126、build 全部通过。
- 手工生命周期使用非虚拟化外部目录：Web/Worker 正常；健康不泄密；不同媒体目录第二 Worker 被拒绝；Stop 脚本正常停止两个 PID并清记录/释放端口。
- 正式原始日志为 P2 根目录 `00`–`11`；无失败重跑。

## P1 观察项

`OVC-P1-R3-N01` 的旧 HTTP timeout 本轮未复现，原根因仍未知。P2 已增加确定性失败 dump，但没有宣称旧超时根因已修复，也没有自动重试有副作用请求。
