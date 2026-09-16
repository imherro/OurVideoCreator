# P0 路由认证与授权地图

实际注册源：`backend/app.py`，共 **69** 条业务路由。当前认证只有共享工作室 session。表中“Session”表示仅检查共享 cookie，没有 Workspace/Production/对象权限；“Signed”表示 HMAC 素材 capability。

目标角色缩写：PA=platform_admin，WO=workspace owner，PM=production manager，ED=对象 editor，VI=viewer，SYS=受限系统身份。

## 健康与身份（5）

| 方法与路径 | 当前 | 目标/副作用 | 阶段 |
|---|---|---|---|
| GET `/api/health` | Public | 公开最小健康，不泄露配置 | P1/P7 |
| GET `/api/auth/status` | Public | 当前用户最小状态 | P3 |
| POST `/api/auth/setup` | Public | **退役**；改为受保护 CLI 初始管理员 | P3 AUTH-01 |
| POST `/api/auth/login` | Public | 个人账号登录、共享限速 | P3 |
| POST `/api/auth/logout` | Session | 当前个人 session 注销 | P3 |

## Production、Episode 与项目文档（15）

| 方法与路径 | 当前 | 目标/副作用 | 阶段 |
|---|---|---|---|
| GET `/api/projects` | Session | 仅参与 Production 的 Episode 列表；WO 可见本团队 | P3 |
| GET `/api/productions` | Session | 同上按 Workspace scope | P3 |
| POST `/api/productions` | Session | PA/WO 创建 Production | P3 |
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

| 方法与路径 | 当前 | 目标/副作用 | 阶段 |
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

## 系统、Provider 与提示词（10）

| 方法与路径 | 当前 | 目标/副作用 | 阶段 |
|---|---|---|---|
| GET `/api/system` | Session | 删除本地硬件/模型细节；普通用户只得安全能力 | P1/P4 |
| GET `/api/settings` | Session | 普通入口退役；安全模型目录另设 | P4 |
| PUT `/api/settings` | Session | 退役；仅 PA 管理 API 可写 | P4 |
| POST `/api/runtime/unload` | Session | 移除 | P1 |
| POST `/api/runtime/maestro/start` | Session | 移除 | P1 |
| GET `/api/providers/{provider_id}/models` | Session | PA 管理目录或普通安全 catalog；无 Key | P4 |
| POST `/api/providers/{provider_id}/verify` | Session | PA；只做无生成验证 | P4 |
| POST `/api/providers/{provider_id}/test` | Session | PA；当前只检测配置模型，不得付费生成 | P4 |
| GET `/api/prompt-library` | Session | 普通用户只读平台已启用模板 | P4 |
| PUT `/api/prompt-library/{tid}` | Session | 退役；仅 PA 使用后台模板 revision 命令 | P4 |

## 原著、章节、事件与改编（23）

| 方法与路径 | 当前 | 目标/副作用 | 阶段 |
|---|---|---|---|
| GET `/api/productions/{production_id}/sources` | Session | Production 成员 | P3 |
| POST `/api/productions/{production_id}/sources` | Session | 分配到自己或 PM/WO | P3/P5 |
| POST `/api/productions/{production_id}/sources/import` | Session | 同上；上传/文本限制 | P3/P7 |
| DELETE `/api/productions/{production_id}/sources/{source_id}` | Session | 负责人/PM/WO；软删除 | P3/P5 |
| POST `/api/productions/{production_id}/chapters/trash` | Session | 批量原子授权 | P3/P5 |
| DELETE `/api/productions/{production_id}/chapters/{chapter_id}` | Session | 负责人/PM/WO | P3/P5 |
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

| 方法与路径 | 当前 | 目标/副作用 | 阶段 |
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
| GET `/openapi.json` | Public（FastAPI 默认） | 开发环境受限；生产默认关闭或仅 PA 可访问，不得泄露管理面 | P3/P7 |
| Mount `/` -> `dist` | 仅 build 后注册，Public | SPA 静态文件公开；API/素材仍由前述服务端授权，不得把私有素材放入 dist | P1/P7 |

`docs_url=None` 与 `redoc_url=None` 不会关闭默认 `/openapi.json`。`dist` 不存在时只缺少根 `StaticFiles` Mount；69 个 `/api` 入口与 OpenAPI 路由仍注册。build 完成后实际 `app.routes` 多一个根 Mount，且因为它最后注册，不覆盖前面的 API 匹配。

## 覆盖核对

业务表去重后覆盖 69 个 `/api` 装饰器入口：5+15+9+10+23+7=69。`scripts/audit_routes.py` 在临时 `MVC_DATA_DIR` 中导入应用并导出实际 `app.routes`，并逐个核对本文中的方法+路径分类，额外捕获 `/openapi.json` 与可选静态 Mount；首次模块路径失败保留在 `evidence/P0-R1/06-route-audit.log`，最终完整输出见 `11-route-audit-classification.log`。成功输出为 71 个注册项：69 API + 1 OpenAPI + 1 build 后静态 Mount，69 个 API 全部已分类且框架入口已登记。P3 应把同一枚举升级为 CI 授权登记守卫；任何新增未分类资源路由使测试失败（ACL-09）。

## 当前最高风险缺口

1. 任意已登录者可写全局 Provider/Key 设置并控制 runtime。
2. job id、asset id、revision id 和 trash 条目只凭 ID 读取或操作。
3. SSE 广播全部事件，没有租户/作品过滤。
4. `PUT /api/projects/{pid}` 可修改整份 document，未来 editor 会形成越权旁路。
5. 任务提交虽检查素材 Production 一致性，但没有用户、角色、额度和平台 model_id 边界。
