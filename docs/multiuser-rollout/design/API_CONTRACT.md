# P0 协作 API 契约草案

本文件冻结行为，不在 P0 实现路由。最终命名可在保持语义和验收能力的前提下调整。

## P5 实际接口补充（优先于下方 P0 路径草案）

下方保留原冻结语义；实际命名和当前阶段边界如下。P5 尚待外部验收，不能将未来 quota/多 Worker 契约读成已实现。

| 实际命令 | 请求与边界 |
|---|---|
| `GET /api/projects/{pid}/objects`、`GET .../objects/{oid}` | 本作品/分集的已授权对象集合与详情；对象 kind 为 shot/node/visual_card/graph/timeline/director；不泄漏 lease token 摘要 |
| `POST .../objects` | `{kind, content}`，服务端确定作者、归属和初始负责人；创建 node/shot 同时核 graph 结构版本 |
| `PATCH .../objects/{oid}` | `{expected_revision, assignment_epoch, content}`；timeline 另需 `lease_token, lease_epoch`；严格 envelope，拒绝伪造身份及跨作品嵌套引用 |
| `POST .../objects/commands` | `{creates, updates, deletes}`，更新/删除逐项携带版本和代际；单事务全成或全败，不能夹带无权对象 |
| `POST .../objects/{oid}/assign` | manager/owner 明确分配或接管；携带当前 revision/epoch 和 assignee_id；递增代际并撤销旧 lease，不授予隐式内容编辑权 |
| `POST .../objects/{oid}/lease` | acquire/renew/release；renew/release 带 token/lease_epoch；仅 timeline。强制接管通过明确 assign（含接管给自己）使旧租约失效，再 acquire |
| `POST .../objects/{oid}/review`、`.../restore` | 审核 action 为 submit/approve/return；恢复携带目标历史 revision；两者仍需当前 expected_revision/assignment_epoch，恢复新增 revision |
| `GET .../objects/{oid}/history`、`GET/POST .../comments` | 同作品授权；viewer 可 append 评论但不能夹带内容/审核字段 |
| `.../productions/{production_id}/owned-content/{chapter\|script}/{target_id}` | 复用原章节/正式剧本主源；提供详情、assign、history、restore、comments；正文沿用既有 scoped 小接口并补 expected revision/epoch。正式剧本沿用 readiness-aware 审核接口 |
| `PATCH /api/projects/{pid}/metadata`、`PATCH /api/productions/{production_id}/context` | manager/owner 受限字段 PATCH + expected_revision，不能夹带对象、视觉卡、音色或整份 document |
| `POST .../projects/{pid}/script-promotion`、`.../director-captures` | 原子校验相关对象/结构及真实素材；不把上传或图片渲染放入数据库事务 |
| `GET .../projects/{pid}/candidates/{jid}`、`POST .../adopt` | GET 只读比较；POST 明确采纳，当前权限和 expected revision/epoch 再核验，必要时显式 accept_stale；来源依赖不一致仍拒绝，收据/对象/历史/事件同事务 |
| `PUT /api/projects/{pid}` | 权限层先检查；有权 manager/owner 也收到 410，editor 不能借此取得协作写入权；聚合 GET 保留 |

前端 SSE 获取当前已授权 objects 快照后逐对象核 revision/草稿并一次合并投影，避免同一结构事务中的节点与 graph 事件先后到达制造本地修改。不会用整份读取结果写回数据库。当前仍为单 Worker；P5 只落实协作目标/候选版本边界，额度预占与多 Worker fencing 属 P6。

## 通用规则

- 身份来自服务端 session cookie；客户端不能提交 `user_id`、角色、workspace 归属、作者或 assignee 作为权威值。
- 所有资源 URL 由父级 scope 导航，例如 `/api/workspaces/{wid}/productions/{production_id}/...`；服务端仍要核对每级真实关联，不能只信路径。
- 写请求使用 CSRF 防护、JSON schema/字段白名单和服务端能力校验。
- 对象更新必须携带 `expected_revision`。数据库以 `UPDATE ... WHERE id=? AND revision=?` 原子更新；0 行更新返回 `409`。
- `409` 返回安全的当前 revision、更新时间和冲突类型，不自动拿最新 revision 重发旧内容。
- 创建/更新/审核/恢复在同一短事务写主对象、历史、审计和 domain event。
- 列表分页并强制 workspace/production scope；不存在和无权可统一返回 404 以减少枚举。
- 批量命令先校验所有对象权限与 revision，第一版默认全成或全败。

## 身份和管理

| 方法/草案 | 行为 |
|---|---|
| `POST /api/auth/register` | 消费一次性邀请并创建未验证手机号账号；事务失败不消费邀请 |
| `POST /api/auth/login/logout` | 个人可撤销 session；登录/兑换/重置共享限速 |
| `POST /api/admin/invitations` | platform_admin 创建摘要存储的邀请码 |
| `POST /api/admin/password-resets` | 管理员线下核验后签发短期一次性链接 |
| `POST /api/admin/workspaces` | 创建 Workspace 并指定 owner |
| `PUT /api/workspaces/{wid}/members/{uid}` | owner 管理已有账号成员关系 |
| `PUT /api/productions/{pid}/members/{uid}` | owner/manager 管理作品成员，目标必须先属于 Workspace |
| `POST /api/workspaces/{wid}/productions` | workspace owner 创建 Production 并指定 manager；平台管理员只走显式审计后台 |
| `POST /api/productions/{pid}/episodes` | owner 或该 Production manager 创建 Episode |

当前 `POST /api/projects` 会在同一事务创建 Production 与首个 Episode，不是 Episode-only 命令。P3 兼容期它必须等同“创建 Production”仅允许 workspace owner，随后由上述两个显式命令替代并退役；不得赋权给仅管理其他 Production 的 manager。

## 对象保存

| 对象 | 读 | 写/命令 | 并发语义 |
|---|---|---|---|
| Episode script | `GET .../episode-scripts/{id}` | `PATCH` body `{expected_revision, patch}`；review/approve/needs-changes 命令 | revision |
| Shot | `GET .../shots/{id}` | `PATCH`；assign/takeover；review/approve | revision + assignment epoch |
| Visual card/version | `GET .../visual-cards/{id}` | card `PATCH`；version fork/lock/deprecate/bind | 锁定版本不可变；card revision |
| Timeline | `GET .../timelines/{episode}` | `PATCH` 携带 revision + lease token；acquire/renew/release/takeover | revision + lease epoch |
| Source/chapter | scoped list/detail | create/patch/trash/restore | revision |
| Graph structure | scoped read | 小范围 node/edge 命令或 structure patch | structure revision |
| Comment | scoped list | append；有限删除策略 | append-only |
| Director stage | `GET .../episodes/{id}/director-stage` | `PATCH` stage；capture 命令另校验素材上传与图像节点创建权限 | episode revision（不需独占 lease） |
| Voice profile | 随 Visual card 读取 | card assignee `PATCH` profile；lock/accept-result 命令 | visual card revision + 结果基线 revision |
| Prompt template | scoped platform catalog | 第一版仅 PA create/update/archive | template revision + append-only history |
| Legacy simple timeline | 作为 Timeline v1 投影读取 | 不再独立写；一次性转换为 editor timeline command | editor timeline revision + lease |

审核状态为 `in_progress -> pending_review -> completed`。审核绑定具体 revision；已完成对象再次编辑产生新 revision 并回到 `in_progress`。版本恢复创建新 revision，不把计数倒退。

## Project.document 退役

1. `GET /api/projects/{episode_id}` 可在过渡期返回只读聚合 `document`。
2. P3 期间现有 `PUT /api/projects/{pid}` 仅允许 owner/manager，且不得被 editor 用作协作旁路。
3. P5 完成时前端所有编辑入口改用对象 API；旧 PUT 对协作字段返回 `410 Gone` 或明确的版本化错误。
4. 禁止把对象表写入后再异步回写 document，或同时接受两套主源。
5. 3D 导演台、固定音色、提示词库、旧简剪与 Twick 的字段级迁移和旧入口退役细节以 `DATA_OWNERSHIP.md` 的“旧可写载体闭合映射”为准。

## 任务提交

- 客户端只能提交平台 `model_id`、允许的业务输入和 idempotency key；不得覆盖 provider、base_url、api_key、上游模型、headers 或凭证版本。
- idempotency scope 为 `(workspace_id, actor_user_id, endpoint_namespace, key)`，并绑定规范化有效输入 hash；同键同输入返回原 job，不重复占额，不同输入 `409`。
- 入队事务同时完成权限复核、模型能力校验、quota 预占、job/子调用计划写入。
- job 冻结对象 revision、assignee epoch、模型版本、凭证版本和允许参数；结果先登记候选。
- 任务查询、取消、恢复、结果素材、SSE 都重新核对作品权限；付费在途归档使用受限系统身份。

## 文件与事件

- Asset API 使用稳定 asset_id，逐资源核对 Workspace/Production 权限；Range 与缩略图同样授权。
- Provider capability 至少绑定 asset_id、方法、用途、过期时间和随机/版本信息；支持撤销语义。
- SSE 事件带 workspace/production/object scope，仅返回当前会话仍有权的事件；最多每 5 秒复核会话与成员状态。
- 过旧 cursor 返回 resync 信号，而不是无限历史重放。
