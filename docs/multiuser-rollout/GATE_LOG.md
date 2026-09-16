# 多用户改造外部验收记录

开发者只能登记“已提交待审”；“通过/不通过/证据不足”由外部验收人给出并绑定具体 SHA。

| 阶段 | 提交状态 | 外部结论 | 被验收 SHA | 报告 | 阻塞问题 | 下一阶段授权 |
|---|---|---|---|---|---|---|
| P0 | P0-R1 已复验 | 通过 | `b957e39405522baf8ae7e3052b2938941e75b00b` | `evidence/P0-R1/REPORT.md` | 无；OVC-P0-01…05 全部关闭 | P1 |
| P1 | P1-R3 已复验 | 通过 | `6358c76f238a680dc9bd27b44968d5fe82db29d0` | `evidence/P1-R3/REPORT.md` | 无；`OVC-P1-R2-01` 已关闭；`OVC-P1-R3-N01` 为非阻塞观察 | P2 |
| P2 | P2-R2 已复验 | 通过 | `a70341bad5c0da23153ad6cd44b67f2cd863dde1` | `evidence/P2-R2/REPORT.md` | 无；`OVC-P2-01…05`、`OVC-P2-R1-01` 全部关闭 | P3 |
| P3 | P3-R2 已复验 | 通过 | `de5ef13d6c772e62ec8a0e40be7be8abf1eb25d6` | `evidence/P3-R2/EXTERNAL_ACCEPTANCE.md` | 无；原六项及 R1-01/02/03 全部关闭 | P4 |
| P4 | P4-R1 READY_FOR_REVIEW | 首轮不通过；R1 待审 | `c7d6a88a06a01035fd44e45309414c05e061ab64`（首轮） | `evidence/P4-R1/REPORT.md` | `OVC-P4-01/02/03`（待外部关闭） | 否 |
| P5 | 未提交 | 未验收 | | | | 否 |
| P6 | 未提交 | 未验收 | | | | 否 |
| P7 | 未提交 | 未验收 | | | | 否 |
| P8 | 未提交 | 未验收 | | | | 不适用 |

## P0 首次外部验收记录

结论：不通过（2026-09-16，主 ChatGPT 会话审查新仓库 `imherro/OurVideoCreator` 的 `3c0e5ca`）

允许进入 P1：否

问题：`OVC-P0-01` 创建作品权限冲突；`02` 旧可写载体主源映射未闭合；`03` 实际注册路由覆盖不足；`04` 缺原始运行产物；`05` Worker/Provider 能力描述不准确。P0-R1 修复后以新 SHA 复验；Codex 不自行填写通过。

## P0-R1 外部复验记录

结论：**通过**（2026-09-16，主 ChatGPT 会话审查新仓库 `imherro/OurVideoCreator`）

通过 SHA：`b957e39405522baf8ae7e3052b2938941e75b00b`

关闭问题：`OVC-P0-01` 至 `OVC-P0-05`

新增阻塞：无

允许进入下一阶段：P1。P2、生产发布和真实付费 API 测试仍未授权。

非阻塞维护项：P1 更新文档时对齐导演台/租约/提示词库的验收编号；P3 实施 `ACL-09` 时将只读路由审计升级为“未分类即失败”的 CI 守卫，不改写既有验收编号含义。

## P1 首次外部验收记录

结论：**不通过**（2026-09-16，主 ChatGPT 会话审查新仓库 `imherro/OurVideoCreator`）

被审查 HEAD：`5ed0afa361b0e86590cd05b9ac285d9285854635`；其中被测试业务 SHA 为 `249b5d0176971c0d6eca510cc72ae0df91b75e1f`。

报告：`evidence/P1/REPORT.md`；原始命令日志与汇总：`evidence/P1/`。

阻塞问题：`OVC-P1-01` 启停脚本不能可靠证明进程属于当前工程根目录与实际数据目录；`OVC-P1-02` 进程验收未确定性证明 Web 重启发生在任务执行中。非阻塞问题：`OVC-P1-N01` 视频网关尾帧错误仍提到“内置引擎”。

处理状态：已授权仅实施 P1-R1；P2 未授权。P1-R1 必须使用独立 `evidence/P1-R1/`，不得覆盖 P1 原始日志，并以新业务 SHA 重新提交外部复验。

## P1-R1 待复验记录

状态：**READY_FOR_REVIEW**（2026-09-16）

被测试业务 SHA：`f27439fc9fcabd706e2772d5cd7212d76a9f4706`

报告：`evidence/P1-R1/REPORT.md`；原始命令日志与汇总：`evidence/P1-R1/`。

开发侧已逐项处理 OVC-P1-01、OVC-P1-02、OVC-P1-N01；是否关闭由外部验收人复核。P1-R1 未获通过前不授权 P2。

## P1-R1 外部复验记录

结论：**不通过**（2026-09-16，主 ChatGPT 会话审查新仓库 `imherro/OurVideoCreator`）

绑定 HEAD：`e698dcb2167cccd6c4797a49f2e4b1581b6c2b95`

已关闭：`OVC-P1-02`、`OVC-P1-N01`。

唯一阻塞：`OVC-P1-R1-01`（S2）。`Get-StudioIdentity()` 接收 `$Root` 却未用它约束 Python 模块加载目录，也未核对返回根目录；从另一工程目录通过绝对路径调用脚本时可能识别并操作调用方实例，相对 `MVC_DATA_DIR` 也可能按错误目录解析。

下一单一授权任务：P1-R2，只修工程目录绑定、相对数据目录统一及跨目录真实脚本回归。P2 仍未授权，新证据必须写入 `evidence/P1-R2/`，不得覆盖历史目录。

## P1-R2 待复验记录

状态：**READY_FOR_REVIEW**（2026-09-16）

被测试业务 SHA：`16a56194c7a15e71142696b283934ea1b7a2e3b5`

报告：`evidence/P1-R2/REPORT.md`；原始命令日志与汇总：`evidence/P1-R2/`。

开发侧已处理 `OVC-P1-R1-01`；是否关闭由外部验收人复核。P1-R2 未获通过前不授权 P2。

## P1-R2 外部复验记录

结论：**不通过**（2026-09-16，主 ChatGPT 会话审查新仓库 `imherro/OurVideoCreator`）

绑定 HEAD：`e4c61feba12765a6b70ecc9ee1e9db8e223372b1`；其中被测试业务 SHA 为 `16a56194c7a15e71142696b283934ea1b7a2e3b5`。

已关闭：`OVC-P1-R1-01`。保持关闭：`OVC-P1-02`、`OVC-P1-N01`。

唯一阻塞：`OVC-P1-R2-01`（S2）。`Start-Studio.ps1` 与 `Stop-Studio.ps1` 把规范化后的绝对 `MVC_DATA_DIR` 写回当前 PowerShell 进程但未恢复；同一会话连续调用不同工程时，前一次调用留下的数据目录可能让下一次调用读取并删除另一实例的生命周期记录。

下一单一授权任务：P1-R3，只修 `MVC_DATA_DIR`、`PYTHONUTF8` 的最外层环境恢复并增加同一 PowerShell PID 的连续真实脚本回归。P2 仍未授权，新证据必须写入 `evidence/P1-R3/`，不得覆盖历史目录。

## P1-R3 待复验记录

状态：**READY_FOR_REVIEW**（2026-09-16）

被测试业务 SHA：`7283fc513cdc8bd296b54e340875ead9431055e4`

报告：`evidence/P1-R3/REPORT.md`；原始命令日志、首轮超时和同 SHA 补跑记录：`evidence/P1-R3/`。

开发侧已处理 `OVC-P1-R2-01`；是否关闭由外部验收人复核。P1-R3 未获通过前不授权 P2。

## P1-R3 外部复验记录

结论：**通过**（2026-09-16，主 ChatGPT 会话只审查新仓库 `imherro/OurVideoCreator`）

通过 HEAD：`6358c76f238a680dc9bd27b44968d5fe82db29d0`；被测试业务 SHA：`7283fc513cdc8bd296b54e340875ead9431055e4`。

关闭：`OVC-P1-R2-01`，原 `OVC-P1-01` 整体关闭。保持关闭：`OVC-P1-R1-01`、`OVC-P1-02`、`OVC-P1-N01`。新增阻塞：无。

非阻塞观察：`OVC-P1-R3-N01`（S3），首次全量测试的一次本机 HTTP 超时未归因；首轮失败日志必须保留，不能宣称根因已解决。P2 改造进程测试时补充失败出口的 Web/Worker/fake 日志、请求时间和安全可读数据库状态，不自动重试有副作用的 POST，也不以无限补跑掩盖。

下一阶段授权：P2。下一单一任务：`P2-PG-01`，把现有保留业务完整切换到 PostgreSQL，建立空库、Web、独立 Worker 的运行闭环。P3、公网部署和真实付费 API 测试仍未授权。

## P2-PG-01 待复验记录

状态：**READY_FOR_REVIEW**（2026-09-16）

被测试业务 SHA：`a6820b045123ed73953cbe5667821225f8ceafb5`

报告：`evidence/P2/REPORT.md`；Schema/事务说明：`design/P2_STORAGE_CHANGELOG.md`；正式原始日志：`evidence/P2/00-context.log` 至 `11-cleanup.log`。

开发侧已完成 PostgreSQL 唯一主库、独立 Alembic 空库迁移、完整保留业务表、并发 revision 冲突、事务回滚、同库单 Worker advisory lock、存储边界、离线 Stop、PowerShell 5.1/7 生命周期和全量回归。外部结论尚未填写，P3 仍未授权。

取证时在旧业务 SHA `938b665e133ab014f1820991720da973082592a0` 的手工 Stop 中发现 PowerShell 7 时间精度缺陷；旧证据已废弃并保存在 `evidence/P2/attempts/938b665/`。修复后在新业务 SHA 上从空库重新运行全部正式证据。

## P2-PG-01 外部复验记录

结论：**不通过**（2026-09-16，主 ChatGPT 会话审查协作版新仓库 `imherro/OurVideoCreator`）。

绑定 evidence HEAD：`a8f532e390706e00cee28585a01f0ece332e94d8`；被测试业务 SHA：`a6820b045123ed73953cbe5667821225f8ceafb5`。

P0/P1 继续保持通过。P2 阻塞项：`OVC-P2-01` Worker 锁连接死亡后仍可能领取；`OVC-P2-02` prompt 首次写和两个 `MAX+1` 路径存在并发竞态；`OVC-P2-03` resume/cancel 可由 stale resume 覆盖；`OVC-P2-04` 多个 event 与业务状态不在同一事务；`OVC-P2-05` SSE identity ID 与提交顺序不一致可永久漏事件。

下一单一授权任务：P2-R1，只修上述五项、补真实 PostgreSQL 并发/失败注入/游标测试并在新目录取证。P3 仍未授权。

## P2-R1 待复验记录

状态：**READY_FOR_REVIEW**（2026-09-16）

被测试业务 SHA：`246db511bd950e649f59600a5f6cd2ed183be71e`

报告：`evidence/P2-R1/REPORT.md`；结构化并发轨迹：`evidence/P2-R1/01-p2-r1-targeted.log`；正式全量：`evidence/P2-R1/02-pytest-full.log`。

开发侧已逐项处理 `OVC-P2-01` 至 `OVC-P2-05`，正式验证为 P2-R1 定向 10/10、Python 全量 273/273、原 P2/进程回归 13/13、前端 126/126、构建通过。是否关闭和 P2 是否通过由外部验收人复核；未开始 P3。

## P2-R1 外部复验记录

结论：**不通过**（2026-09-16，主 ChatGPT 会话只审查协作版新仓库 `imherro/OurVideoCreator`）。

绑定 evidence HEAD：`1ae1544ce62e9fa351a6d7a4da09c281544658dd`；被测试业务 SHA：`246db511bd950e649f59600a5f6cd2ed183be71e`。

关闭：`OVC-P2-01`、`OVC-P2-02`、`OVC-P2-03`、`OVC-P2-04`。`OVC-P2-05` 的事务发布顺序、业务/event 原子性和按行保留已认可，但剩余 `OVC-P2-R1-01`（S2）：`_event_cursor()` 仍按 Identity 数值差判断积压，大 rollback 空洞可跳过仍保留的新事件。

下一单一任务：P2-R2，只修实际可见积压/保留边界判断，并补 500 次真实 rollback 后通过 `Last-Event-ID` 和 `after` 读取实际流的回归。P3 仍未授权。

## P2-R2 待复验记录

状态：**READY_FOR_REVIEW**（2026-09-16）

被测试业务 SHA：`fc8feee3d9c3bfaffb39c55ab10d41e0fff7050f`

报告：`evidence/P2-R2/REPORT.md`；修复前失败：`evidence/P2-R2/00-prefix-large-gap-failure.log`；修复后专项：`evidence/P2-R2/02-p2-r2-targeted.log`；正式全量：`evidence/P2-R2/03-pytest-full.log`。

开发侧只处理 `OVC-P2-R1-01`：重连判断使用同一 SQL 快照中的实际可见积压行数和保留边界。正式结果为 P2-R2 定向 8/8、Python 全量 276/276、P2/进程回归 20/20、前端 126/126、构建通过。是否关闭剩余阻塞和 P2 是否通过由外部验收人复核；未开始 P3。

## P2-R2 外部复验记录

结论：**通过**（2026-09-16，主 ChatGPT 会话只审查协作版新仓库 `imherro/OurVideoCreator`）。

通过 HEAD：`a70341bad5c0da23153ad6cd44b67f2cd863dde1`；被测试业务 SHA：`fc8feee3d9c3bfaffb39c55ab10d41e0fff7050f`。

本次关闭：`OVC-P2-R1-01`，原 `OVC-P2-05` 整体关闭。保持关闭：`OVC-P2-01`、`OVC-P2-02`、`OVC-P2-03`、`OVC-P2-04`。新增阻塞：无。

非阻塞观察：`OVC-P2-R2-N01`（S3），开发组合运行中一次 PostgreSQL connect timeout 仍未归因；不能写成根因已解决。历史 `OVC-P1-R3-N01` 继续保留。

下一阶段授权：P3。下一单一任务：`P3-ID-01`（邀请制账号、团队/作品隔离与基础页面闭环）。P4 及后续实施、公网部署、真实付费 API 未授权。

## P3-ID-01 待复验记录

状态：**READY_FOR_REVIEW**（2026-09-16）

被测试业务 SHA：`8b9c74607b46d8c09fb5d6445e46d57fead4f2b3`

报告：`evidence/P3/REPORT.md`；正式原始日志：`evidence/P3/01-p3-targeted.log` 至 `06-compile.log`；浏览器补充：`evidence/P3/07-browser-manual.md`。

开发侧已完成邀请制个人账号、团队/作品角色隔离、嵌套资源授权、素材读取与签名、SSE 撤权、管理/成员基础页面和 ACL-09 fail-closed 路由守卫。正式结果为 P3 定向 7/7、Python 全量 283/283、前端 126/126、构建通过、85/85 API 已分类。是否通过由外部验收人复核；P4 未开始。

## P3-ID-01 外部验收记录

结论：**不通过**（2026-09-16，主 ChatGPT 会话只审查协作版新仓库 `imherro/OurVideoCreator`）。

绑定最终 HEAD：`dc1b0083db90ac1960b1f88117fa673e878c7baf`；被测试业务 SHA：`8b9c74607b46d8c09fb5d6445e46d57fead4f2b3`。

P0/P1/P2 保持通过。P3 阻塞项：`OVC-P3-01` 批量章节删除绕过 manager 限制；`OVC-P3-02` 团队撤权与作品授权并发可留下孤立授权；`OVC-P3-03` 旧密码登录可在重置后迟到签发 session；`OVC-P3-04` 最后 owner/admin 并发保护不足；`OVC-P3-05` 限流晚于密码哈希且成功登录错误清空共享 IP 记录；`OVC-P3-06` 管理页面缺少重置/撤权闭环，浏览器与 ACL-09 负向证据不足。

下一单一授权任务：P3-R1，集中修复上述六项并在 `evidence/P3-R1/` 重新取证。P4、公网部署和真实付费 API 仍未授权。

## P3-R1 待复验记录

状态：**READY_FOR_REVIEW**（2026-09-16）

被测试业务 SHA：`a8cd59e8247b915737084383f5b53df1f831f4fe`

报告：`evidence/P3-R1/REPORT.md`；正式日志与结构化证据：`evidence/P3-R1/01-p3-r1-targeted.log` 至 `08-browser-db-audit.json`。

开发侧已逐项处理 `OVC-P3-01…06`：统一批量删除权限、串行化成员/授权和最后管理员/owner 不变量、串行化登录/重置、限流前置与共享 IP 记录保留、补齐管理 UI 与真实路由负向测试。正式结果为 P3-R1 定向 12/12、Python 全量 288/288、前端 126/126、构建通过、85/85 API 已分类，并完成双浏览器隔离闭环。是否关闭阻塞和 P3 是否通过由外部验收人复核；P4 未开始。

## P3-R1 外部复验记录

结论：**不通过**（2026-09-16，主 ChatGPT 会话只审查协作版新仓库 `imherro/OurVideoCreator`）。

绑定 evidence HEAD：`5e0c5e36d37415d4867d380f4e86dd47c87eebce`；被测试业务 SHA：`a8cd59e8247b915737084383f5b53df1f831f4fe`。

关闭：`OVC-P3-01`、`OVC-P3-02`、`OVC-P3-04`。部分完成：`OVC-P3-03`、`OVC-P3-05`、`OVC-P3-06`。

剩余阻塞：`OVC-P3-R1-01`（S2，首次限流桶不存在时并发请求可一起通过旧检查）；`OVC-P3-R1-02`（S2，同用户并发签发可能留下两个有效重置令牌，且签发/消费需统一 user→token 锁顺序）；`OVC-P3-R1-03`（S2，必须实际点击新增管理控件并提交可追溯浏览器/请求/DOM/审计原始证据）。

下一单一任务：P3-R2，只补上述三个残留项并写入 `evidence/P3-R2/`。P0/P1/P2 历史通过不变；P4、公网部署和真实付费 API 仍未授权。

## P3-R2 待复验记录

状态：**READY_FOR_REVIEW**（2026-09-16）。被测业务 SHA：`cd61996bf6908f66cfd3429d27fa42acb03c144d`。

报告及原始证据：`evidence/P3-R2/REPORT.md`、00–13 日志/JSON/浏览器记录。正式定向 27、Python 全量 303、前端 126，build/route/compile exit 0；基线真实 PG 死锁、首次预算失守和双有效重置 token 红测已保存。页面流程在独立 host-only Cookie 上下文完成，两次 native confirm 由用户协助，失败尝试和取证限制如实保留。

三个残留项是否关闭、P3 是否通过均待外部验收人复核；不自行签发通过，P4 未开始。

## P3-R2 外部复验通过

结论：**通过，P3 已通过，允许进入 P4**（2026-09-16，用户指定的主 ChatGPT 会话，完整绑定及运行边界见 `evidence/P3-R2/EXTERNAL_ACCEPTANCE.md`）。

通过 evidence HEAD：`de5ef13d6c772e62ec8a0e40be7be8abf1eb25d6`；被测业务 SHA：`cd61996bf6908f66cfd3429d27fa42acb03c144d`。

本次关闭 `OVC-P3-R1-01`、`OVC-P3-R1-02`、`OVC-P3-R1-03`，原 `OVC-P3-01…06` 整体关闭，无新增阻塞，不需要 P3-R3。浏览器证据按人工协助验证认可，不冒称全自动。P0/P1/P2 历史通过不变，既有 warning 和历史未归因超时继续保留。

下一单一授权任务：**P4-MODEL-01，平台统一 Provider/Key/模型后台与受控调用闭环**。只授权 P4；P5/P6 等后续阶段、公网部署、真实付费 API 仍未授权。完整外部任务归档于 `prompts/P4_CODEX_PROMPT.md`，P4 完成后必须再次外部验收。

## P4-MODEL-01 待验收记录

状态：**READY_FOR_REVIEW**（2026-09-17）。被测试业务 SHA：`3a73165f74520d0c15ec6f0750d7b2c105108744`；实现 SHA：`0e64bd0540ad53de5ea6d93013c14d5154760867`。

报告及证据：`evidence/P4/REPORT.md`、`SUMMARY.json` 和原始日志/浏览器记录。最终真实 PG 后端 351 passed、前端 128 passed、构建和编译 exit 0，96/96 API 分类。实际 UI 保存 Provider/Key/发布模型后，普通获权账号选择并提交文本、异步图片，独立 Worker 成功返回结果；四角色管理拒绝、嵌套覆盖、密钥异常、A/B HTTP 轮换/吊销和出站边界有对应负向测试。浏览器/前端 SHA 与最终业务间仅测试断言不同，运行时代码相同，明确记录而不冒称重跑。

尚未获 P4 外部验收；P5、上线和真实付费 API 仍未授权。只向协作版新仓库提交，外部审核应聚焦已冻结功能与实际缺陷，避免过度设计。

## P4-MODEL-01 外部验收：不通过，授权 P4-R1

2026-09-17 用户指定 ChatGPT 主会话正式结论：**P4 不通过，暂不允许进入 P5**。绑定业务 `3a73165f74520d0c15ec6f0750d7b2c105108744`、证据 HEAD `c7d6a88a06a01035fd44e45309414c05e061ab64`。

仅授权下一单一任务 **P4-R1**，集中修复三个 S2：

- `OVC-P4-01`：省略参数后适配器缺省值可越过平台发布范围（max_tokens 上限 200 实际发 4096）。
- `OVC-P4-02`：Maestro/Comfy 接受 api_key 认证模式，却发送匿名请求。
- `OVC-P4-03`：Replicate audio 可发布和入队，但结果以 PNG 图像登记。

外部认可既有平台权限、CSRF、秘密加密/失败关闭、出站保护、A/B 版本轮换及真实文本/图片浏览器闭环证据；不新增浏览器证据缺口，不要求新增音频供应商或认证平台。P0/P1/P2/P3 历史通过不变。

已下载并完整读取原始审核包及返修提示词。原件见 `reviews/P4/REVIEW.md`、`MATRIX.md`、`GATE_DECISION.json`；完整执行要求见 `prompts/P4_R1_CODEX_PROMPT.md`。新证据写入 `evidence/P4-R1/`，保留旧证据和 7868/7895/6313/6185 实例。当前仅返修开始，不声称三个问题已经修复。

## P4-R1 待复验记录

2026-09-17 状态 **READY_FOR_REVIEW**。固定业务 `e6c3edd95830d4c778fee357b8807d1443920a04`；后续 evidence 提交仅 docs。三个缺陷的真实 API/PG/Worker/guarded HTTP 红测 4 failed / 2 passed；修复后定向 17 passed，正式完整后端 368 passed / 2 warnings / exit 0，前端 128 passed、build 1827 modules、compile/routes exit 0。

新建 7028 隔离浏览器实例验证原生认证提示、Replicate audio 发布 400、普通用户缺失 max_tokens 400、填写 100 后独立 Worker 成功。证据在 `evidence/P4-R1/`，含真实工具调用/返回、安全扫描范围和未运行项。没有改动旧实例或调用真实付费 Provider。

仅提交外部复验，**不自行关闭 OVC-P4-01/02/03，不授予 P5 权限**。请在协作版 OurVideoCreator 新仓库审核实际功能和最小修复，避免过度设计。
