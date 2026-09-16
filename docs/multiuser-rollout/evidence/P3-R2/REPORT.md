# P3-R2 — READY_FOR_REVIEW

仅审查协作版仓库 `https://github.com/imherro/OurVideoCreator`，分支 `master`。P0/P1/P2 历史通过不变；本次不自行签发 P3 通过，不进入 P4。

- 外部返修基线：`5e0c5e36d37415d4867d380f4e86dd47c87eebce`。
- 第一业务修复：`4a77a39`；最终被测业务 SHA：`cd61996bf6908f66cfd3429d27fa42acb03c144d`。
- 本目录随后单独提交证据；最终 evidence head 由该提交的 Git SHA 标识。业务 SHA 到证据提交只允许 `docs/` 变化。
- 环境：Windows / Python 3.14 / 真实 PostgreSQL，测试库由现有 pytest 白名单 fixture 创建。浏览器仅操作回环 7895 隔离服务；不触碰用户 7868，不运行真实付费 Provider。

## OVC-P3-R1-01：首次限流与锁序

`backend/identity.py::_lock_rate_limit_keys/rate_limit/record_failure/clear_rate_limit` 对去重排序的限流 key 取得 PostgreSQL transaction advisory lock，空桶也有共同同步边界；认证路径先限流键、后用户行。桶窗口时间在锁等待结束后读取。保留 Argon2id 成本、prehash 拒绝及成功登录不清共享 IP 的策略，无 Redis、Python 生产互斥或自动重试 POST。

红测在基线独立 worktree 上运行当前新增探针，仅复制测试文件，不修改基线业务：02 的 11 个空桶请求全部 401、verify 11 次、桶计数 11；03 的 A/B/C 确定性交错实际触发 `psycopg.errors.DeadlockDetected`（HTTP 401/401/500），带 PostgreSQL PID 和等待轨迹。不是用模拟数据库推断事故。

绿测 04 中 absent/expired/cleared 各 11 请求，均 10×401 + 1×429、verify 10、两桶计数 [10,10]；三请求返回 [401,401,401]，verify 3。测试用受控验证暂停点和 `pg_stat_activity/pg_blocking_pids` 观察真实等待，修复版等待于 advisory lock；不要求正确实现强行越过锁进入旧屏障。测试线程互斥仅保护计数/屏障，实际生产同步全部在 PostgreSQL。

## OVC-P3-R1-02：重置签发/消费

`backend/app.py::issue_password_reset/consume_password_reset` 和 `identity.lock_password_recovery_user` 使用共同 user→token 顺序。消费先只读解析 user_id，再锁用户、锁 token 并重新校验 active/consumed/revoked/expiry；成功消费撤销同用户其他未消费 token 和旧 sessions。签发串行撤旧建新；等待后取当前时间。无 schema 变化、无启动 DDL。

03 红测在两个真实 HTTP 客户端于实际 revoke UPDATE 后、INSERT 前暂停，旧业务两次签发 200/200、重叠 revoke=true、活跃 token=2。04 同探针修复后第二请求被用户行锁阻塞，200/200、重叠=false、活跃=1。

04 另有无旧 token / 已有旧 token、issue→consume / consume→issue 两种确定顺序、替换后的旧 token 拒绝、新 token 成功和重放 400、同 token 两消费者 200/400、login→reset 200/200 和 reset→login 200/401，旧 session 全失效，新密码登录 200。到期等待用例以真实 PG 用户锁阻塞并推进测试时钟，等待后 400。原停用、CSRF、共享 IP、权限与 SSE 回归保留。

00 披露第一版业务 `4a77a39` 在请求开始记录 now，等锁后可接受已过期 token 的红测；`cd61996` 修复后正式取证。00 当时使用 Python 等待点，最终用例改为真实 PG 行锁等待；不把这两次探针冒充字节相同。

## OVC-P3-R1-03：真实页面闭环证据

浏览器执行 2026-09-16T14:23:05.486Z 至 14:40:46.087Z。10 是逐步 CUA/Playwright/CDP 脱敏输出投影，11 是后续撤权原始工具/AX 输出，13 是实际隔离服务访问日志，12 是 read-only SQL 实际审计导出（12 行，ID 9–20）及成员关系查询。浏览器 UA 为 Chrome/152.0.0.0；工具未提供运行包版本，记录可见技能版本而不编造。

管理员 localhost 与成员 127.0.0.1 使用独立 host-only Cookie/origin storage，**不是两个浏览器 profile**。页面实际完成创建邀请→注册等待→确认入组→viewer 授权→双团队切换/刷新→按钮签发重置→表单消费→旧 Cookie SSE 401 / 登录页→新密码 UI 登录→移除作品权限→尚未加入作品→移出团队→刷新只剩另一个团队。最后 owner 降级 409 在 UI 展示，访问日志有对应状态；普通成员访问管理页亦为 403。没有以 API 脚本写入后刷新冒充按钮操作。

两次撤权按钮由工具点击，native confirm 工具取不到句柄，最终由用户手动确认；按人工协助浏览器验收申报，**不声称全自动**。原 owner 删除提示被用户取消，没有 DELETE；改用降级 409 验证错误反馈。10/11 保留错误断言（刷新恢复首个团队、异步加载未完成）、CDP 缓冲截断及浏览器 API 导航被阻止的取证限制；没有掩盖为全绿工具运行。浏览器调用无 CLI 总退出码，不能虚构 exit 0。

最终 SQL：该成员仅保留第二团队 owner 一行，production_members 零行；撤销原团队/作品对应 audit ID 19/20。记录的是合成测试账号，无原始密码/token/Cookie/Key/DSN。日志中的角色名及 user/workspace/production ID 用来关联请求、DOM 与审计。

## 正式回归

| 证据 | 实际结果 |
| --- | --- |
| 04-targeted.log | 27 passed，2 warnings，88.31s，exit 0 |
| 05-full.log | 303 passed，2 warnings，390.32s，exit 0 |
| 06-frontend.log | 126 passed，0 failed/skipped，exit 0 |
| 07-build.log | 1825 modules，8.24s，exit 0；原大 chunk warning |
| 08-routes.log | 88 注册项、85/85 API 分类，0 未分类，exit 0 |
| 09-compile.log | backend/migrations/scripts/tests 编译检查，exit 0 |

全量保留 P1/P2、Provider/FFmpeg 与 AUTH/ACL/MEDIA/EVENT 测试；没有删测试或降低断言。两个 Python warning 仍为 websockets 弃用。失败/探索尝试见 ATTEMPT_HISTORY，不计入正式绿测。隔离服务/数据库保留待审核；未声称已清理。历史未归因超时观察继续保留。

请外部验收人复核三个残留项是否关闭，判断 P3 是否通过。重点是已授权功能闭环和上述实际缺陷的最小修复；不扩大到 P4、不引入额外设计要求。
