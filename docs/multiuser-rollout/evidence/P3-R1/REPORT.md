# P3-R1 返修交付报告

## 1. 状态与审核边界

- 前置外部通过：P2-R2，`a70341bad5c0da23153ad6cd44b67f2cd863dde1`。
- P3 首轮外部不通过 HEAD：`dc1b0083db90ac1960b1f88117fa673e878c7baf`；业务 SHA：`8b9c74607b46d8c09fb5d6445e46d57fead4f2b3`。
- 本轮被测试业务 SHA：`a8cd59e8247b915737084383f5b53df1f831f4fe`。
- 唯一审核仓库：`https://github.com/imherro/OurVideoCreator`；不是单机版 `MyVideoCreator`。
- 开发侧状态：**READY_FOR_REVIEW**。没有自行宣称 P3 通过，没有开始 P4。

本轮只处理外部授权的 `OVC-P3-01…06`。继续保持单 Worker、内部试用；不调用真实付费 Provider。P4 的后续边界准确表述为“平台统一 Provider/Key/模型后台”，不是团队自管 Provider。

## 2. 六项阻塞处理

| 编号 | 修复与可复核证明 |
|---|---|
| `OVC-P3-01` | 批量 `POST /chapters/trash` 与单项 DELETE 同样显式要求 manager/owner；ACL 矩阵实际证明 editor 批量删除 403、manager 成功。 |
| `OVC-P3-02` | 团队撤权和作品授权进入同一 PostgreSQL 事务级 advisory 不变量锁；授权前要求有效团队成员；读端列表、详情、权限投影与成员列表同时要求有效团队关系；重新入组会清掉旧孤立作品角色，避免静默复活。确定性并发测试证明不会遗留可用孤立授权。 |
| `OVC-P3-03` | 登录验证与密码重置均对同一用户行 `FOR UPDATE`；重置更新密码、撤销旧 session、签发新 session 在同一串行事务中。并发测试证明旧密码不能迟到签发；浏览器旧 Cookie 刷新回登录页。 |
| `OVC-P3-04` | 平台管理员停用、团队 owner 降级/移除和成员关系变化共享事务级不变量锁；并发停用/降级测试均只允许一个成功并至少保留一个有效管理员/owner。 |
| `OVC-P3-05` | 注册/重置先查数据库限流再执行 Argon2；成功登录只清账号桶，不清共享 IP 桶；成功邀请/重置只清 token 桶。测试以 monkeypatch 证明被限流请求不会调用哈希，并证明共享 IP 失败记录保留。 |
| `OVC-P3-06` | `/admin` 增加“签发重置”与一次性原始 token 展示；`/members` 增加移出团队、移除作品权限及 403/409 错误反馈。ACL-09 负向测试向实际 `app.routes` 注入未分类路由并断言守卫 exit 1，再移除并断言 exit 0。真实浏览器闭环见 `07-browser-trace.md`。 |

额外加固：异步 adaptation/script 回写在应用结果前锁定 job，并核对 job、marker、project、production、workspace 完整来源链，防止错误作品的迟到任务结果写入。

## 3. 正式验证

所有正式结果都绑定业务 SHA `a8cd59e8247b915737084383f5b53df1f831f4fe`。

| 验证 | 结果 |
|---|---:|
| `python -m pytest tests/test_p3_identity_acl.py -q` | **12 passed**，2 个已知 websockets deprecation warning，exit 0 |
| `python -m pytest -q` | **288 passed**，相同 2 warning，exit 0 |
| `npm test` | **126 passed / 0 failed**，exit 0 |
| `npm run build` | **1825 modules**，exit 0；仅既有 chunk-size warning |
| `python scripts/audit_routes.py` | **85/85** API 已分类，0 未分类，OpenAPI null，exit 0 |
| `python -m compileall -q backend migrations scripts tests` | exit 0 |
| 双浏览器隔离闭环 | viewer 可见、双团队隔离、旧 session 失效、新密码登录、撤权后不可见；清理完成 |

原始/结构化输出位于本目录 `01-p3-r1-targeted.log` 至 `08-browser-db-audit.json`。测试使用专用临时 PostgreSQL，不打印 DSN、密码、token 或 Cookie。

## 4. 测试覆盖索引

新增五个 P3-R1 测试分别覆盖：登录/重置竞态、限流先于哈希及共享 IP 桶、最后平台管理员并发保护、团队撤权/作品授权竞态与孤立行读防御、最后 owner 并发保护。原 ACL 矩阵补充批量章节删除正反路径；ACL-09 改为实际注册路由注入。测试名和行号可直接由 `tests/test_p3_identity_acl.py` 复核。

## 5. 真实浏览器证据

独立端口 7894 和独立数据库上，Chrome 管理员与 Edge 成员完成邀请、注册、入组、viewer 授权、双团队切换、刷新隔离、密码重置、旧会话失效、新密码登录和撤权。管理页同时验证重置、移出团队、移除作品权限三个新控件。最终审计动作与成员关系见 `08-browser-db-audit.json`；临时服务和数据库已清理，7868 未触碰。

## 6. 已知非阻塞项

- 两个 warning 来自 Uvicorn 依赖的 websockets 旧接口；本轮 SSE 断言通过。
- 前端仍有既有大 chunk 构建 warning；构建成功。
- `OVC-P1-R3-N01` 与 `OVC-P2-R2-N01` 继续保留为未归因的非阻塞观察，本轮不伪造根因结论。
- 开发阶段曾发现列表读取孤立作品角色的失败，已在 `ATTEMPT_HISTORY.md` 如实保留。

## 7. 外部复验请求

请只审查协作版新仓库 `https://github.com/imherro/OurVideoCreator` 的 `master`：先看本报告和 `SUMMARY.md`，再看六项阻塞对应代码、`01-p3-r1-targeted.log`、`02-pytest-full.log`、`07-browser-trace.md` 与实际 diff。

请给出 P3-R1 “通过/不通过”、逐项关闭结论和严重级别。只有 P3-R1 通过时才授权 P4；P4 应按“平台统一 Provider/Key/模型后台”定义。
