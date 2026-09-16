# P4-MODEL-01 交付报告

状态：**READY_FOR_REVIEW，未获外部验收通过**。只提交 P4；不进入 P5、不上线、不调用真实付费 API。

审核仓库：**https://github.com/imherro/OurVideoCreator**，分支 `master`。不是单机版 MyVideoCreator。

## 1. 版本和证据边界

- 开发 base / P3 已通过 HEAD：`de5ef13d6c772e62ec8a0e40be7be8abf1eb25d6`。
- 实现提交：`0e64bd0540ad53de5ea6d93013c14d5154760867`。
- 最终被测业务 SHA：`3a73165f74520d0c15ec6f0750d7b2c105108744`。比实现提交仅增加 14 行 Worker 密钥异常拒绝断言；运行时代码无差异，见 `provenance.json`、`checks.json`。
- 正式浏览器和前端测试基于 `0e64bd0`；没有冒称在 `3a73165` 重跑浏览器。后端完整回归在两个 SHA 分别运行；最终结果见 `SUMMARY.json` / `backend-full.txt`。
- 业务 diff：`de5ef13..3a73165`；后续证据提交仅改 `docs/`。最终完整 HEAD 以本报告所在证据提交的 Git SHA 及外部审核消息为准，避免文档自引用 SHA。
- 环境：Windows 10.0.26200.0、Python 3.14.2、PostgreSQL 18.6、Node 24.13.0、npm 11.8.0；依赖版本见 `provenance.json`。

## 2. 本轮实现

1. 增量迁移 `0003` 建立平台 Provider 配置、认证加密凭证版本、模型目录/版本/默认项及任务私有版本引用。平台管理员是唯一配置来源；旧 settings Provider 路径退役，不双写、不回落、不迁移旧测试 Key。
2. `provider_secrets` 使用独立部署主密钥和成熟认证加密，密文绑定 Provider/版本身份；保持、替换、吊销分开。审计与配置同事务；缺失、错误或损坏密钥明确失败，不自动生成替代主密钥。
3. 现有 `/admin` 接入 Provider/Key/模型发布表单；普通页面改用安全模型目录、受限参数和明确空状态。服务端独立执行平台管理员、CSRF、作品 ACL、模型用途/能力、参数范围和嵌套覆盖拒绝。
4. 单节点、批量、原著/改编/剧本、视觉/视频/语音入口统一受控解析。语音批量先全部校验再原子入队；旧整份 document 不能注入 Provider、上游 model、地址或 header。
5. Worker 固定模型、配置、凭证版本，仅在必要调用时解密。新任务使用当前版本，已有远端 handle 查询/取消保留原身份和地址；吊销不换账号、不重复生成。停用阻止新提交及尚未出站的排队调用。
6. 统一 URL/DNS/重定向保护及实际连接 IP 固定；私有服务必须部署显式精确 host/IP/port 例外。认证不转发至异源；结果下载使用无平台认证客户端。供应商回显的合成 Key 在响应、持久化、错误和事件路径脱敏。
7. 保留现有 Provider 协议、幻场素材登记与作品/账号身份映射、Film Bible、素材、Twick、FFmpeg/ffprobe；平台提示词库维持管理员写/普通读。

主要文件：`backend/platform_models.py`、`backend/provider_secrets.py`、`backend/provider_egress.py`、`backend/provider_redaction.py`、`backend/model_routes.py`、`backend/worker.py`、相关任务入口和 adapter、`src/PlatformModels.tsx`、模型选择/参数面板、迁移、`tests/test_p4_*.py`。准确实体、入口和契约见 `../../design/P4_MODEL_CONFIG.md`。没有增加 Redis、微服务、通用插件平台或多 Worker。

## 3. 冻结验收矩阵

以下是开发侧验证结果，不代表外部签发通过。测试总数不是矩阵的替代。

| 编号 | 实际验证及证据 |
| --- | --- |
| MODEL-01 | 实际 UI 创建 2 个 Provider、发布 2 个模型，审计行 4–7；foundation 四角色矩阵直接请求全部新旧管理入口拒绝，CSRF 拒绝；普通浏览器 `/admin` 无权访问，相关请求 403。 |
| MODEL-02 | 普通目录仅含 id/kind/type/name/capabilities/defaults/rules；199 份 JSON 响应与 13 条 SSE 扫描零 canary 命中、零不可读取 body；无 Provider 地址/上游模型/Key 暴露。 |
| MODEL-03 | foundation 递归覆盖拒绝；submission 的单任务与 document 五类嵌套注入、退役路径、批次后项失败测试，拒绝后任务不增加且零 fake 出站；批量事务不留下前半批。 |
| MODEL-04 | 用途、枚举/范围/时长、引用能力及跨作品资源拒绝；视频帧数按发布规则规范化而不相信提交 fps；浏览器 max_tokens=201 请求 400、fake 仍为零，改为 100 成功。 |
| MODEL-05 | 空目录/停用模型 API 拒绝；浏览器视频模型为空时显示联系管理员且“不自动回退其他服务”，生成按钮禁用；停用队列由实际 Worker 在 HTTP 前阻止。 |
| MODEL-06 | 后台保存和检查后 fake 所有计数为零；实际页面明确“未验证上游鉴权，未发起生成或素材上传”；foundation 保存/检查 HTTP sentinel 同样为零。 |
| MODEL-07 | `test_p4_rotation_http.py` 使用真实 loopback A/B HTTP：A 接收旧任务、配置和 Key 轮换至 B 后新任务用 B；旧查询/取消仍用 A；吊销 A 后恢复受阻且不出站；停用 B 后新提交/排队调用阻止，但已有 handle 可按既定规则查询；断言 9 个精确事件，无错账号请求。 |
| MODEL-08 | foundation 覆盖非 HTTP(S)、URL 内嵌凭据、私有/混合 DNS、连接 IP 固定、重定向和异源认证隔离；精确 loopback 例外正例；媒体结果下载在真实链路标记 anonymous。 |
| SECRET-01 | PG 仅存认证密文（浏览器两行密文长度 312，只输出长度不输出密文）；密文移植、审计失败回滚、缺失/错误/格式错误主密钥及损坏密文断言；`3a73165` 补充四种异常的真实 Worker.execute 零 HTTP。 |
| SECRET-02 | fake 故意在文本结果回显合成 canary，页面只见 `[REDACTED]`；浏览器普通 JSON/SSE/历史、37 张表 60 行、4 份 Web/Worker 日志零命中；submission 独立 Worker 文本/媒体/实际 FFmpeg 导出及事件/数据库/日志扫描。证据导出另外清除管理员输入时本应出现的合成 Key/测试密码。 |
| P4-TPL-01 | 既有提示词库权限/版本历史测试随完整回归运行，服务端平台管理员写、普通成员只读，无新 CMS。 |

## 4. 正式浏览器：操作、请求、数据库关联

实际工具 `mcp__cua_repl.js` / Codex in-app browser，computer-use skill 版本 `26.908.70816`。内核版本调用不支持，记 unavailable；浏览器不是 CLI，**没有总 exit code**。本轮没有用户代点确认框。

隔离夹具启动 UTC `2026-09-16T16:54:28Z`，实际操作约 `16:54:48–17:01:46Z`；Web `127.0.0.2:6185`，fake `127.0.0.1:6962`，PG `ovc_test_6360_1c0f38899a8f`。独立进程 harness 6360 / Web 27040 / Worker 31708。预置只有合成账号、团队、作品和无模型节点，**Provider/Key/模型不是提前 API 填库**。

| UTC | 实际浏览器动作/请求 | 结果 |
| --- | --- | --- |
| 16:56:06 | 表单保存文本 Provider，POST `/api/admin/model-providers` | 200，审计 4 |
| 16:56:12 | 点击配置检查，POST Provider `/check` | 200，仅配置校验，不声称鉴权 |
| 16:56:23 | 表单发布文本模型，POST `/api/admin/models` | 200，审计 5 |
| 16:56:35 | 表单保存异步图片 Provider | 200，审计 6 |
| 16:56:52 | 发布图片模型 | 200，审计 7；全部 fake 计数仍 0 |
| 16:58:10 | 普通获权用户选择文本，提交 max_tokens=201 | jobs 400，页面明确错误，fake 仍 0 |
| 16:58:31 | 改为 100 并再次点击生成 | jobs 200，独立 Worker 返回脱敏文本 |
| 16:59:42 | 选择图片模型并点击生成 | jobs 200，轮询后可见 256×144 图片和完成历史 |
| 随后 | 新建视频节点、检查空目录，打开历史 | 明确无模型且禁用生成；历史版本 1–8 可见 |

普通测试账号是 platform user / workspace member / production manager，不是平台管理员；保留 P3 对整份 document 写入的 manager 门槛。owner/editor/viewer 拒绝由 API 角色矩阵证明，不把单个 manager 浏览器冒称全部角色 UI 测试。

- 文本任务 `job-3c744c71d4d04ee6a89bcf77433e1c1c` 和图片任务 `job-8ed002bfbc6d47e191759e239fee0c4a` 均 succeeded。
- 最终 fake：text=1、submit=1、poll=1、download=1、wrong_auth=0；下载账号 anonymous。
- `browser-tool-trace.json` 是实际会话中 30 次工具调用及 30 次返回，保留 UTC/call_id、填写/点击、关键 AX、CDP 请求状态及扫描断言；不是事后编写的“原始日志”。
- `browser-pre-generation.json` 证明保存、检查、发布结束时尚无调用。
- `browser-db-audit.json` 从真实 PG 和实例日志只读采集，包含上述 job→模型/配置/凭证版本关联、审计行、角色及安全扫描计数。采集器为 `scripts/collect_p4_browser_evidence.py`。
- `browser-web-access.txt` 是该实例真实访问日志，不含 HTTP header/body。

## 5. 命令、原始日志和失败尝试

| 证据 | 正式命令 / 说明 |
| --- | --- |
| `backend-full.txt` | `python -m pytest -q --tb=short`，最终业务 3a73165，真实隔离 PG；UTC、总数、warning、退出码在文件和 SUMMARY 中。 |
| `backend-0e64bd0.txt` | 同命令，实现提交第一次正式完整回归，UTC 16:52:17–17:00:24，351 passed / 2 warnings / 485.49s / exit 0。 |
| `frontend-test-build.txt` | `npm test` 后 `npm run build`，UTC 16:52:27–16:52:42，128 passed / 0 failed / 0 skipped，TypeScript + Vite 1827 modules，exit 0。 |
| `routes.json` / `checks.json` | `python scripts/audit_routes.py`，99 registered / 96 API / 96 classified / 0 unclassified，exit 0；`python -m compileall -q backend tests scripts` exit 0；最终 SHA 与时间见 checks。完整后端另含真实新增未分类路由 0→1→0 的负向回归。 |
| `development-backend-r2.txt` | 开发期 346 passed / 2 warnings / exit 0，非最终 SHA 验证，不混充正式日志。 |
| `ATTEMPT_HISTORY.md` | 保留初次失败、旧 fixture 修复、预备浏览器、工具不支持、只读采集错误及补跑边界。 |
| `provenance.json` | SHA、依赖、运行时代码等同性、浏览器可得版本/不可得项。 |
| `integrity.json` | 证据文件 SHA-256（自身除外）；不等同于第三方认证。 |

后端沿用真实 PostgreSQL 和实际业务解析，不以 SQLite、禁用 ACL 或全局 mock 客户端换绿；契约测试只替换内层 transport。回归包含 P1 进程生命周期、P2 事务/事件空洞、P3 限流/重置交错及 ACL/MEDIA/EVENT，保留供应商协议及 FFmpeg。全部出站限定 fake/契约，未进行真实供应商鉴权或生成。

脱敏/投影规则：仅替换原始后端 warning 中本机用户名路径；浏览器 trace 精确替换合成 Key 与测试密码，并去掉非证据性的工具文档，不输出 Cookie/Authorization/body；DB 只输出安全字段、密文长度和扫描是否命中，不输出密文、密码哈希或连接串。完整原始后端日志留在本机测试临时目录；没有把不存在的早期完整红测文件重新构造出来。trace 生成脚本从测试源码读取合成常量用于脱敏，不在证据目录再复制明文。

## 6. 限制及待外部决定

- 检查按钮只证明配置/密文/地址解析，不证明上游免费鉴权、余额或付费生成能力。真实 Provider、数百人负载、公网部署 **未运行/未授权**。
- 两个浏览器夹具（预备 6313 / 正式 6185）的数据库、媒体和日志保留待查；未清理、未停止 7868 用户实例或 7895 P3 实例。pytest 只清理它自己创建的白名单临时库。
- 主密钥需部署方持久安全提供；丢失主密钥或吊销旧凭证后旧任务明确受阻，不承诺恢复秘密。不是多 Worker exactly-once/lease/fencing。
- 保留两项 websockets 弃用 warning、Vite >500k chunk warning，以及此前阶段记载的未归因连接超时观察；不声称这些根因均已解决。
- 没有改变冻结产品边界。普通浏览器使用 production manager 是遵循既有 P3 保存权限的夹具选择，不是放宽编辑权限。
- 建议外部只依据 P4 冻结矩阵审查实际功能和安全边界。若发现真实缺陷，给出最小修复；不要扩张为架构重写或提前实施 P5。
