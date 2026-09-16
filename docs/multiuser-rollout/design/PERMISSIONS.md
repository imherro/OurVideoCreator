# P0 权限矩阵

## 角色

- 平台：`platform_admin` / `user`。
- Workspace：`owner` / `member`。
- Production：`manager` / `editor` / `viewer`。
- Workspace owner 对本 Workspace 的 Production 具有管理能力，但跨租户访问必须走显式、审计的后台入口。

## 行为矩阵

| 动作 | platform_admin | workspace owner | production manager | editor | viewer |
|---|---:|---:|---:|---:|---:|
| 签发/撤销注册邀请 | 是 | 否 | 否 | 否 | 否 |
| 停用全局账号/签发重置链接 | 是 | 否 | 否 | 否 | 否 |
| 创建 Workspace/指定 owner | 是 | 否 | 否 | 否 | 否 |
| 管理平台 Provider/Key/模型/全局额度 | 是 | 否 | 否 | 否 | 否 |
| 将已有用户加入/移出本 Workspace | 后台显式 | 是 | 否 | 否 | 否 |
| 创建 Production/指定 manager | 后台显式、审计 | 是 | 否 | 否 | 否 |
| 在已有 Production 中创建 Episode | 后台显式 | 是 | 是（仅有管理权的 Production） | 否 | 否 |
| 管理 Production 成员 | 后台显式 | 是 | 是 | 否 | 否 |
| 查看参与 Production 内容 | 后台显式审计 | 是 | 是 | 是 | 是 |
| 查看同 Workspace 未参与 Production | 后台显式审计 | 是 | 否 | 否 | 否 |
| 创建允许对象 | 后台显式 | 是 | 是 | 是，初始归自己 | 否 |
| 修改自己负责对象 | 后台显式 | 是 | 是 | 是 | 否 |
| 修改他人对象 | 后台显式 | 显式接管 | 显式接管 | 否 | 否 |
| 分配/重新分配/接管 | 后台显式 | 是 | 是 | 否 | 否 |
| 评论 | 后台显式 | 是 | 是 | 是 | 是 |
| 提交审核 | 后台显式 | 是 | 是 | 自己对象 | 否 |
| 确认/退回内容 | 后台显式 | 是 | 是 | 否 | 否 |
| 发起生成 | 后台显式 | 按对象权限 | 按对象权限 | 自己对象且额度允许 | 否 |
| 取消/恢复任务 | 后台显式 | 有权作品 | 有权作品 | 自己可操作范围 | 否 |
| 上传/下载/Range/导出 | 后台显式 | 有权作品 | 有权作品 | 有权作品 | 只读下载；不可导出若策略禁止 |
| 删除/恢复业务对象 | 后台显式 | 是 | 按对象规则 | 否 | 否 |

## 强制约束

1. 注册邀请只建立账号，不自动入组；手机号不能成为授权依据。
2. manager 不能把非 Workspace 成员直接加入 Production。
3. 普通成员不得列举全站用户或完整手机号。
4. 成员移除后撤销租约和编辑权，成果保留并标记待重新分配。
5. 保留最后一个有效 platform_admin 和 Workspace owner。
6. viewer 只读但可以评论；不能生成、删除、取得编辑租约或调用隐藏写 API。
7. 所有列表、详情、历史、回收站、素材、任务、事件、批量入口和导出都执行相同租户/作品边界。
8. 管理员跨租户内容访问必须使用显式后台入口并产生审计，不能在普通查询中设置万能 bypass。
9. `POST /api/projects` 当前会同时创建 Production 和首集，因此迁移期间必须与“创建 Production”同权（WO；PA 仅后台显式审计），不得作为 manager 越权兼容入口；manager 创建分集只能使用已有 Production 下的 Episode 命令。

## 当前差距

当前应用只有全局共享 session。通过登录后，所有用户对 69 条受保护路由拥有相同权限；`/api/settings`、任务详情、回收站、素材文件和 SSE 均无对象级授权。P3 必须按 `ROUTE_AUTH_MAP.md` 全面闭合，不能只增加登录页和新接口。
