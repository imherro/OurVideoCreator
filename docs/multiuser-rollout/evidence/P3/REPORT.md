# P3-ID-01 交付报告

## 1. 身份、状态与审核仓库

- 阶段：P3-ID-01 — 邀请制个人账号、团队/作品隔离与基础管理页面闭环。
- 前置外部通过：P2-R2，`a70341bad5c0da23153ad6cd44b67f2cd863dde1`。
- 被测试业务 SHA：`8b9c74607b46d8c09fb5d6445e46d57fead4f2b3`。
- 分支：`master`。
- 唯一审核仓库：`https://github.com/imherro/OurVideoCreator`；不是单机版 `MyVideoCreator`。
- 开发侧状态：**READY_FOR_REVIEW**。没有自行宣称 P3 通过，没有开始 P4。

本阶段继续保持单 Worker、内部试用，不实施凭证平台化、多 Worker、公网发布，也不调用真实付费 Provider。

## 2. 实施结果

| 范围 | 实现结果 |
|---|---|
| 初始管理员 | `python -m backend.admin_cli bootstrap-admin` 使用 advisory lock，仅允许空系统创建一次；重复执行拒绝且不覆盖密码；公开 `/api/auth/setup` 固定返回 410 |
| 邀请注册 | 邀请 token 仅保存 SHA-256 摘要，过期/撤销/复用拒绝，并发消费只有一个成功；注册事务失败不会消耗邀请 |
| 密码与会话 | Argon2id 密码；个人 DB session；退出、改密/重置、停用均撤销旧 session；重置 token 短期一次性且只存摘要 |
| Web 防护 | 数据库持久限速覆盖登录/注册/重置；双提交 CSRF；跨 Origin 写拒绝；Cookie 设置 HttpOnly/SameSite，并按生产配置 Secure；只信任明确 CIDR 内代理 |
| 团队与作品 ACL | workspace owner、production manager/editor/viewer 分离；跨租户及同团队未参与作品统一隐藏为 404；同作品权限不足为 403；平台管理员不具有普通内容万能旁路 |
| 嵌套资源 | 项目、作品、素材、修订、任务、回收站、原著/章节、改编、剧本、设置、Provider 与事件入口均显式分类和授权；嵌套 ID/批量 ID 做归属校验 |
| 管理与审计 | 平台管理、团队成员、作品成员、邀请、重置和状态变更使用独立入口；关键管理及业务动作写审计；最后活跃平台管理员和团队 owner 不可被移除/降级/停用 |
| 素材能力 | 普通素材读取按作品授权；Provider 签名 URL 绑定 asset、HTTP method、purpose、expiry，篡改/过期/撤销失效 |
| SSE | 事件带 workspace/production 归属，连接只返回当前可见作品；每 2 秒重查成员与 session，撤权/停用后不晚于 5 秒停止 |
| 前端闭环 | 登录、邀请注册、密码重置、等待加入团队、团队切换、空团队/空作品状态、`/admin` 和 `/members` 页面；无权限控制隐藏并保留服务端拒绝 |
| ACL-09 | `scripts/audit_routes.py` 对实际注册路由做 fail-closed 分类；新增未分类 API 会非零退出；OpenAPI 禁用 |

## 3. 验收矩阵映射

| 编号 | 证明内容 | 证据 |
|---|---|---|
| AUTH-01 | CLI 初始管理员、重复不改密、公开 setup 退役、P2 旧数据归属回填 | `test_auth01_protected_cli_bootstraps_once_and_public_setup_is_retired` |
| AUTH-02/03/04 | 邀请过期/撤销/复用/并发/失败回滚；手机号规范化唯一；注册无提权；密码和 token 非明文 | `test_auth02_03_04_invites_are_transactional_one_time_hashed_and_role_safe` |
| AUTH-05…09 | 多会话隔离与撤销、一次性重置、跨进程限速、CSRF/Cookie/代理、最后管理员与 owner、mass assignment 拒绝 | `test_auth05_06_07_08_09_sessions_reset_rate_limit_csrf_and_last_role_guards` |
| ACL-01…08 | 两团队及同团队两作品的 owner/manager/editor/viewer/team-only 正反矩阵；嵌套 ID、文件、任务、回收站、设置、管理边界和审计 | `test_acl01_to_08_role_matrix_nested_ids_files_jobs_trash_and_admin_boundary` |
| ACL-09 | 实际 85 条 API 全分类；注入虚构新路由时守卫失败 | `test_acl09_route_guard_fails_for_a_new_unclassified_api_route`、`05-route-audit.json` |
| MEDIA-01 | 作品素材读取与 Range 跟随 ACL；跨作品、跨团队拒绝 | ACL 定向测试中的 asset/file 矩阵 |
| MEDIA-04 | 签名绑定 asset/method/purpose/expiry；过期、删除撤销失败 | `test_media04_signed_capability_binds_asset_method_purpose_expiry_and_revocation` |
| EVENT-01/02 | 真实 Uvicorn 长连接无跨团队泄漏；移除成员及停用 session 后在复核窗口内停止 | `test_event01_02_live_sse_filters_tenants_and_stops_after_membership_and_session_revocation` |

P3 提示词要求的 AUTH-*、ACL-*、MEDIA-01、EVENT-01/02 均有正常与拒绝路径。MEDIA-04 是本阶段为 Provider 回调素材补充的额外闭环，不提前宣称 P4 通过。

## 4. 正式验证

所有正式结果均绑定业务 SHA `8b9c74607b46d8c09fb5d6445e46d57fead4f2b3`。

| 验证 | 结果 |
|---|---:|
| `python -m pytest tests/test_p3_identity_acl.py -q` | **7 passed**，2 个上游 websockets deprecation warning，exit 0 |
| `python -m pytest -q` | **283 passed**，2 个相同 deprecation warning，exit 0 |
| `npm test` | **126 passed / 0 failed**，exit 0 |
| `npm run build` | 1825 modules，exit 0；仅既有 chunk-size warning |
| `python scripts/audit_routes.py` | 85/85 API 已分类，0 未分类，OpenAPI null，exit 0 |
| `python -m compileall -q backend migrations scripts tests` | exit 0 |

原始输出为本目录 `01-p3-targeted.log` 至 `06-compile.log`。测试使用专用临时 PostgreSQL 数据库；不打印生产 DSN 或密钥。

## 5. 浏览器闭环

在独立端口 7893、隔离测试数据库上验证：管理员登录和 `/admin` 用户/团队/邀请页面；普通成员登录后的“等待加入团队”；加入团队后的“尚未加入作品”；双团队选择器切换；owner 空团队的“创建第一部作品”；`/members` 成员管理与手机号掩码。临时服务和数据库在验证后已删除，用户现有 7868 服务未被触碰。详见 `07-browser-manual.md`。

## 6. 已知边界

- 两个 warning 来自 Uvicorn 依赖的 websockets 旧接口，不影响本轮 SSE 断言。
- 前端仍有既有大 chunk 构建 warning，构建成功。
- P1 的 `OVC-P1-R3-N01` 和 P2 的 `OVC-P2-R2-N01` 继续作为非阻塞观察保留，本阶段未伪造根因结论。
- P4（团队 Provider 凭证、密钥加密/轮换等）未实施、未授权。

## 7. 外部审核入口

- 审核仓库：`https://github.com/imherro/OurVideoCreator`
- 分支：`master`
- 被测试业务 SHA：`8b9c74607b46d8c09fb5d6445e46d57fead4f2b3`
- evidence-only head：本报告提交后的 SHA；只包含状态与证据文件。
- 推荐顺序：本报告 → `SUMMARY.md` → `../../design/PERMISSIONS.md` → `../../design/ROUTE_AUTH_MAP.md` → `01-p3-targeted.log` → `02-pytest-full.log` → 实际代码 diff。

请外部验收人只审查协作版新仓库的 P3 实际提交与证据，给出“通过/不通过”、问题编号与严重级别；只有 P3 通过时才授权 P4。
