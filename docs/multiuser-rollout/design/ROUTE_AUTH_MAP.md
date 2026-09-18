# P3/P4 路由认证与授权地图

实际注册源：`backend/app.py`。P3 已切换为个人数据库 session、CSRF 和 Workspace/Production 服务端授权；“Signed”表示不依赖用户 Cookie、但绑定素材/方法/用途/期限的 HMAC capability。`scripts/audit_routes.py` 以实际 `app.routes` 为输入，任何未在本文分类的 `/api` 路由都会令检查失败。

目标角色缩写：PA=platform_admin，WO=workspace owner，PM=production manager，ED=对象 editor，VI=viewer，SYS=受限系统身份。

## 平台模型（P4 实施中）

| 方法与路径 | 服务端守卫 | 数据与副作用 |
| --- | --- | --- |
| GET `/api/models` | 已登录 | 仅安全模型目录；无凭证/URL/上游标识 |
| GET `/api/admin/model-providers` | PA | 私有配置及凭证版本状态，不含密文或明文 |
| POST `/api/admin/model-providers` | PA + CSRF | 配置/凭证/审计同事务新建 |
| PUT `/api/admin/model-providers/{provider_id}` | PA + CSRF | 乐观版本更新/显式轮换 |
| POST `/api/admin/model-providers/{provider_id}/check` | PA + CSRF | 格式/解密/DNS 检查，无 HTTP 鉴权/生成 |
| POST `/api/admin/model-providers/{provider_id}/credentials/{credential_id}/revoke` | PA + CSRF | 吊销明确版本，保留引用 |
| GET `/api/admin/models` | PA | 模型版本管理视图 |
| POST `/api/admin/models` | PA + CSRF | 模型/默认选择/审计同事务新建 |
| PUT `/api/admin/models/{model_id}` | PA + CSRF | 乐观版本编辑、发布、启停 |
| PUT `/api/admin/prompt-templates/{tid}` | PA + CSRF | 提示词版本/审计原子写入，旧写路径返回 410 |

旧入口切换与全部创作路径接线仍在 P4 实施中，不据此表宣称整阶段已完成。

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
| POST `/api/projects/{pid}/audio-jobs` | Session | Production editor；全部音频模型/参数/素材验证后同事务入队 | P3/P4 |
| POST `/api/projects/{pid}/jobs` | Session | 对象 assignee/PM/WO + model/quota；可能付费 | P3/P4/P6 |
| POST `/api/projects/{pid}/run` | Session | 逐对象授权、版本校验、原子批次；可能多次付费 | P3/P5/P6 |
| GET `/api/projects/{pid}/jobs` | Session | Production 成员，只得有权任务 | P3 |
| GET `/api/jobs/{jid}` | Session | 由 job -> production 反查授权 | P3 |
| POST `/api/jobs/{jid}/cancel` | Session | 发起者/对象 manager；远端可能继续计费 | P3/P6 |
| POST `/api/jobs/{jid}/resume` | Session | 保留 P3 提交者/作品角色边界，并在身份锁及任务锁后核当前对象负责人/原分配代际；有远端句柄只恢复查询；无句柄重排必须原目标及引用/设置版本不变，否则要求新任务；无协作快照旧任务 410。预占/配额仍属 P6 | P3/P5/P6 |
| GET `/api/events` | Session | 按会话的 Production 权限过滤，定期复核 | P3/P7 |
| POST `/api/productions/{production_id}/source-extractions` | Session | 已在原著组登记；任务副作用交叉索引 | P3/P6 |

`source-extractions` 只在总路由计数中计算一次。

## FastAPI 框架与前端入口

| 实际注册项 | 当前 | 目标/副作用 | 阶段 |
|---|---|---|---|
| `openapi_url=None` | Disabled | P3 默认不注册 `/openapi.json`，避免泄露管理面 | P3/P7 |
| Mount `/` -> `dist` | 仅 build 后注册，Public | SPA 静态文件公开；API/素材仍由前述服务端授权，不得把私有素材放入 dist | P1/P7 |

应用同时设置 `docs_url=None`、`redoc_url=None`、`openapi_url=None`。`dist` 不存在时只缺少根 `StaticFiles` Mount；全部 `/api` 入口仍注册。build 完成后实际 `app.routes` 多一个根 Mount，且因为它最后注册，不覆盖前面的 API 匹配。

## P5 对象命令（实施中）

所有对象路由同时校验 URL Episode、真实对象 Production、当前有效个人 session 与成员关系。修改事务取得身份共享锁和对象行锁后再次复核，不能仅依赖中间件的请求开始时检查。对象权限与整个 P5 尚在集成，不表示阶段完成。

| 方法与路径 | 权限和对象边界 |
|---|---|
| GET `/api/projects/{pid}/objects` | viewer+，只列本 Episode 及本 Production 共享视觉卡 |
| POST `/api/projects/{pid}/objects` | editor+，新对象初始归当前用户，拒绝伪造作者/租户 |
| GET `/api/projects/{pid}/objects/{oid}` | viewer+，真实父级复核 |
| PATCH `/api/projects/{pid}/objects/{oid}` | 当前 assignee + editor，revision/epoch；timeline 另需有效 lease |
| POST `/api/projects/{pid}/objects/batch` | 每项 assignee/revision/epoch/reference 检查，全部通过才写入 |
| POST `/api/projects/{pid}/objects/commands` | 创建/修改/删除和结构变更原子命令；全部对象权限、版本、引用先验证；不接收整份项目 |
| POST `/api/projects/{pid}/objects/{oid}/assign` | manager/owner 显式分配或接管；增加 epoch 并撤销租约 |
| POST `/api/projects/{pid}/objects/{oid}/lease` | timeline 当前负责人，acquire/renew/release，锁后检查时间与 token/epoch |
| POST `/api/projects/{pid}/objects/{oid}/review` | assignee 提交；manager/owner 确认/退回指定 revision |
| GET `/api/projects/{pid}/objects/{oid}/history` | viewer+，与当前对象相同边界 |
| POST `/api/projects/{pid}/objects/{oid}/restore` | assignee、版本与必要 lease；恢复产生新 revision |
| GET `/api/projects/{pid}/objects/{oid}/comments` | viewer+，与当前对象相同边界 |
| POST `/api/projects/{pid}/objects/{oid}/comments` | viewer+；仅 append 评论，不能修改内容 |
| PATCH `/api/projects/{pid}/metadata` | manager/owner；小白名单、expected_revision；拒绝整份 document 和对象字段 |
| POST `/api/projects/{pid}/script-promotion` | 当前自由文本节点及正式剧本负责人；节点/图结构/剧本 revision 与 epoch；同事务保存剧本并移除自由节点主源 |
| POST `/api/projects/{pid}/director-captures` | 当前导演台负责人及 editor；导演台/图结构 revision 与 epoch；同集图片素材校验后原子建节点和更新结构 |
| GET `/api/projects/{pid}/candidates/{jid}` | viewer+；任务必须属于当前分集，返回候选与真实父级内的当前目标供比较；分镜额外列明整集替换范围、旧镜头负责人/版本与待移除编号 |
| POST `/api/projects/{pid}/candidates/{jid}/adopt` | 章节/剧本/节点/镜头/视觉卡当前负责人；改编 manager；任务成功、revision/epoch、来源版本及明确旧结果采纳检查，主数据/历史/事件/采纳收据同事务；视觉/音色/对白仅采纳该任务服务端已登记且未删除素材；分镜核原镜头集合及所有被替换镜头负责人，移除旧镜头还须 manager/owner；新卡/子节点/graph 同事务，旧视觉卡及音色保留；纯导出不采纳 |
| PATCH `/api/productions/{production_id}/context` | manager/owner；风格/模型策略/故事设定小白名单；拒绝 visual/voices 对象 |

## 覆盖核对

### R1 五角色作品分工（仅显式启用的作品）

补齐此前已实现的单入口分类（不改变运行权限）：

| 方法与路径 | 权限和对象边界 |
|---|---|
| GET `/api/admin/provider-presets` | 平台管理员；四家快捷配置安全投影，不返回明文凭证 |
| POST `/api/admin/provider-presets/{preset_id}` | 平台管理员、CSRF、配置 revision；凭证与默认模型同事务保存，不发起生成 |
| POST `/api/projects/{pid}/objects/{oid}/visual-versions/{version_id}/restore` | 当前资产负责人、对象 revision/epoch；校验历史版本与引用，不复活旧分配 |
| POST `/api/projects/{pid}/assets/{aid}/voice-reference` | 当前作品授权及关联音色对象负责人；服务端确认素材归属，非任意 URL |
| POST `/api/projects/{pid}/image-spec` | 作品 viewer+；模型池与参数编译预览，不写数据、不调用 Provider |
| POST `/api/projects/{pid}/video-spec` | 作品 viewer+；真实镜头、模型池、引用与参数编译预览，不发起生成 |
| POST `/api/productions/{production_id}/sources/{source_id}/chapters/import` | 旧 editor+；五角色为编剧；父作品核验，只追加章节并按默认编剧确定新负责人 |
| GET `/api/productions/{production_id}/source-extractions` | 作品 viewer+；读取当前作品章节提取任务投影 |
| POST `/api/productions/{production_id}/adaptation/episodes/{episode_no}/review` | 旧 manager；五角色默认编剧；保存版本检查，仅改当前集规划状态 |
| POST `/api/productions/{production_id}/adaptation/episodes/{episode_no}/approve` | 旧 manager；五角色默认编剧；保存版本检查，不作为制片人剧本审批 |
| POST `/api/productions/{production_id}/adaptation/episodes/{episode_no}/generate` | 旧 manager；五角色默认编剧；模型池、来源及分工快照，结果为待采纳候选 |
| POST `/api/productions/{production_id}/episode-scripts/{episode_no}/assist` | 当前剧本负责人、模型池与任务准入；五角色额外核编剧角色，返回候选不自动写正文 |

| 方法与路径 | 权限和对象边界 |
|---|---|
| GET `/api/productions/{production_id}/workflow` | 当前有效作品成员只读；仅制片人返回可添加的团队成员列表 |
| POST `/api/productions/{production_id}/workflow/enable` | 旧作品 manager/owner 显式启用；现有负责人及内容保留，不升级 Workspace 权限 |
| PUT `/api/productions/{production_id}/workflow/members/{user_id}` | 当前制片人、有效团队成员、分工 revision；固定五角色；撤权同步清空对应分配并递增代际；保留最后一名制片人 |
| PUT `/api/productions/{production_id}/workflow/defaults` | 制片人、分工 revision；目标具备对应角色；仅改变后续新增内容默认归属 |
| PUT `/api/productions/{production_id}/workflow/episodes/{project_id}` | 制片人、分工 revision、真实父作品；整集制作范围原子转交及旧租约失效，特殊分配先确认；不转交共享资产与剧本 |
| POST `/api/productions/{production_id}/workflow/assign` | 制片人、分工及逐项 revision/epoch；按章节/资产业务清单批量分配，全部成功或全部回滚 |
| GET `/api/productions/{production_id}/workflow/reviews` | 五角色作品有效成员只读；返回当前剧本与共享资产明确版本 |
| POST `/api/productions/{production_id}/workflow/reviews/assets` | 资产师提交自己的资产；制片人批准或退回；每项版本/代际核验、批次原子成功或回滚；复用对象历史 |

启用五角色后，上述历史条目中的 manager 写权限由作品制片人承担，不赋予 Workspace owner；正文仍要求业务角色与实际负责人。原著/章节软删除由编剧执行并校验全部目标负责人及版本。改编策划及其候选采纳由默认编剧执行；任务冻结分工修订，分工变更后旧任务不能沿用旧票据恢复。供应商/凭证/模型目录仍仅平台管理员管理。

### P5 既有关系表内容入口

| 方法与路径 | 权限和对象边界 |
|---|---|
| GET `/api/productions/{production_id}/owned-content/{kind}/{target_id}` | viewer+，关系表对象最新版本只读查询，真实父作品复核 |
| POST `/api/productions/{production_id}/owned-content/{kind}/{target_id}/restore` | 当前负责人和 revision/epoch；复核历史来源，正文恢复为新版本，状态回进行中 |
| POST `/api/productions/{production_id}/owned-content/{kind}/{target_id}/assign` | kind 仅 chapter/script；manager 显式分配，revision/epoch 校验，作者由会话决定 |
| GET `/api/productions/{production_id}/owned-content/{kind}/{target_id}/history` | viewer+，章节/剧本真实父作品复核 |
| GET `/api/productions/{production_id}/owned-content/{kind}/{target_id}/comments` | viewer+，相同对象归属校验 |
| POST `/api/productions/{production_id}/owned-content/{kind}/{target_id}/comments` | viewer+，仅追加评论，不写对象正文 |
| POST `/api/productions/{production_id}/owned-content/{kind}/{target_id}/review` | chapter：负责人提交、manager 确认/退回指定 revision/epoch；script 使用原正式审核小接口 |

既有章节和剧本 PUT 要求当前 assignee、revision 与 assignment_epoch；剧本 review 要求负责人，approve/needs-changes 要求 manager。分配、撤权复用 P3 身份锁，不能凭管理者角色静默写正文。

原著 DELETE 必须提交全部存活章节的 revision/assignment_epoch，管理者须先显式接管各章；章节批量 trash 全批校验权限和版本后才删除，单章 DELETE 也必须提交版本/epoch。改编 PUT/review/approve 在事务内限制 manager，GET 不再隐式写回。

P5 回收站：分集、原著、章节和素材删除/恢复先取既有 P3 身份排他屏障，并在事务中复核当前会话及 manager，不能凭请求开始时的旧权限执行。分集删除/恢复各递增本集对象、正式剧本及分集元数据版本，同时递增对象/剧本 assignment_epoch、清除时间线旧租约；作品共享视觉卡不受影响。原著/章节只递增章节编辑代际并保留正文/负责人。恢复不绕过原著/素材所属分集的父级回收站检查，不复活单独删除的章节。素材 ID/文件保留，分类编辑用共享身份屏障与生命周期互斥；不引入新租约体系。

P3 新增 18 个身份/成员入口，当前总数由脚本按实际注册项计算。脚本在临时 `MVC_DATA_DIR` 中导入应用、导出实际 `app.routes`、逐个核对本文的方法+路径分类，并额外捕获可选静态 Mount；发现任一未分类 `/api` 路由时返回非零。负向测试会注入虚构新路由，证明 ACL-09 守卫确实失败。

## P3 后续阶段边界

1. P3 已把现有 Provider/Key 写入口限为 PA，并向普通用户返回安全投影；P4 再迁入版本化加密凭证与正式模型目录。
2. P3 已对 job、asset、revision、trash、SSE 及嵌套 ID 施加 Production 授权；P5 继续细化 assignee 与对象级协作。
3. `PUT /api/projects/{pid}` 在 P3 仅 WO/PM 可用，editor 无法借旧整份写旁路；P5 将彻底退役协作写路径。
4. 任务提交在 P3 复用当前个人/作品权限；多 Worker 执行前二次授权、额度与 fencing 在 P6 完成。
