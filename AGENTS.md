# OurVideoCreator 项目执行规则

本文件是 Codex 在本仓库中的默认执行入口。开始任何开发任务前，必须完整阅读并遵守根目录的 `ChatGPTRules.md`。

## 当前项目约定

- `origin`（`imherro/OurVideoCreator`）是协作版主仓库，也是唯一默认推送目标。
- `upstream`（`imherro/MyVideoCreator`）是单机版只读上游。可以从中获取更新，但不得向其推送。
- 所有新开发默认只进入协作版仓库；只有用户明确要求时，才再次同步单机版的新提交。
- 当前采用 `master` 直接开发和推送。开始多人并行开发后，改用功能分支和 Pull Request；切换前由 ChatGPT 或用户明确决定。
- `AGENTS.md`、`README.md`、`ARCHITECTURE.md` 和 `docs/` 中的相关资料应在存在时阅读；文件或目录尚不存在时，不把缺失本身视为阻塞。
- 用户当前指定的项目 ChatGPT 会话是产品设计与代码审核主会话。能够访问时，将每个已验证并推送的任务结果发送到该会话；无法访问时，在当前 Codex 任务中报告，不猜测会话内容。
- 每轮只完成一个可独立验收的任务。验证通过后再提交并推送到 `origin`，然后请求 ChatGPT 审核并给出下一个单一任务。

如本文件与 `ChatGPTRules.md` 出现冲突，以两者中更具体、更新的项目约定为准；仍无法判断时停止扩大修改并交由用户或 ChatGPT 决策。

## 多用户改造

- 冻结契约和阶段规则来自 `docs/MyVideoCreator_Codex_Full_Playbook_v1.md`；当前阶段与产物索引见 `docs/multiuser-rollout/README.md`。
- 每次只实施外部验收人明确指定的一个阶段，阶段交付后停止；未收到通过结论不得进入下一阶段。
- 旧测试数据不迁移；目标为外部 API-only；平台独占供应商、API Key 与模型配置；手机号首版只是未验证登录名。
- 保留创作流程、外部 Provider、Film Bible 版本、素材、剪辑和 FFmpeg；不做实时共编、充值商城或复杂组织树。
- 权限必须由服务端实施；不能靠隐藏前端控件，不能让整份项目 PUT 绕过对象权限和版本控制。
- P2 起集成测试必须使用真实 PostgreSQL。默认禁止真实付费 Provider；只有用户按供应商、模型、次数和费用边界独立授权后才可调用。
- 不提交秘密，不自动删库，不覆盖用户改动；跳过、未运行和环境阻塞必须如实记录。
- 开发交付只能标记 `READY_FOR_REVIEW` 或 `BLOCKED`，Codex 不得自行签发外部验收通过。
