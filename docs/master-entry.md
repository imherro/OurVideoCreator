# master 与本机入口统一（2026-09-19）

用户明确要求把验证后的同步分支正式合回 master，再统一开发和启动入口；该授权替代此前“保留旧 master 不动”的目录约定。

## Git 与工作目录

- 唯一日常工作目录：`C:\Users\kunpeng\Documents\ChatGPT\OurVideoCreator`，分支 `master`，推送 `origin/master`。
- 本次从 `eeb7a4f` fast-forward 到已验证同步分支 `ac91cf2ff4f2663e5a25e7d51eba92b98cfd30ec`，完整保留 63 个提交，无冲突、无 reset/revert/clean。原基线仍在历史中。
- `origin` 是 `imherro/OurVideoCreator`；`upstream` 是 `imherro/MyVideoCreator`，push 保持 `DISABLED`。本次没有合并 upstream/master。
- 同步分支保留在 `ac91cf2` 作为交接历史；旧 worktree 对齐统一入口提交后以 detached HEAD 保留，避免继续推进旧分支。该目录中的新启动入口会被私有脚本的目录检查拒绝。不删除其本地构建或记录，后续不要从那里启动或继续开发。
- 五角色 R1–R6 及 SYNC-40 已在 master；其他上游条目的分类继续见 [剩余清单](upstream-sync/2026-09-19-REMAINING.md)。合并不等于完成所有上游需求，AI 助手仍暂缓。

## 启动与数据

本机统一双击根目录 `Start-Local.cmd`；终端可用 `./Start-Local.ps1 -NoBrowser`。默认启动/复用 Web 与单 Worker，使用 loopback 7878、Worker 并发 1；可按需传 `-WebOnly` 或 `-WorkerOnly`。

仓库入口只调用 `%LOCALAPPDATA%\OurVideoCreator-dev\Start-Local.ps1`。私有脚本核对调用目录，读取已有 Windows 加密凭据，固定使用原验收 PostgreSQL `127.0.0.1:55440/ourvideocreator_acceptance`、原 `acceptance-media` 与同一解密主密钥。仓库不保存凭据、实际密钥或数据库连接密码。

迁移入口不执行初始化、建库、账号重置、Key 重写或数据库迁移。工程根目录变化会使 instance_id 变化，但数据库、媒体位置和用户内容仍是同一套；旧生命周期记录先备份，仅对已不存在的进程记录进行启动时正常刷新。通用 `Start-Studio.ps1` 仍作为已配置环境的底层启动工具。

开始检查时 7878 无监听，专用 PostgreSQL 也未运行，不能将前一天的运行记录当作本次实时状态。先恢复该专用 PostgreSQL、备份验收库和原前端/日志/启动配置，再核对 schema、任务状态及数据摘要。没有停止单机版或其他项目服务。

## 本次验证

历史功能测试记录保持原版本绑定，不冒充本次全量重跑。本次实测：

- 合并前两工作区干净，origin/master 与本地旧 master 一致，能够 fast-forward；合并后原目录执行既有 Twick 补丁（4 个发行文件），完整前端 **292 passed**（2350.47ms），TypeScript/Vite 构建通过（11.17s）。既有大 chunk 警告保留。
- 真实隔离 PostgreSQL 的 Web/Worker 生命周期与进程锁测试：`tests/test_p1_processes.py tests/test_process_lock.py` **3 passed（12.78s）**。夹具只创建/释放本轮 `ovc_test_*` 库，未用验收库跑测试，商业出站由夹具禁止。
- 本机私有备份 `before-master-entry-20260919-105948` 保存切换前数据库（188610 字节）、原主目录 dist、启动脚本、登录辅助脚本、生命周期记录和日志；未改写既有备份。
- 启动前后、API 登录前，验收库 **55 张表规范化内容摘要完全一致**，9 个媒体文件 SHA-256 一致。schema 始终 `0011_sample_reviews`，无迁移。历史任务始终 12 succeeded / 6 failed / 1 interrupted，queued/running 为 0。
- 密钥服务的原加密校验值通过 `checked_cipher` 验证；没有解密输出供应商 Key、重新保存/轮换 Key 或更换主密钥。原管理员 API 登录成功，四家快捷配置 `configured=true`，作品列表可读。此为本地配置可用检查，不是新的供应商鉴权/付费验证。
- 7878 只监听 `127.0.0.1`，健康 status=ok；网页 HTML 与原目录新 dist 完全一致，主包 `index-BIanMICl.js`。Web PID 31060、Worker PID 8200，均绑定原目录及原 acceptance-media，instance_id 为 `ovc-d898df8c678a2b3f67ac36c5fe193756`。Worker 并发 1；独立数据库连接尝试相同源码锁键得到 false，证明不能获取第二把 Worker 锁。
- Windows PowerShell 5 的 `.cmd` 首测暴露私有脚本 `python -c` 嵌套引号问题；改用标准输入传 Python 片段后，`.cmd -NoBrowser` 复测成功，复用上述相同 Web/Worker PID。目录守卫在加载凭据和进程启动前拒绝旧目录。
- 初次登录检查误请求不存在的 `/api/auth/session` 得到 404；改为读取实际 `ovc_csrf` Cookie 后，登录/退出闭环通过。登录测试正常追加会话/审计记录；上面的全表一致性比较发生在登录前，不宣称认证测试不写审计。
- 单机 7868 未停止、重启或修改。没有真实模型调用，没有续跑历史中断任务；未运行本次完整业务浏览器 E2E、五角色全部后端回归或新的备份恢复演练。

完成代码提交后推送 `origin/master`，核对 HEAD、跟踪分支和远端 SHA 一致。开发交付状态 READY_FOR_REVIEW；无需外部 ChatGPT 审核，不自称外部 PASS。
