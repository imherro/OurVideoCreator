# P4-MODEL-01 实现契约

状态：实施中，不是完成或验收声明。授权见 `../prompts/P4_CODEX_PROMPT.md`；开发起点 `de5ef13d6c772e62ec8a0e40be7be8abf1eb25d6`。不修改现有 7868 / P3-R2 7895 实例，不调用真实付费服务。

## 唯一配置来源及版本

增量迁移新增平台 Provider、不可变 Provider 配置版本、认证加密凭证版本、模型目录及不可变模型版本。已有 `settings.providers` 不迁移、不再作为运行时来源；已有 `job_private.provider` 不回落解密使用。没有新版本引用的旧任务不能恢复外呼，需明确重新核对。

Provider 当前行保存名称、启停、当前配置与凭证指针及乐观版本；配置版本保存类型、base URL 和经过白名单校验的非秘密协议参数。凭证版本保存独立部署主密钥下的认证密文、主密钥标识、current/retired/revoked 状态，禁止回显明文。配置/凭证/审计同事务提交。模型当前行保存发布、启停及版本指针；模型版本保存 Provider、上游标识、用途、能力、默认参数与简单允许规则。各用途默认模型只引用明确发布的模型，不自动挑选其他服务。

任务保留平台 model_id、模型版本、Provider 配置版本、凭证版本与非秘密参数快照。新任务使用当前版本；已有任务不重绑最新 URL 或 Key。正常轮换仅将旧凭证退役，旧远端 handle 继续原凭证/原地址；吊销后失败关闭。停用阻止新提交和尚未外呼的队列任务；持有远端 handle 的任务仍可查询/取消，除非原凭证被吊销。任务引用版本不提供硬删除入口。

认证加密使用成熟库，主密钥仅由环境注入，不自动生成、不读旧 settings。缺失/错误/损坏均明确阻止凭证操作及出站。平台身份管理可以继续工作。

## 页面/API/权限

扩展现有 `/admin`：Provider 保存、保持/替换 Key、吊销版本、启停、配置检查；模型编辑、发布、用途默认。新 `/api/admin/` 路由复用 platform_admin + CSRF 守卫。workspace owner、作品 manager/editor/viewer 均不可管理。API 不回显秘密，审计只写实体及版本标识。

普通页面只读 `/api/models` 安全目录：平台 ID、显示名、用途、能力、默认参数/允许规则及用途默认，不含上游地址、凭证、headers 或上游模型标识。无可用模型有明确空状态。普通任务仅以 `model_id` 选择模型，服务端验证用途、参数和素材作用域。递归拒绝隐藏的 provider/key/url/header/上游 model 覆盖。批量全部验证后在原事务内创建任务。

`GET /api/settings` 仅保留创作所需安全设置/目录；旧 Provider 写入、模型读取、verify/test 不得继续访问全局 settings 或任意地址。提示词库继续平台管理员写、获权普通账号读；复用现有界面和版本历史，不另造 CMS。

## 实际入口与改造边界

| 当前入口 | P4 接入点 |
| --- | --- |
| `backend/app.py` settings/provider models/verify/test | 新模型服务唯一配置源；旧管理入口退役或委托同一服务 |
| `create_job_record`、`submit`、`run_batch` | 统一解析、全部校验、原子队列及不可变版本引用 |
| 原著提取/改编/剧本/视觉/语音编译及整份 document 保存 | 平台模型 ID 默认/覆盖；递归拒绝私有配置输入 |
| `generation_policy.py`、视觉/视频编译器 | 仅从安全平台目录解析；不自动挑选 Ark 或其他付费服务 |
| `worker.py` execute/ark_job、app cancel/resume | 仅加载任务冻结引用；出站前校验停用/吊销；临时解密，不持久化明文 |
| `providers/*` 协议及 `providers/common.py` 下载 | 保留协议；统一 URL/DNS/redirect 守卫及安全错误输出 |
| 幻场素材注册/审核/映射 | 保留作品/团队授权与原账号配置身份隔离 |
| `src/main.tsx` AdminConsole/SettingsPanel、ModelSelector/GenerationPolicyPanel/任务输入 | 后台实际保存发布，普通用户只选平台目录 |
| FFmpeg、ffprobe、Twick、私有素材/SSE | 保留本地非推理路径与既有 ACL，不误删 |

出站策略仅允许 HTTP(S)、不含内嵌凭证的 URL；检查实际 DNS 和每跳 redirect，默认拒绝非公网目标。仅部署明确配置的 host/IP/port 窄例外可访问 loopback fake/私有推理。认证请求不把 headers 传播给任意结果或异源重定向。保存/格式检查不外呼；无免费鉴权协议则显示未验证，不能声称生成成功。

## 验证映射（执行结果见最新检查点与交付证据）

- MODEL-01/02：各角色管理 API、CSRF、旧路径与安全目录；真实管理员/普通用户浏览器操作。
- MODEL-03/04/05：递归输入、批量事务、用途/参数/能力/素材权限、空目录/停用零出站与 UI 空状态。
- MODEL-06/08：免费检查语义、URL/DNS/redirect、精确例外与跨源认证隔离。
- MODEL-07/SECRET-01：真实 PG 配置事务、密文、A→B 轮换、原 URL 恢复、吊销、错误主密钥及损坏密文零出站。
- SECRET-02：唯一合成 canary 在普通响应/任务/历史/SSE/日志/导出/浏览器产物的安全扫描，不打印 Key。
- P4-TPL-01：提示词管理员写/普通用户读；既有 P1/P2/P3 和 Provider/FFmpeg 回归不能删断言求绿。
- 成功链：真实后台页面配置 → 普通页面选模型提交 → PG 任务 → 独立 Worker → loopback fake 文本及一种异步媒体 → 页面结果。失败、人工协助、工具限制分别记录。

只有上述实际实现并验证，才另存 `evidence/P4/`，提交业务 SHA 和证据 HEAD 后请求 ChatGPT 外部验收。本契约不授予 P5/P6、真实费用或公网部署权限。

## 实施检查点：2026-09-16（非阶段交付）

已写入工作区，尚未提交：

- `0003_platform_models` 增量迁移；Provider/模型不可变版本、凭证状态、任务版本引用及提示词 append-only 历史。旧 settings 和旧 job JSON 未迁移或删除。
- `provider_secrets.py` 使用 cryptography 50.0.1 Fernet。部署主密钥校验密文绑定唯一 keyring，凭证认证包绑定 Provider/凭证版本，避免跨配置密文替换。保存/审计同事务；没有自动生成主密钥。实现依据 [Fernet 官方文档](https://cryptography.io/en/latest/fernet/)。
- `provider_egress.py`：精确部署例外、DNS 全部答案检查、实际连接 IP 固定、原 Host/TLS SNI、每跳 redirect 检查和认证请求来源绑定。传输封装依据 [HTTPX transport](https://www.python-httpx.org/advanced/transports/) / [HTTPCore extensions](https://www.encode.io/httpcore/extensions/)。**尚未替换全部 adapter 调用点，不代表现有调用已经全部受保护。**
- 平台 Provider/模型管理服务及 `/api/admin/model-providers`、`/api/admin/models`、普通 `/api/models`；复用原认证/CSRF。
- 现有 `/admin` 增加模型表单；提示词写入切换 `/api/admin/prompt-templates/{tid}`，旧写接口返回 410；前端只给 PA 编辑按钮并仅提交允许字段。

开发中实跑（工具输出记录，非已提交业务 SHA 的最终原始证据）：

| 检查 | 实际结果 |
| --- | --- |
| 首次旧测试端口 55432 | 连接超时，尚未执行测试；中止后创建新的隔离 PG，不算失败用例或通过 |
| 新 55434 隔离 PG，首轮 foundation | 27 passed / 12.07s / exit 0 |
| foundation + 既有提示词版本用例 | 28 passed / 14.45s / exit 0 |
| 扩展 foundation + 提示词 + P3 identity/ACL + P3-R2 真实交错 | 60 passed / 91.46s / exit 0；2 项既有 websockets 弃用 warning |
| npm test | 126 passed / 0 failed / 0 skipped / exit 0 |
| npx tsc -b、Python compileall | exit 0 |
| 实际 app.routes 分类 | 98 条注册项，95/95 API 分类，0 未分类 / exit 0 |

新测试 cluster 仅监听 `127.0.0.1:55434`，不是原 55432 cluster；pytest 继续每轮创建和仅清理自身白名单命名库。7868 未由本任务停止/重启；7895 当次检查未监听，不启动或清理其旧数据。未运行真实付费 API。

仍未完成：旧 Provider settings/verify/test 退役，全部创作/整份 document/批量入口转 `model_id`，安全目录替换普通选择器和项目策略，Worker/取消/恢复全面绑定新版本，适配器统一出站与错误/结果秘密防泄漏，HC 账号映射与全部能力/参数回归，真实浏览器文本+异步媒体独立 Worker 闭环，完整后端回归与最终 evidence、commit/push/外部验收。基础测试通过不等于 MODEL/SECRET 整体已通过，当前不得部署此未完成工作区。

## 实施检查点：2026-09-17（当前）

以上 2026-09-16 条目是历史检查点；其“尚未接通/仍未完成”不代表当前状态。当前已接通全部任务入口、旧 settings/verify/test 退役、普通安全目录与平台 ID、冻结 Worker/取消/恢复、受控出站和秘密脱敏。

- 音频批量使用 `POST /api/projects/{pid}/audio-jobs`，先全量校验再一次事务入队。
- 分镜图尺寸与视频帧数从已发布规则/能力及作品的规范镜头数据计算；不依靠上游名称推测。固定项目视频时长同时作用于预览和服务端。
- RunningHub 文本与媒体显式分开 Provider 地址；不使用隐式域名重写。音色只允许平台发布枚举及参数，未发布控制项不提交。
- 全景节点在平台允许 resolution/size 时保留 2:1 参数，规则不允许则不夹带越界参数。
- 后端首次全量迁移回归出现 97 failed / 237 passed / 10 errors，主要为旧 Provider settings fixture 和旧 HTTP mock；保留实际业务断言后迁移至真实 PG/平台配置。修复后第二轮全量 346 passed / 2 warnings / exit 0，441.83s。新增角色矩阵 foundation 36 passed；A/B 真实 HTTP 轮换 1 passed。
- 前端最新 128 passed / 0 failed / 0 skipped；TypeScript + Vite build 通过，保留原有大 chunk warning。
- 隔离浏览器实际保存/发布文本与异步图片模型；普通 manager 页面选模型提交，独立 Worker 生成结果可见。editor 保持 P3 既有整份文档限制，不为测试放宽。无视频目录明确提示、不回退；保存/检查前后 fake 计数零。正式业务 SHA、完整回归、秘密扫描和原始证据在交付时另行归档。

该检查点仍不是外部通过结论；P5、真实费用和部署未授权。

## P4-R1 修复契约（2026-09-17，未验收）

外部 P4 首轮不通过，三个 S2 及原始执行要求见 `../reviews/P4/REVIEW.md` 和 `../prompts/P4_R1_CODEX_PROMPT.md`。保留旧证据，不自行关闭阻塞。

- 受限参数：所有规则列出的参数在入队前必须由模型默认值、明确输入或规范镜头计算补齐并验证；缺失明确 400，非法值不夹紧。未发布规则的既有协议固定常量不受此改动影响。Worker 在新出站前再验证其冻结快照，旧空快照不使用版本默认值偷偷填充。已有远端 handle 的查询不重新生成参数或任务。
- 认证组合：Maestro/Comfy 保留当前原生无认证协议，只允许显式 `none` 且 Key 为空；API Key 模式在服务端及管理 UI 明确拒绝，不增加新认证协议。精确部署出站例外不变。
- 用途组合：Replicate 仅保留 text/image/video，不再宣称 audio；既有豆包语音保持。配置、模型发布、普通目录、提交和原版本 Worker 装载执行相同的已支持组合检查；旧不支持版本不可用，不自动改写数据库或切换服务。
- 回归采用实际 API/PG/Worker/guarded loopback HTTP。已保存四个期望失败的基线红测（参数一项、Maestro/Comfy 两项、Replicate 音频一项），不是只摘录函数的探针。正式绿测、全量和浏览器补证另行固定新业务 SHA 后归档。
