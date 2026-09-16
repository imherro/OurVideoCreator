# 多用户改造外部验收记录

开发者只能登记“已提交待审”；“通过/不通过/证据不足”由外部验收人给出并绑定具体 SHA。

| 阶段 | 提交状态 | 外部结论 | 被验收 SHA | 报告 | 阻塞问题 | 下一阶段授权 |
|---|---|---|---|---|---|---|
| P0 | P0-R1 已复验 | 通过 | `b957e39405522baf8ae7e3052b2938941e75b00b` | `evidence/P0-R1/REPORT.md` | 无；OVC-P0-01…05 全部关闭 | P1 |
| P1 | P1-R3 已复验 | 通过 | `6358c76f238a680dc9bd27b44968d5fe82db29d0` | `evidence/P1-R3/REPORT.md` | 无；`OVC-P1-R2-01` 已关闭；`OVC-P1-R3-N01` 为非阻塞观察 | P2 |
| P2 | P2-PG-01 READY_FOR_REVIEW | 未验收 | `a6820b045123ed73953cbe5667821225f8ceafb5` | `evidence/P2/REPORT.md` | 等待外部复核 | 否 |
| P3 | 未提交 | 未验收 | | | | 否 |
| P4 | 未提交 | 未验收 | | | | 否 |
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
