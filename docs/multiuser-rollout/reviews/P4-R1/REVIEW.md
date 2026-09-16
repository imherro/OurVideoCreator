# OurVideoCreator · P4-R1 外部复验

## 最终结论

**通过。P4 已通过，允许进入 P5。**

- 仅审查协作仓库 `imherro/OurVideoCreator`，分支 `master`。
- 本轮 base：`c7d6a88a06a01035fd44e45309414c05e061ab64`。
- 固定业务 SHA：`e6c3edd95830d4c778fee357b8807d1443920a04`。
- 通过 evidence HEAD：`c0152ffcfb5623fcc0b723dbdf450acec9f17f73`。
- 原三个 S2：`OVC-P4-01`、`OVC-P4-02`、`OVC-P4-03` 全部关闭；无新增阻塞，不要求 P4-R2。
- P0–P3 历史通过不变。唯一下一任务：**P5-COLLAB-01，对象级分工协作前后端闭环**。
- 不授予 P6、真实付费 API 或公网部署权限。本结论不是所有商业供应商已实测的声明。

## 1. 版本与范围

实际分支和父链为 `c7d6a88 → e6c3edd → c0152ff`。业务根 tree 为 `88b0fc154cfad017a3409321f80ee08c7e1fe69c`，证据根 tree 为 `0cc1d0892f18d2e96d0f27e79ec18dbfdf54fb62`；根条目除 docs 外一致。[S01–S05]

本轮产品代码修改集中在 `model_validation.py`、`platform_models.py`、`PlatformModels.tsx`；测试新增 `test_p4_r1_regressions.py` 并将原生服务测试夹具改为合法 none 模式。未新增依赖或迁移，未将测试模式作为生产放行路径。本文不把远端 HEAD 一致性当成审核端亲自验证开发机工作区干净。[S03]

## 2. OVC-P4-01：受限缺省参数 —— 通过，关闭

`parameters()` 在合并默认/显式输入并校验后检查规则字段是否完整；`shot_parameters()` 允许规范镜头先计算控制项，随后进行完整检查。`_load_binding()` 对未持有远端 handle 的任务，用原冻结快照重新校验，明确不补当前或旧定义默认值。已经有远端 handle 的查询不被强制改造成新生成参数计算。[S06–S07]

基线红测使用平台管理 API、普通 editor 任务 API、真实 PostgreSQL、完整 `Worker.execute` 和 guarded loopback HTTP，捕获了 rules.max_tokens.max=200、冻结空对象而实际发送4096的矛盾。[S09–S10]

固定业务绿测：省略值400且HTTP零次；显式201仍400且零次；显式100成功，冻结与实际wire均100。temperature=0真实发送0；图片n=2真实发送2；voice_type缺省被拒绝，合法默认冻结，空/首尾空白音色枚举被拒绝发布。旧排队任务的空快照同样在出站前拒绝。[S09–S11]

边界：voice_type新增用例只证明解析/冻结，不是新语音wire闭环。所有已声明规则字段均须完整，是本轮明确采用的契约；未声明限制的固定协议常量不因此一律禁止。后台可发布defaults为空、要求用户填写的模型，提交时拒绝缺省，属于上轮允许的最小修复，不再要求另造规则引擎。

## 3. OVC-P4-02：Maestro/Comfy认证组合 —— 通过，关闭

本轮选择不扩建认证协议。`supported_protocol()` 在服务端拒绝两个原生类型的api_key模式，要求显式none。保存、发布、普通目录、提交和冻结版本装载复用这项检查；UI切换协议时选择none，禁用API Key选项并显示原因。[S06–S08]

基线红测记录Key模式被接受却发出匿名请求；新业务保存该模式400且零外呼。合法none模式由真实Worker分别完成Maestro目录/默认/生成/查询/下载，以及Comfy提交/查询/取图链路，普通editor可以读取生成图片。[S09–S11]

旧非法组合通过隔离夹具表示，测试覆盖目录隐藏、发布与提交拒绝、Worker及恢复拒绝、零外呼。没有修改生产旧数据来伪装修复，也没有因none模式取消私有目标所需的精确出站例外。[S07–S09]

## 4. OVC-P4-03：Replicate音频用途 —— 通过，关闭

已从可发布的Replicate用途中移除audio，保留text/image/video及既有豆包语音。该限制同样在旧配置目录与任务装载边界生效。[S06–S07]

红测真实请求取得有效WAV并由原Worker触发UnidentifiedImageError；绿测在发布时400且HTTP零次。旧组合的目录、提交、Worker和恢复均拒绝，不通过重标成功、错误后缀或换供应商绕过。[S09–S11]

无需为了通过P4新增Replicate音频或Maestro/Comfy Key协议。后续真要接入，作为明确的新功能处理；本轮不作承诺。

## 5. 浏览器闭环及安全扫描

本轮修改UI有真实工具记录：管理员表单创建两个原生none Provider、Replicate及OpenAI-compatible Provider；尝试Replicate audio得到发布400；defaults为空且max_tokens上限200的文本模型发布成功。普通manager的管理页请求被拒绝，任务缺max_tokens返回400并显示错误；输入100后独立Worker执行成功，页面出现已完成和脱敏正文。[S18–S20]

只读数据库审计4–8与配置/模型操作对应；最终任务`job-edb894a5420447378a1320fa36a53f11`为succeeded，冻结max_tokens=100，model/config/credential版本引用存在。fake text=1、wrong_auth=0；Web与Worker分别记录PID16764、28788。上述是实施端浏览器、PG、HTTP证据的交叉核对，不是审核端访问该实例。[S19]

扫描边界接受如实申报：本轮99份可读取JSON检查零canary，9份跳转后不可读取不计为通过，2条SSE response未做body扫描。PG37表49行、4份Web/Worker日志的已覆盖扫描零命中。原P4 SSE证据属于原SHA，不改写为本轮结果。密钥/egress代码本轮未重写，完整回归保留；不为这三项修复强制重跑原P4每一个浏览器抓包，也不把零命中当形式化安全证明。[S03,S16,S18–S20]

## 6. 正式运行证据

| 项目 | 结果 |
|---|---|
| 基线红测 | 4 failed / 2 passed / exit1，绑定c7 |
| P4-R1定向 | 17 passed / 43.87s / exit0，绑定e6 |
| 完整后端 | 368 passed / 2 warnings / 568.06s / exit0，绑定e6 |
| 前端 | 128 passed，0 failed/skipped，exit0 |
| TypeScript/Vite | 1827 modules / 8.79s / exit0 |
| app.routes/compile | 99 registered / 96 API全部分类 / 0未分类，均exit0 |

正式完整后端时间为2026-09-16 17:51:00.1323846–18:00:31.1632704 UTC。工作区开发运行另档，不混充固定SHA。定向新增17项与原351项全量合计368相符，但此算术不代替读取测试实现。[S09–S14]

早期夹具尚按api_key加载而失败、后改为native none的记录已披露；修复未删除实际原生执行断言。现有websockets弃用和Vite chunk警告不阻塞。本轮没有为历史超时编造根因或解决结论。[S17]

## 7. 审核端实际执行边界

审核端完成：连接器只读获取实际提交、代码、测试与证据，核对Git tree，检查三项修复和对应测试证明力；另实际运行环境探测及只读git ls-remote。

本容器git探测返回DNS解析失败，未安装psql/postgres/pwsh/powershell；没有独立重跑项目的PG、完整pytest/npm或浏览器。具体原始探测见`checks/environment.json`。本次没有额外运行源码摘录探针，也没有把实施端绿测写成审核端复跑。

未访问、停止、重启或清理用户7868、P3/P4历史实例或本轮7028。7028及测试数据按交付声明保留，不宣称已清理。没有修改远端仓库，没有真实付费调用。[S15,S17]

## 8. 下一单一授权任务

**P5-COLLAB-01：对象级分工协作前后端闭环。**

任务全文见`P5_CODEX_PROMPT.md`，对应已冻结P5和COLLAB-01…12。重点是同集不同对象各自保存、对象负责人、版本冲突、接管与剪辑租约、审核评论、AI候选结果，以及退役整份document写旁路。采用当前技术栈和最小必要数据边界，不做实时逐字共编、P6配额/分布式调度或部署平台。[S21–S23]

P5可以有多个小提交，但未完成前后端闭环之前不得自称P5通过或进入P6。通过结论只绑定本报告中的P4 HEAD；后续变更由新阶段验收。
