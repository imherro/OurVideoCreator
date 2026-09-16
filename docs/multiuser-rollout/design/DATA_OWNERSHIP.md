# P3 数据主源与对象归属

## 语义映射

- `Workspace`：团队，租户隔离边界。
- `Production`：作品/剧集，包含多个分集。
- 当前 `projects`：`Episode`/制作集，不得再建立一个含义冲突的 Project。
- 素材属于 Workspace + Production；`project_id` 可保留来源 Episode，但不是所有权边界。

## 当前物理主源

| 当前表/载体 | 当前主数据 | 当前版本机制 | 问题 |
|---|---|---|---|
| `settings` | Provider/Key、prompt library、FFmpeg 路径 | 部分 JSON revision | P3 仅 PA 可写、普通用户只得安全投影；P4 迁版本化加密凭证 |
| `users/sessions/invitations/password_reset_tokens` | 个人身份、摘要令牌与一次性邀请/重置 | expiry/revocation | P3 已落地；手机号未验证不授予角色 |
| `productions/workspaces/*_members` | 作品名、共享 Film Bible/策略/改编 context 与租户/作品角色 | revision + `production_revisions` | P3 已有 workspace_id 与成员 ACL；P5 再细化对象负责人 |
| `projects` | Episode 元数据和大 `document` JSON | revision + `revisions` | 多对象共享一个写冲突域 |
| `source_documents/source_chapters/source_events` | 原著、章节、提取事件 | 章节 revision；事件替换 | 由 production 归属隔离；P5 增负责人 |
| `episode_scripts` | 一集正式剧本 | revision + revisions | 已接近目标粒度 |
| `assets` | 媒体身份与磁盘 key | 无内容 revision | P3 以 production_id 授权，project_id 仅来源；P7 完成对象存储 |
| `jobs/job_private` | 任务、冻结输入、Provider 快照及 workspace/production/actor scope | status/update time | P3 查询/操作已授权；`job_private` 明文 Key 在 P4 迁除 |
| `events` | 带 workspace/production scope 的 SSE 通知日志 | 自增 cursor | P3 按当前成员过滤并每 2 秒复核；P7 完整复测 |
| `provider_asset_*` | 幻场远端登记映射 | provider/account hash 唯一 | 缺租户/凭证版本显式维度 |
| `deleted_items` | 软删除索引 | 时间戳 | 通用表，授权依赖调用方 |

## 目标权威对象

| 对象 | 权威存储建议 | 归属 | 编辑控制 | 历史/审核 |
|---|---|---|---|---|
| User/Session | `users/sessions/password_reset_tokens` | 全局 user_id | 用户本人/平台管理员受限动作 | 安全审计 |
| Invitation | `invitations` | 平台 | platform_admin | 一次性摘要、过期/撤销 |
| Workspace | `workspaces/workspace_members` | workspace | platform_admin 指定 owner | 管理审计 |
| Production | `productions/production_members` | workspace | owner/manager | metadata revision |
| Episode | `episodes`（可迁移当前 projects 名称） | production | manager 结构权限 | revision |
| Source/Chapter/Event | 关系表 | production | 分配负责人/manager | revision/history |
| Episode Script | `episode_scripts` | episode | 一个 assignee | expected_revision；确认绑定 revision |
| Shot | `shots` | episode/production | 一个 assignee | expected_revision + history |
| Visual Card/Version | `visual_cards/visual_versions` | production | 一个 assignee | 锁定版本不可原改 |
| Graph node/edge/structure | `graph_nodes/graph_edges` + 小结构 revision | episode/production | 镜头节点继承镜头；自由节点独立 | expected_revision |
| Editor timeline | `editor_timelines` | episode | 一个 assignee | revision + 独占短租约 |
| Asset | `assets` | workspace + production，episode 仅来源 | 作品权限 | 稳定 asset_id、不可存临时 URL |
| Comment/Revision/Lease | 独立关系表 | 对应对象 | 按对象权限 | append-only/epoch |
| Provider/Credential/Model | `providers/provider_credential_versions/model_catalog/model_versions` | 平台 | platform_admin | 加密、版本引用、审计 |
| Job/Attempt/Quota/Usage | `jobs/job_attempts/quota_* /usage_events` | workspace + production + actor | service/授权用户 | lease/fencing/ledger |
| Domain event/Audit | `domain_events/audit_events` | workspace/production | 服务写入 | append-only |

## 旧可写载体闭合映射

| 当前字段/函数 | 唯一目标对象与存储 | 归属 | 负责人/动作权限 | 并发 | 保存命令/API | 旧入口退役与验收 |
|---|---|---|---|---|---|---|
| `document.director`，`main.tsx update()` | `episode_director_stages.stage_json` | Workspace→Production→Episode | Episode 的 director assignee 可改；PM/WO 显式接管；capture 还需素材上传和图像节点创建权 | director-stage 对象自身 `revision`，不复用整集 revision；无需 lease | `PATCH .../episodes/{eid}/director-stage`；`POST .../capture` 绑定 expected_revision | P5 禁止整份 PUT；COLLAB-11：无权 capture 失败、冲突 409、截图素材和节点同事务/补偿一致 |
| `filmBible.voices.profiles`，`voices.ts` | `visual_cards.voice_profile_json`（不是独立第二主源） | Production visual card | card assignee 编辑/锁定/采纳；PM/WO 接管 | card `revision` + 生成基线 revision | `PATCH .../visual-cards/{cid}/voice-profile`，lock/accept 命令 | P5 从共享 JSON 投影读取后停写；REG-04：锁定后拒绝原改、迟到结果不覆盖新 revision |
| `settings.prompt_library`，`save_prompt_template()` | `prompt_templates` + `prompt_template_revisions` | 第一版平台级 | 仅 PA 写/归档；普通成员只读启用模板 | `revision`，历史 append-only | `/api/admin/prompt-templates/{id}` | P4 退役普通 `PUT /api/prompt-library/{tid}`；P4-TPL-01：非 PA 403、历史可追溯、无秘密字段 |
| `document.timeline: Clip[]` 旧简剪 | `editor_timelines.timeline_json` 的 v1 投影/导入，不再单独可写 | Episode | timeline assignee；PM/WO 接管 | 与 Twick 共用 revision + lease epoch | 一次性 `POST .../timeline/import-legacy`，其后统一 PATCH timeline | P5 首次转换后返回只读投影；REG-05：旧 clips/audio 不丢、两入口不能双写 |
| `document.editor.timeline` Twick 工程 | `editor_timelines.timeline_json` | Episode | timeline assignee；其他成员预览/评论 | `revision` + 独占短租约/epoch | lease acquire/renew/release/takeover + `PATCH .../timeline` | P5 停止 `main.tsx update()` 整份保存；COLLAB-06：过期 lease/旧 epoch/旧 revision 均拒绝；审核另属 COLLAB-07 |
| `document.audio_id`/编辑导出参数 | `editor_timelines.audio_asset_id` 与 timeline export settings | Episode；asset 必须同 Production | timeline assignee 修改；导出按作品权限 | timeline revision + lease | timeline PATCH；export job 冻结 timeline revision | P5/P6 禁止 job 输入成为主源；REG-05/MEDIA-07 验证跨作品 asset 拒绝和导出可复现 |
| `document.nodes/edges`，`patchNode()` | `graph_nodes/graph_edges` + `graph_structures` | Episode | 镜头节点继承 Shot assignee；自由节点有独立 assignee；PM/WO 接管 | 节点/结构 revision | node/edge 小命令或 structure PATCH | P5 旧 PUT 410；COLLAB-11 验证不同节点并行、同节点冲突 |
| `filmBible.visual` 卡片/版本/绑定 | `visual_cards/visual_versions/shot_visual_bindings` | Production，绑定落到 Episode Shot | card/shot assignee 按动作；锁定版本不可原改 | card/shot revision；版本不可变 | card/version/bind/fork/lock 命令 | P5 禁止 JSON 双写；COLLAB-08/09 与 REG-02/03 |
| `generationPolicy/style` 当前共享 context | `production_generation_policies` / Production metadata | Production | PM/WO；普通 editor 只读可选已发布模型 | revision | `PATCH .../productions/{pid}/policy` | P4/P5 退役 project PUT；MODEL-03 验证不能注入 provider/key/upstream id |

UI-only 的 `selected`、视口、播放头、面板开关和 PanoramaViewer 当前查看状态继续只保存在客户端，不建立共享写对象；全景素材本身仍是受 Production 授权的 Asset。

## 唯一主源原则

1. `Project.document` 最终只能是读取聚合，不可写回成为第二主源。
2. Film Bible 卡片、视觉版本、镜头、剧本和时间线各自只有一个可写表/服务。
3. UI 视口、选中项、播放头、面板状态不进入共享业务对象。
4. 对象变更在一个短事务内完成：权限检查、`expected_revision` 条件更新、历史、审计和 domain event。
5. 生成结果先登记为候选并绑定提交时对象版本/assignment epoch；不得覆盖更晚人工版本。
6. 复合外键或等价约束防止跨 workspace/production 父子混绑。

## 旧写路径退役顺序

1. P2 将 SQLite 数据按目标领域迁入新空 PostgreSQL 基线，不迁旧用户数据。
2. P3 暂时把旧整份 PUT 限制为 manager/owner，禁止 editor 借旁路修改他人对象。
3. P5 前后端逐对象切换；所有旧编辑入口有对象映射后，旧 PUT 对协作写明确返回失败。
4. 保留只读聚合器供既有纯函数/UI 过渡；确认无写调用后删除 JSON 双写和旧迁移逻辑。
