# P0 数据主源与对象归属

## 语义映射

- `Workspace`：团队，租户隔离边界。
- `Production`：作品/剧集，包含多个分集。
- 当前 `projects`：`Episode`/制作集，不得再建立一个含义冲突的 Project。
- 素材属于 Workspace + Production；`project_id` 可保留来源 Episode，但不是所有权边界。

## 当前物理主源

| 当前表/载体 | 当前主数据 | 当前版本机制 | 问题 |
|---|---|---|---|
| `settings` | 共享密码、Provider/Key、模型目录、prompt library、本地 runtime 设置 | 部分 JSON revision | 全局、混合秘密与公开配置 |
| `sessions` | 全局共享会话 token 摘要 | expiry | 无 user_id |
| `productions` | 作品名、共享 Film Bible/策略/改编 context | revision + `production_revisions` | 无 workspace/成员 |
| `projects` | Episode 元数据和大 `document` JSON | revision + `revisions` | 多对象共享一个写冲突域 |
| `source_documents/source_chapters/source_events` | 原著、章节、提取事件 | 章节 revision；事件替换 | 无负责人/租户列 |
| `episode_scripts` | 一集正式剧本 | revision + revisions | 已接近目标粒度 |
| `assets` | 媒体身份与磁盘 key | 无内容 revision | `project_id` 来源与所有权混杂 |
| `jobs/job_private` | 任务、冻结输入、Provider 快照 | status/update time | `job_private` 含明文 Key 配置 |
| `events` | SSE 通知日志 | 自增 cursor | 无 workspace/可见性字段 |
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
