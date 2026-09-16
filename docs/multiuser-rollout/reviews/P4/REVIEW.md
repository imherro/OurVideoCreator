# OurVideoCreator · P4-MODEL-01 外部验收

## 结论与绑定

**不通过。P4 未通过，P5 未授权。下一单一任务：P4-R1。**

- 唯一仓库：`imherro/OurVideoCreator`
- P3 通过 base：`de5ef13d6c772e62ec8a0e40be7be8abf1eb25d6`
- P4 实现：`0e64bd0540ad53de5ea6d93013c14d5154760867`
- 最终被测业务：`3a73165f74520d0c15ec6f0750d7b2c105108744`
- evidence HEAD：`c7d6a88a06a01035fd44e45309414c05e061ab64`
- 阻塞：`OVC-P4-01`、`OVC-P4-02`、`OVC-P4-03`，均为 **S2**。
- P0/P1/P2/P3 的历史通过保持不变。

本次问题限定于已发布模型参数、已接受认证方式、已发布用途是否与当前实际执行一致。不要求 P5 对象协作、P6 多 Worker/配额，不要求真实付费 API 或公网部署。已有 PostgreSQL、账号权限、配置/凭证版本化及文本/图片闭环不需要推倒重做。

## 1. 实际检查与证据关系

已读取指定 branch、父提交、业务 diff、关键模型服务/Worker/适配器实现、迁移、相关测试及正式证据。提交链为 `de5ef13 → 0e64bd0 → 3a73165 → c7d6a88`。[S01–S05]

`0e64bd0 → 3a73165` 只在 `tests/test_p4_model_foundation.py` 增加 14 行针对真实 Worker.execute 的密钥异常/零 HTTP 断言；没有运行时代码差异。`3a73165 → c7d6a88` 根 Git 树仅 docs 不同。故 0e64bd0 的浏览器/前端证据可用于相同运行时，不冒称它们在 3a73165 重跑。[S03–S05, S23]

正式实施端结果已核对：
- 最终后端：351 passed，2 warnings，502.37 秒，exit 0；UTC 2026-09-16 17:03:37.7463019–17:12:02.5591828。[S24]
- 前端：128 passed，0 failed/cancelled/skipped；TypeScript+Vite 成功，**1827 modules**，7.53 秒。[S25]
- 实际路由：99 注册项，96 API/96 分类，0 未分类，OpenAPI disabled；compile exit 0。[S30–S31]
- 两个 websockets 弃用 warning 和原大 chunk warning 不阻塞。用户摘要中 1825 modules 应按原始本轮日志记为 1827；这是数字校正，不是功能缺陷。

## 2. 已有成果予以认可

平台管理员服务端权限及 CSRF、旧 Provider 配置入口退役、安全目录、递归私有字段拒绝、任务版本引用及配置/审计事务已有实现及正反测试。[S06–S09, S14–S17]

凭证使用认证加密，密文包绑定 Provider/凭证版本，独立部署主密钥有校验，缺失/错误/损坏时拒绝；最终测试增强确实覆盖 Worker.execute 在 HTTP 前失败。[S03, S12, S15]

真实 loopback A/B 轮换测试使用原账号/原地址轮询及取消旧 handle，吊销不改账号重试，停用阻止未出站队列并保留原 handle 查询语义。认可这一已测路径，不将其扩大为“所有适配器所有配置都已验证”。[S16]

集中出站代码执行 DNS 全答案检查、实际连接目标 IP 固定、原 Host/TLS SNI、每跳策略及认证来源约束；测试覆盖混合/私有 DNS 与跨源重定向拒绝。没有要求为了 P4 引入网关/服务网格。[S09, S15]

## 3. 阻塞问题

### OVC-P4-01 · S2 · 缺省参数绕过已发布规则

**位置**
- `backend/model_validation.py::model_definition / parameters`
- `backend/platform_models.py::resolve / _load_binding`
- `backend/worker.py::Worker.execute / _chat_text`
- 同类需要窄范围自检的既有协议缺省：`backend/providers/volcengine_speech.py::synthesize`。

**具体事实**
模型定义允许默认参数为空，只验证实际提供的 defaults/submitted 值。例如已发布：
```json
{"rules":{"max_tokens":{"type":"integer","min":1,"max":200}},"defaults":{}}
```
普通提交 `parameters={}` 会得到合法的空冻结参数；Worker 的文本协议随后自行加入 `int(inp.get('max_tokens',4096))`。这不是用户明确提交 201 的已测拒绝路径：省略值反而使实际 HTTP 请求带 4096。[S06–S08]

**影响**
后台限制与实际外部请求不一致；用户只需省略可选参数，实际调用就可能超过平台已声明范围。这是实际参数约束缺口，不是尚未完成金额配额，也不声称发生真实费用。

**最小复现**
用本项目已支持 OpenAI-compatible 文本适配器，管理员发布上述规则且不设默认值；普通获权用户不提供 max_tokens；在专用 fake `/chat/completions` 捕获请求。当前参数冻结为 `{}`，实际请求为 4096。可通过管理/提交 API + 实际 Worker 做完整红测，不需要真实 Provider。

**本审核端独立观察**
`probes/protocol_probe.py` 执行了原参数函数和完整 `_chat_text` 摘录，通过自行创建的 loopback HTTP 收到 `max_tokens=4096`，规则上限为 200。为了不连接外部地址/数据库，进度和持久化是夹具，egress client 用仅允许该测试 URL 的普通 httpx client 替代。因此这是实际 HTTP 的协议摘录实验，**不是完整 PG 发布/提交/Worker 执行**。

**最小必要修复/通过标准**
1. 填补后的实际协议参数仍受该模型已发布规则约束。可以要求这种字段有合法默认值、拒绝缺省提交，或将支持的缺省值纳入受控解析并验证；不强制选择某种架构。
2. 不允许适配器在冻结之后补入超出规则的值。成功任务的冻结参数与实际 wire 参数在这些控制项上必须一致。
3. 直接提交 201 仍拒绝且零外呼；明确 100 正常；省略不能发 4096。用真实 PG/API + 实际 Worker/fake HTTP 验证，并保持批量末项失败的原子行为。
4. 同根因的现有关键缺省做有限检查：例如温度/图片数量/语音 voice_type 在已声明枚举或范围时也不能回退越界。只覆盖当前接通协议，不扩建通用规则系统。未声明限制的固定协议常量不因本条要求一律禁用。
5. 不以静默截断/夹紧非法用户值、删除平台规则、只改 UI 值作为修复。

### OVC-P4-02 · S2 · Maestro/Comfy 接受 API Key 配置，却发出匿名请求

**位置**
- `backend/model_validation.py::provider_config`
- `backend/platform_models.py::_load_binding`
- `backend/worker.py::Worker.maestro / Worker.comfy`
- `backend/provider_egress.py::client`

**具体事实**
Provider 配置接受上述类型的 `auth_mode=api_key` 并保存非空凭证；Worker 装载可取得该 Key。然而两个方法的 `provider_egress.client(...)` 及实际请求都没有传入认证 header。集中 client 只处理传输防护，不读取 Provider 或代为加入 Key。[S06–S09]

**触发与影响**
服务启用鉴权时，平台后台保存/发布后，Maestro 的首个 `/api/v1/models` 或 Comfy 的 `/prompt` 请求仍是匿名的，收到 401，任务不能运行。这里不是 Key 泄漏，也不是要求上游必须支持某种新鉴权；问题在于产品接受了一种实际上未使用的认证配置。

**本审核端独立观察**
对两个方法从入口到首个出站点的代码摘录，使用自己创建且要求合成 Bearer 的 loopback 服务；捕获到两条请求 `has_authorization=false`、HTTP 401。进度/数据库夹具以及 egress 替代边界同上；Maestro 前置未用到的 capabilities import 在摘录中省略。没有运行完整适配器生命周期。

**最小必要修复/通过标准**
二选一即可，不要求额外认证平台：
- 若当前适配器确实要支持已接受的 Key 协议，在该协议要求的上传/提交/查询/取消调用上正确注入，来源固定；或
- 明确当前类型只支持无认证 API，在服务端配置/发布与 UI 直接拒绝 `api_key` 组合，不接受然后在任务中忽略。无认证私有服务仍必须通过现有精确部署例外。
对“允许的组合”用实际 guarded transport 和 fake HTTP 证明认证值有效但不入日志；对“不支持组合”证明入队/外呼前拒绝。保持跨源 header 隔离、凭证轮换/吊销与其他适配器回归。

### OVC-P4-03 · S2 · Replicate 的 audio 可发布入队，但成功输出走 PNG 图像登记

**位置**
- `backend/model_validation.py::PROVIDER_KINDS`
- `backend/app.py::create_job_record`
- `backend/worker.py::Worker.dispatch`
- `backend/replicate_api.py::execute`
- `backend/providers/common.py::download_result / register`

**具体事实**
P4 将 Replicate 列为支持 text/image/video/**audio**；提交端原先只允许 `volcengine_speech` 的 audio 限制已经移除。新的 audio 模型可以通过校验并进入 Replicate 执行路径。[S07, S14; implementation diff]
但 Replicate 所有非文本媒体只用：
```python
'.mp4' if job['kind']=='video' else '.png'
```
决定下载后缀。因此 audio 输出也保存为 PNG。`register()` 按后缀猜 MIME，选择 image 分支并调用 PIL 读取；真正的 WAV/MP3 音频无法按这条路径登记为音频。[S10–S11]

**影响**
平台发布了当前适配器没有完成的用途；上游即使成功，结果在本地报错。这里不要求补上新的 Replicate 音频能力。

**最小复现与独立边界**
真实 PG 管理入口发布 `kind=audio` 的 Replicate 模型，fake 返回成功及有效 WAV URL；当前 Worker 会以 `.png` 进入图像登记。此完整场景须实施端补红测。
审核端已执行两个原始后缀/类型分支及真实 WAV/PIL 解码：样本为 800 帧、8kHz、单声道有效 WAV，选择 `.png`、`image/png`、`image` 后得到 `UnidentifiedImageError`。只验证路径决策与解码，不冒称完整远端任务/PG 执行。

**最小必要修复/通过标准**
优先从已发布能力集合及服务端入口移除当前未接通的 `replicate/audio`，发布/提交在任何外呼前给明确拒绝，普通目录不再提供该组合，保持已经接通的豆包语音、Replicate 文本/图像/视频。
若选择保留 audio，才需最小地做正确格式/类型登记并有 fake 成功闭环；本阶段**不强制扩展**这一能力。不能把任务失败简单改为 succeeded 或跳过媒体校验。

## 4. 浏览器与安全证据

本轮 UI 证据可接受，不另立浏览器补证阻塞。实际 trace 记录平台后台表单创建两个 Provider/录入合成 Key/发布文本和图像模型，再以普通 platform user、作品 manager 完成提交；不是 API 预填模型冒充表单。[S26–S28]

文字参数 201 明确 400、未生成，改为100后成功；独立 Worker 文本和异步图片均 succeeded，图片可见，空视频目录禁止生成；fake text/submit/poll/download 各1、wrong_auth0，下载 anonymous。[S26–S28]
已读取的普通响应与事件扫描为199份JSON/13条SSE，PG37表60行、4份进程日志canary0。只认可该合成 canary 与实际覆盖范围，不声称证明所有可能的信息泄漏都不存在。[S22, S26–S27]
浏览器基于0e64bd0，运行时与最终业务相同，工具没有CLI总exit、内核版本不可得，都已正确披露。[S03,S23]

## 5. 审核端实际执行边界

`environment.json` 保存本次只读 git ls-remote 失败（GitHub DNS）及工具探测；本容器没有 psql/postgres/PowerShell。**没有独立重跑完整项目、真实 PG、PowerShell 或工程浏览器。**
连接器读代码/证据正常。独立执行仅为 `probes/` 下明确标注的源码摘录/自有loopback HTTP/真实WAV解码。
`protocol_stderr.txt` 保留测试子进程 Python 启动时无关的 spreadsheet runtime warmup warning；协议探针本身退出0并输出记录，不能将该 stderr 冒充工程日志或删掉后声称完全无输出。
没有访问用户7868、P3 7895、保留的P4 6313/6185实例，没有修改远端仓库，没有支付调用。

## 6. 下一步

仅实施 **P4-R1**，见 `P4_R1_CODEX_PROMPT.md`。新证据写入 `evidence/P4-R1/`、绑定新业务SHA；现有P4原始日志保留。无需为这三处最小修复重建架构或再次补整套P3。
完整矩阵见 `MATRIX.md`，来源编号见 `SOURCES.md`。
