# P3 路由认证与授权地图

实际注册源：`backend/app.py`。P3 已切换为个人数据库 session、CSRF 和 Workspace/Production 服务端授权；“Signed”表示不依赖用户 Cookie、但绑定素材/方法/用途/期限的 HMAC capability。`scripts/audit_routes.py` 以实际 `app.routes` 为输入，任何未在本文分类的 `/api` 路由都会令检查失败。

目标角色缩写：PA=platform_admin，WO=workspace owner，PM=production manager，ED=对象 editor，VI=viewer，SYS=受限系统身份。

## 健康与身份（7）

| 方法与路径 | P3 强制 | 目标/副作用 | 阶段 |
|---|---|---|---|
| GET `/api/health` | Public | 公开最小健康，不泄露配置 | P1/P7 |
| GET `/api/auth/status` | Public | 当前用户最小状态 | P3 |
| POST `/api/auth/setup` | Public | **退役**；改为受保护 CLI 初始管理员 | P3 AUTH-01 |
| POST `/api/auth/login` | Public | 个人账号登录、共享限速 | P3 |
| POST `/api/auth/logout` | Session | 当前个人 session 注销 | P3 |
| POST `/api/auth/register` | Public | 一次性邀请注册；不自动入组 | P3 |
| POST `/api/auth/password-reset` | Public | 消费短期重置令牌并撤销旧 session | P3 |

## P3 平台、团队与作品成员管理（16）

| 方法与路径 | P3 授权 | 副作用 |
|---|---|---|
| GET `/api/admin/invitations` | PA | 邀请摘要，不返回原始令牌 |
| POST `/api/admin/invitations` | PA | 签发一次性邀请，原始值仅返回一次 |
| DELETE `/api/admin/invitations/{invitation_id}` | PA | 撤销未消费邀请 |
| GET `/api/admin/users` | PA | 平台账号目录 |
| PATCH `/api/admin/users/{user_id}` | PA | 启停账号；保护最后管理员 |
| POST `/api/admin/password-resets` | PA | 人工核验后签发一次性重置令牌 |
| GET `/api/workspaces` | User | 只列当前用户团队 |
| GET `/api/admin/workspaces` | PA | 平台团队与 owner 清单；显式后台入口 |
| POST `/api/admin/workspaces` | PA | 创建团队并指定 owner，审计 |
| GET `/api/workspaces/{workspace_id}/members` | Workspace member | owner 可见必要手机号，其他成员脱敏 |
| PUT `/api/workspaces/{workspace_id}/members/{user_id}` | WO | 已注册用户确认入组 |
| DELETE `/api/workspaces/{workspace_id}/members/{user_id}` | WO | 撤销作品成员关系，保护最后 owner |
| GET `/api/productions/{production_id}/members` | Production member/WO | 作品成员列表 |
| PUT `/api/productions/{production_id}/members/{user_id}` | PM/WO | 目标必须先是团队成员 |
| DELETE `/api/productions/{production_id}/members/{user_id}` | PM/WO | 移除作品成员 |
| GET `/api/admin/audit-events` | PA | 显式后台审计查询 |

## Production、Episode 与项目文档（15）

| 方法与路径 | P3 强制 | 目标/副作用 | 阶段 |
|---|---|---|---|
| GET `/api/projects` | Session | 仅参与 Production 的 Episode 列表；WO 可见本团队 | P3 |
| GET `/api/productions` | Session | 同上按 Workspace scope | P3 |
| POST `/api/productions` | Session | 仅 WO 创建 Production；PA 无普通查询旁路 | P3 |
| PATCH `/api/productions/{production_id}` | Session | WO/PM + revision | P3/P5 |
| GET `/api/productions/{production_id}` | Session | Production 成员；WO | P3 |
| GET `/api/productions/{production_id}/episodes` | Session | Production 成员 | P3 |
| GET `/api/productions/{production_id}/visual-usage` | Session | Production 成员 | P3 |
| POST `/api/productions/{production_id}/episodes` | Session | WO/PM | P3 |
| POST `/api/projects` | Session | 当前同时创建 Production+首集；兼容期仅 WO，之后退役；PA 只走审计后台 | P3 |
| GET `/api/projects/{pid}` | Session | 参与者只读聚合 | P3/P5 |
| DELETE `/api/projects/{pid}` | Session | WO/PM；软删除审计 | P3 |
| GET `/api/projects/{pid}/storyboard-sheet` | Session | Production 成员；文件读取 | P3/P7 |
| PUT `/api/projects/{pid}` | Session | P3 暂限 WO/PM；P5 退役协作写旁路 | P3/P5 |
| GET `/api/projects/{pid}/revisions` | Session | Production 成员；对象化后按权限 | P3/P5 |
| GET `/api/projects/{pid}/revisions/{rid}` | Session | 同上，不得跨作品读 | P3/P5 |

`POST /api/projects` 不是“在已有作品加一集”；代码会新建 Production。PM 只能调用 `POST /api/productions/{production_id}/episodes` 在其管理的既有作品内新增分集。

## 素材、文件与回收站（9 个唯一入口，另列 1 个交叉索引）

| 方法与路径 | P3 强制 | 目标/副作用 | 阶段 |
|---|---|---|---|
| GET `/api/projects/{pid}/assets` | Session | Production 成员；scope 参数不能越权 | P3 |
| GET `/api/productions/{production_id}/assets` | Session | Production 成员 | P3 |
| POST `/api/projects/{pid}/assets` | Session | 有编辑权；文件大小/类型/像素检查 | P3/P7 |
| PATCH `/api/projects/{pid}/assets/{aid}` | Session | ED/PM/WO；核对同 Production | P3 |
| DELETE `/api/projects/{pid}/assets/{aid}` | Session | PM/WO 或明确对象策略；软删除 | P3 |
| GET `/api/trash` | Session | 仅有权 Workspace/Production 条目 | P3 |
| POST `/api/trash/{kind}/{item_id}/restore` | Session | PM/WO；逐资源授权与审计 | P3 |
| GET `/api/assets/{aid}/file` | Session | Production 成员；Range 同权限 | P3/P7 |
| GET `/api/provider-assets/{aid}` | Signed | capability 绑定素材/方法/用途/期限/撤销 | P3/P7 |
| GET `/api/productions/{production_id}/visual-usage` | Session | 已在 Production 组登记；涉及素材引用只读 | P3 |

`visual-usage` 只在总路由计数中计算一次；本表为安全域交叉索引。

## 系统、Provider 与提示词（8）

| 方法与路径 | P3 强制 | 目标/副作用 | 阶段 |
|---|---|---|---|
| GET `/api/system` | Session | P1 只返回 external-api / separate-process 状态和模板，不含本地硬件/模型细节 | P1/P4 |
| GET `/api/settings` | Session | 普通入口退役；安全模型目录另设 | P4 |
| PUT `/api/settings` | Session | 退役；仅 PA 管理 API 可写 | P4 |
| GET `/api/providers/{provider_id}/models` | Session | PA 管理目录或普通安全 catalog；无 Key | P4 |
| POST `/api/providers/{provider_id}/verify` | Session | PA；只做无生成验证 | P4 |
| POST `/api/providers/{provider_id}/test` | Session | PA；当前只检测配置模型，不得付费生成 | P4 |
| GET `/api/prompt-library` | Session | 普通用户只读平台已启用模板 | P4 |
| PUT `/api/prompt-library/{tid}` | Session | 退役；仅 PA 使用后台模板 revision 命令 | P4 |

## 原著、章节、事件与改编（23）

| 方法与路径 | P3 强制 | 目标/副作用 | 阶段 |
|---|---|---|---|
| GET `/api/productions/{production_id}/sources` | Session | Production 成员 | P3 |
| POST `/api/productions/{production_id}/sources` | Session | 分配到自己或 PM/WO | P3/P5 |
| POST `/api/productions/{production_id}/sources/import` | Session | 同上；上传/文本限制 | P3/P7 |
| DELETE `/api/productions/{production_id}/sources/{source_id}` | Session | 负责人/PM/WO；软删除 | P3/P5 |
| POST `/api/productions/{production_id}/chapters/trash` | PM/WO | 与单项删除一致；editor/viewer 不得借批量入口绕过 | P3/P5 |
| DELETE `/api/productions/{production_id}/chapters/{chapter_id}` | PM/WO | P3 尚无对象负责人，保持 manager 删除边界 | P3/P5 |
| GET `/api/productions/{production_id}/chapters` | Session | Production 成员 | P3 |
| POST `/api/productions/{production_id}/sources/{source_id}/chapters` | Session | 负责人/PM/WO | P3/P5 |
| PUT `/api/productions/{production_id}/chapters/{chapter_id}` | Session | assignee + expected_revision | P3/P5 |
| GET `/api/productions/{production_id}/source-events` | Session | Production 成员 | P3 |
| POST `/api/productions/{production_id}/source-extractions` | Session | 对象编辑权；创建文本任务/额度 | P3/P6 |
| GET `/api/productions/{production_id}/adaptation` | Session | Production 成员 | P3 |
| PUT `/api/productions/{production_id}/adaptation` | Session | assignee/PM/WO + revision | P3/P5 |
| POST `/api/productions/{production_id}/adaptation/review` | Session | assignee 提交审核 | P3/P5 |
| POST `/api/productions/{production_id}/adaptation/approve` | Session | PM/WO，绑定 revision | P3/P5 |
| POST `/api/productions/{production_id}/adaptation/generate` | Session | 有权对象 + model/quota；付费副作用 | P3/P4/P6 |
| GET `/api/productions/{production_id}/scripts` | Session | Production 成员 | P3 |
| GET `/api/productions/{production_id}/episode-scripts/{episode_no}` | Session | Production 成员 | P3 |
| PUT `/api/productions/{production_id}/episode-scripts/{episode_no}` | Session | assignee + expected_revision | P3/P5 |
| POST `/api/productions/{production_id}/episode-scripts/{episode_no}/review` | Session | assignee | P3/P5 |
| POST `/api/productions/{production_id}/episode-scripts/{episode_no}/approve` | Session | PM/WO | P3/P5 |
| POST `/api/productions/{production_id}/episode-scripts/{episode_no}/needs-changes` | Session | PM/WO | P3/P5 |
| POST `/api/productions/{production_id}/script-generations` | Session | 有权对象 + model/quota；批量付费 | P3/P4/P6 |

## 任务、批量运行与事件（7 个唯一入口，另列 1 个交叉索引）

| 方法与路径 | P3 强制 | 目标/副作用 | 阶段 |
|---|---|---|---|
| POST `/api/projects/{pid}/jobs` | Session | 对象 assignee/PM/WO + model/quota；可能付费 | P3/P4/P6 |
| POST `/api/projects/{pid}/run` | Session | 逐对象授权、版本校验、原子批次；可能多次付费 | P3/P5/P6 |
| GET `/api/projects/{pid}/jobs` | Session | Production 成员，只得有权任务 | P3 |
| GET `/api/jobs/{jid}` | Session | 由 job -> production 反查授权 | P3 |
| POST `/api/jobs/{jid}/cancel` | Session | 发起者/对象 manager；远端可能继续计费 | P3/P6 |
| POST `/api/jobs/{jid}/resume` | Session | 有权且状态允许；无句柄重排队前重新预占/确认 | P3/P6 |
| GET `/api/events` | Session | 按会话的 Production 权限过滤，定期复核 | P3/P7 |
| POST `/api/productions/{production_id}/source-extractions` | Session | 已在原著组登记；任务副作用交叉索引 | P3/P6 |

`source-extractions` 只在总路由计数中计算一次。

## FastAPI 框架与前端入口

| 实际注册项 | 当前 | 目标/副作用 | 阶段 |
|---|---|---|---|
| `openapi_url=None` | Disabled | P3 默认不注册 `/openapi.json`，避免泄露管理面 | P3/P7 |
| Mount `/` -> `dist` | 仅 build 后注册，Public | SPA 静态文件公开；API/素材仍由前述服务端授权，不得把私有素材放入 dist | P1/P7 |

应用同时设置 `docs_url=None`、`redoc_url=None`、`openapi_url=None`。`dist` 不存在时只缺少根 `StaticFiles` Mount；全部 `/api` 入口仍注册。build 完成后实际 `app.routes` 多一个根 Mount，且因为它最后注册，不覆盖前面的 API 匹配。

## 覆盖核对

P3 新增 18 个身份/成员入口，当前总数由脚本按实际注册项计算。脚本在临时 `MVC_DATA_DIR` 中导入应用、导出实际 `app.routes`、逐个核对本文的方法+路径分类，并额外捕获可选静态 Mount；发现任一未分类 `/api` 路由时返回非零。负向测试会注入虚构新路由，证明 ACL-09 守卫确实失败。

## P3 后续阶段边界

1. P3 已把现有 Provider/Key 写入口限为 PA，并向普通用户返回安全投影；P4 再迁入版本化加密凭证与正式模型目录。
2. P3 已对 job、asset、revision、trash、SSE 及嵌套 ID 施加 Production 授权；P5 继续细化 assignee 与对象级协作。
3. `PUT /api/projects/{pid}` 在 P3 仅 WO/PM 可用，editor 无法借旧整份写旁路；P5 将彻底退役协作写路径。
4. 任务提交在 P3 复用当前个人/作品权限；多 Worker 执行前二次授权、额度与 fencing 在 P6 完成。
